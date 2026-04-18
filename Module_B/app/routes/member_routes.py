"""
member_routes.py  –  ScholarEase  |  Assignment 4
--------------------------------------------------
All member queries are routed to the correct real shard server.

  INSERT  -> primary DB (auto-ID) then correct shard server
  LOOKUP  -> correct shard server using MemberID % 3
  DELETE  -> correct shard server + primary DB cleanup
  RANGE   -> fan-out across all 3 shard servers, merge in app
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import SHARD_PORTS, get_db, get_shard_db
from app.utils.logger import log_action
from app.utils.shard_utils import all_shard_indices, get_shard_index, get_shard_table

router = APIRouter()


class MemberCreate(BaseModel):
    name: str
    email: str
    phone: str
    age: int
    role: str


def _fetch_member_from_shard(member_id: int):
    """Read one member from exactly one shard using the shard key."""
    shard_idx = get_shard_index(member_id)
    shard_table = get_shard_table(member_id)
    shard_conn = get_shard_db(shard_idx)
    sc = shard_conn.cursor(dictionary=True)

    try:
        sc.execute(
            f"""
            SELECT MemberID, Name, Email, PhoneNo, Age, Role
            FROM {shard_table}
            WHERE MemberID = %s
            """,
            (member_id,),
        )
        result = sc.fetchone()
    finally:
        sc.close()
        shard_conn.close()

    return result


def _fetch_members_in_range(start_id: int, end_id: int):
    """
    Fan-out range query across all shards and merge results.
    For hash-based sharding, any ID range may exist on every shard.
    """
    result = []

    for shard_idx in all_shard_indices():
        shard_table = f"shard_{shard_idx}_member"
        shard_conn = get_shard_db(shard_idx)
        sc = shard_conn.cursor(dictionary=True)

        try:
            sc.execute(
                f"""
                SELECT MemberID, Name, Email, PhoneNo, Age, Role
                FROM {shard_table}
                WHERE MemberID BETWEEN %s AND %s
                ORDER BY MemberID
                """,
                (start_id, end_id),
            )
            result.extend(sc.fetchall())
        finally:
            sc.close()
            shard_conn.close()

    result.sort(key=lambda row: row["MemberID"])
    return result


@router.post("/member")
def create_member(data: MemberCreate, user=Depends(get_current_user)):
    if user["Role"] != "Admin":
        log_action(f"UNAUTHORIZED: {user['Role']} {user['MemberID']} tried to create a member")
        raise HTTPException(status_code=403, detail="Access denied")

    log_action(f"{user['Role']} {user['MemberID']} creating member {data.email}")

    primary = get_db()
    pc = primary.cursor()
    shard_conn = None
    sc = None
    new_id = None
    shard_idx = None
    shard_table = None

    try:
        # Keep primary uncommitted until shard write succeeds.
        pc.execute(
            """
            INSERT INTO member (Name, Email, PhoneNo, Age, Role)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (data.name, data.email, data.phone, data.age, data.role),
        )
        new_id = pc.lastrowid

        shard_idx = get_shard_index(new_id)
        shard_table = get_shard_table(new_id)
        shard_conn = get_shard_db(shard_idx)
        sc = shard_conn.cursor()

        sc.execute(
            f"""
            INSERT INTO {shard_table}
                (MemberID, Name, Email, PhoneNo, Age, Role)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (new_id, data.name, data.email, data.phone, data.age, data.role),
        )

        shard_conn.commit()
        primary.commit()

    except Exception as e:
        if shard_conn:
            try:
                shard_conn.rollback()
            except Exception:
                pass
        try:
            primary.rollback()
        except Exception:
            pass
        log_action(f"CREATE MEMBER FAILED for {data.email}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create member: {str(e)}")
    finally:
        if sc:
            sc.close()
        if shard_conn:
            shard_conn.close()
        pc.close()
        primary.close()

    log_action(
        f"Member {data.email} (ID={new_id}) created -> "
        f"Shard {shard_idx} (port {SHARD_PORTS[shard_idx]}) / {shard_table}"
    )

    return {
        "message": "Member created",
        "MemberID": new_id,
        "shard": shard_idx,
        "shard_table": shard_table,
    }


@router.get("/member/{member_id}")
def get_member(member_id: int, user=Depends(get_current_user)):
    if user["Role"] not in ["Admin", "Authority"]:
        raise HTTPException(status_code=403, detail="Admin or Authority access required")

    result = _fetch_member_from_shard(member_id)
    if not result:
        raise HTTPException(status_code=404, detail="Member not found")

    shard_idx = get_shard_index(member_id)
    log_action(
        f"{user['Role']} {user['MemberID']} looked up member {member_id} "
        f"from shard {shard_idx}"
    )
    return result


@router.delete("/member/{member_id}")
def delete_member(member_id: int, current_user: dict = Depends(get_current_user)):
    if current_user["Role"] != "Admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    if member_id == current_user["MemberID"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    shard_idx = get_shard_index(member_id)
    shard_table = get_shard_table(member_id)

    shard_conn = get_shard_db(shard_idx)
    sc = shard_conn.cursor()
    primary = get_db()
    pc = primary.cursor()

    try:
        sc.execute(f"SELECT MemberID FROM {shard_table} WHERE MemberID = %s", (member_id,))
        if not sc.fetchone():
            raise HTTPException(status_code=404, detail="Member not found in shard")

        sc.execute(f"DELETE FROM {shard_table} WHERE MemberID = %s", (member_id,))
        pc.execute("DELETE FROM member WHERE MemberID = %s", (member_id,))

        shard_conn.commit()
        primary.commit()
    except HTTPException:
        try:
            shard_conn.rollback()
            primary.rollback()
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            shard_conn.rollback()
            primary.rollback()
        except Exception:
            pass
        log_action(f"DELETE MEMBER FAILED for {member_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete member: {str(e)}")
    finally:
        sc.close()
        shard_conn.close()
        pc.close()
        primary.close()

    log_action(f"Admin {current_user['MemberID']} deleted member {member_id} from Shard {shard_idx}")

    return {
        "message": "Member deleted successfully",
        "shard": shard_idx,
        "shard_table": shard_table,
    }


@router.get("/members/range")
def get_members_in_range(
    start_id: int = Query(..., ge=1),
    end_id: int = Query(..., ge=1),
    user=Depends(get_current_user),
):
    if user["Role"] not in ["Admin", "Authority"]:
        raise HTTPException(status_code=403, detail="Admin or Authority access required")
    if start_id > end_id:
        raise HTTPException(status_code=400, detail="start_id must be <= end_id")

    result = _fetch_members_in_range(start_id, end_id)

    log_action(
        f"{user['Role']} {user['MemberID']} ran range query from {start_id} to {end_id} "
        f"across all shards"
    )

    return {
        "start_id": start_id,
        "end_id": end_id,
        "count": len(result),
        "members": result,
    }


@router.get("/profile")
def get_profile(user=Depends(get_current_user)):
    if user["Role"] == "Student":
        result = _fetch_member_from_shard(user["MemberID"])
        if not result:
            raise HTTPException(status_code=404, detail="Profile not found in shard")
        return result

    elif user["Role"] in ["Admin", "Authority"]:
        # Keep UI behavior same as current project: admins/authorities see all members.
        return _fetch_members_in_range(1, 10**9)

    log_action(f"UNAUTHORIZED: Invalid role {user['Role']} accessing profile")
    raise HTTPException(status_code=403, detail="Invalid role")



# """
# --------------------------------------------------
# All member queries are routed to the correct real shard server.

#   INSERT  → primary DB (auto-ID) then mirror to correct shard server
#   GET     → shard server (single-key via get_shard_index)
#   DELETE  → shard server + primary DB
#   RANGE   → fan-out across all 3 shard servers, merge in app
# """

# from fastapi import APIRouter, Depends, HTTPException
# from app.auth import get_current_user
# from app.db import get_db, get_shard_db, SHARD_PORTS
# from app.utils.logger import log_action
# from app.utils.shard_utils import get_shard_index, get_shard_table, all_shard_indices
# from pydantic import BaseModel

# router = APIRouter()


# class MemberCreate(BaseModel):
#     name: str
#     email: str
#     phone: str
#     age: int
#     role: str


# # ── POST /member  (Admin only) ────────────────────────────────────────────────

# @router.post("/member")
# def create_member(data: MemberCreate, user=Depends(get_current_user)):
#     if user["Role"] != "Admin":
#         log_action(f"UNAUTHORIZED: {user['Role']} {user['MemberID']} tried to create a member")
#         raise HTTPException(status_code=403, detail="Access denied")

#     log_action(f"{user['Role']} {user['MemberID']} creating member {data.email}")

#     # 1. Insert into primary DB to get auto-generated MemberID
#     primary = get_db()
#     pc = primary.cursor()
#     try:
#         pc.execute("""
#             INSERT INTO member (Name, Email, PhoneNo, Age, Role)
#             VALUES (%s, %s, %s, %s, %s)
#         """, (data.name, data.email, data.phone, data.age, data.role))
#         primary.commit()
#         new_id = pc.lastrowid
#     finally:
#         pc.close()
#         primary.close()

#     # 2. Route to the correct shard server
#     shard_idx   = get_shard_index(new_id)
#     shard_table = get_shard_table(new_id)
#     shard_conn  = get_shard_db(shard_idx)
#     sc = shard_conn.cursor()
#     try:
#         sc.execute(f"""
#             INSERT IGNORE INTO {shard_table}
#                 (MemberID, Name, Email, PhoneNo, Age, Role)
#             VALUES (%s, %s, %s, %s, %s, %s)
#         """, (new_id, data.name, data.email, data.phone, data.age, data.role))
#         shard_conn.commit()
#     finally:
#         sc.close()
#         shard_conn.close()

#     # FIX: use SHARD_PORTS dict instead of hardcoded arithmetic (3307 + shard_idx)
#     log_action(
#         f"Member {data.email} (ID={new_id}) created "
#         f"→ Shard {shard_idx} (port {SHARD_PORTS[shard_idx]}) / {shard_table}"
#     )

#     return {
#         "message": "Member created",
#         "MemberID": new_id,
#         "shard": shard_idx,
#         "shard_table": shard_table,
#     }


# # ── DELETE /member/{member_id}  (Admin only) ──────────────────────────────────

# @router.delete("/member/{member_id}")
# async def delete_member(member_id: int, current_user: dict = Depends(get_current_user)):
#     if current_user["Role"] != "Admin":
#         raise HTTPException(status_code=403, detail="Admin access required")
#     if member_id == current_user["MemberID"]:
#         raise HTTPException(status_code=400, detail="Cannot delete your own account")

#     shard_idx   = get_shard_index(member_id)
#     shard_table = get_shard_table(member_id)

#     # Delete from shard server
#     shard_conn = get_shard_db(shard_idx)
#     sc = shard_conn.cursor()
#     try:
#         sc.execute(f"SELECT MemberID FROM {shard_table} WHERE MemberID = %s", (member_id,))
#         if not sc.fetchone():
#             raise HTTPException(status_code=404, detail="Member not found in shard")
#         sc.execute(f"DELETE FROM {shard_table} WHERE MemberID = %s", (member_id,))
#         shard_conn.commit()
#     finally:
#         sc.close()
#         shard_conn.close()

#     # Also delete from primary DB
#     primary = get_db()
#     pc = primary.cursor()
#     try:
#         pc.execute("DELETE FROM member WHERE MemberID = %s", (member_id,))
#         primary.commit()
#     finally:
#         pc.close()
#         primary.close()

#     log_action(f"Admin {current_user['MemberID']} deleted member {member_id} from Shard {shard_idx}")

#     return {
#         "message": "Member deleted successfully",
#         "shard": shard_idx,
#         "shard_table": shard_table,
#     }


# # ── GET /profile  (role-aware) ────────────────────────────────────────────────

# @router.get("/profile")
# def get_profile(user=Depends(get_current_user)):

#     if user["Role"] == "Student":
#         # Single-key lookup → route directly to the one correct shard server
#         shard_idx   = get_shard_index(user["MemberID"])
#         shard_table = get_shard_table(user["MemberID"])
#         shard_conn  = get_shard_db(shard_idx)
#         sc = shard_conn.cursor(dictionary=True)
#         try:
#             sc.execute(f"""
#                 SELECT MemberID, Name, Email, PhoneNo, Role, Age
#                 FROM {shard_table}
#                 WHERE MemberID = %s
#             """, (user["MemberID"],))
#             result = sc.fetchone()
#         finally:
#             sc.close()
#             shard_conn.close()
#         return result

#     elif user["Role"] in ["Admin", "Authority"]:
#         # Range query → fan-out: query ALL 3 shard servers and merge results
#         result = []
#         for shard_idx in all_shard_indices():
#             shard_table = f"shard_{shard_idx}_member"
#             shard_conn  = get_shard_db(shard_idx)
#             sc = shard_conn.cursor(dictionary=True)
#             try:
#                 sc.execute(f"""
#                     SELECT MemberID, Name, Email, PhoneNo, Role, Age
#                     FROM {shard_table}
#                 """)
#                 result.extend(sc.fetchall())
#             finally:
#                 sc.close()
#                 shard_conn.close()
#         return result

#     else:
#         log_action(f"UNAUTHORIZED: Invalid role {user['Role']} accessing profile")
#         raise HTTPException(status_code=403, detail="Invalid role")