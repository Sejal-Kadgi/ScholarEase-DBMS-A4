from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader
import uuid

from app.db import get_db, get_shard_db
from app.utils.shard_utils import get_shard_index, get_shard_table


def create_session(member_id: int) -> str:
    """Create a session in the primary database and return the session token."""
    db = get_db()
    cursor = db.cursor()
    session_id = str(uuid.uuid4())

    try:
        cursor.execute(
            """
            INSERT INTO session (SessionID, MemberID, ExpiresAt)
            VALUES (%s, %s, NOW() + INTERVAL 1 DAY)
            """,
            (session_id, member_id),
        )
        db.commit()
        return session_id
    finally:
        cursor.close()
        db.close()


api_key_header = APIKeyHeader(name="Authorization")


def get_current_user(token: str = Depends(api_key_header)):
    """
    Resolve the logged-in user in two hops:
      1. Read MemberID from the unsharded session table in the primary DB.
      2. Route to the correct member shard using MemberID % 3.

    This keeps session/login tables centralized while member data is sharded.
    """
    primary = get_db()
    pc = primary.cursor(dictionary=True)

    try:
        pc.execute(
            """
            SELECT MemberID
            FROM session
            WHERE SessionID = %s AND ExpiresAt > NOW()
            """,
            (token,),
        )
        session_row = pc.fetchone()
    finally:
        pc.close()
        primary.close()

    if not session_row:
        raise HTTPException(status_code=401, detail="Invalid session")

    member_id = session_row["MemberID"]
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
        user = sc.fetchone()
    finally:
        sc.close()
        shard_conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Session user not found in shard")

    return user


# from fastapi import Header, HTTPException, Depends
# import uuid
# from app.db import get_db
# from fastapi.security import APIKeyHeader

# def create_session(member_id):
#     db = get_db()
#     cursor = db.cursor()

#     session_id = str(uuid.uuid4())

#     cursor.execute("""
#         INSERT INTO session (SessionID, MemberID, ExpiresAt)
#         VALUES (%s, %s, NOW() + INTERVAL 1 DAY)
#     """, (session_id, member_id))

#     db.commit()
#     return session_id


# api_key_header = APIKeyHeader(name="Authorization")

# def get_current_user(token: str = Depends(api_key_header)):
#     from app.db import get_db

#     db = get_db()
#     cursor = db.cursor(dictionary=True)

#     cursor.execute("""
#         SELECT m.*
#         FROM session s
#         JOIN member m ON s.MemberID = m.MemberID
#         WHERE s.SessionID = %s AND s.ExpiresAt > NOW()
#     """, (token,))

#     user = cursor.fetchone()

#     if not user:
#         raise HTTPException(status_code=401, detail="Invalid session")

#     return user


# # def get_current_user(Authorization: str = Header(None)):
# #     if not Authorization:
# #         raise HTTPException(status_code=401, detail="No token provided")

# #     db = get_db()
# #     cursor = db.cursor(dictionary=True)

# #     cursor.execute("""
# #         SELECT m.*
# #         FROM session s
# #         JOIN member m ON s.MemberID = m.MemberID
# #         WHERE s.SessionID = %s AND s.ExpiresAt > NOW()
# #     """, (Authorization,))

# #     user = cursor.fetchone()

# #     if not user:
# #         raise HTTPException(status_code=401, detail="Invalid session")

# #     return user


# # import uuid
# # from app.db import get_db

# # def create_session(member_id):
# #     db = get_db()
# #     cursor = db.cursor()

# #     session_id = str(uuid.uuid4())

# #     cursor.execute("""
# #         INSERT INTO session (SessionID, MemberID, ExpiresAt)
# #         VALUES (%s, %s, NOW() + INTERVAL 1 DAY)
# #     """, (session_id, member_id))

# #     db.commit()
# #     return session_id


# # def get_user_from_session(token):
# #     db = get_db()
# #     cursor = db.cursor(dictionary=True)

# #     cursor.execute("""
# #         SELECT m.*
# #         FROM session s
# #         JOIN member m ON s.MemberID = m.MemberID
# #         WHERE s.SessionID = %s AND s.ExpiresAt > NOW()
# #     """, (token,))

# #     return cursor.fetchone()
