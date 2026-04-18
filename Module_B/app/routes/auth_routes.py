from fastapi import APIRouter, HTTPException, Depends
from app.db import get_db
from app.auth import create_session, get_current_user

router = APIRouter()

@router.post("/login")
def login(data: dict):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM login_credentials WHERE Email=%s
    """, (data["email"],))

    user = cursor.fetchone()

    if not user or user["PasswordHash"] != data["password"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    session_id = create_session(user["MemberID"])

    return {"session_token": session_id}


@router.get("/isAuth")
def is_auth(user=Depends(get_current_user)):
    return {
        "message": "User authenticated",
        "role": user["Role"],
        "user": user["Name"]
    }


# from fastapi import APIRouter, HTTPException
# from app.db import get_db
# from app.auth import create_session

# router = APIRouter()

# @router.post("/login")
# def login(data: dict):
#     db = get_db()
#     cursor = db.cursor(dictionary=True)

#     cursor.execute("""
#         SELECT * FROM login_credentials WHERE Email=%s
#     """, (data["email"],))

#     user = cursor.fetchone()

#     if not user or user["PasswordHash"] != data["password"]:
#         raise HTTPException(status_code=401, detail="Invalid credentials")

#     session_id = create_session(user["MemberID"])

#     return {"session_token": session_id}