from fastapi import APIRouter, Depends, HTTPException
from app.auth import get_current_user
from app.db import get_db
from app.utils.logger import log_action

router = APIRouter()

@router.post("/payment")
def make_payment(data: dict, user=Depends(get_current_user)):

    if user["Role"] != "Authority":
        log_action(f"UNAUTHORIZED: {user['Role']} {user['MemberID']} tried to process payment")
        raise HTTPException(status_code=403, detail="Only authority can process payment")

    log_action(f"{user['Role']} {user['MemberID']} started payment for application {data['application_id']}")

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO payment
        (ApplicationID, AmountPaid, PaymentDate, BankAccountID, Status)
        VALUES (%s, %s, CURDATE(), %s, 'Completed')
    """, (data["application_id"], data["amount"], data["bank_id"]))

    db.commit()

    log_action(f"{user['Role']} {user['MemberID']} completed payment for application {data['application_id']}")

    return {"message": "Payment completed"}


# from fastapi import APIRouter, HTTPException
# from app.db import get_db

# router = APIRouter()

# @router.post("/payment")
# def make_payment(data: dict):
#     db = get_db()
#     cursor = db.cursor()

#     cursor.execute("""
#         INSERT INTO payment (ApplicationID, AmountPaid, PaymentDate, BankAccountID, Status)
#         VALUES (%s, %s, CURDATE(), %s, 'Completed')
#     """, (data["application_id"], data["amount"], data["bank_id"]))

#     db.commit()

#     return {"message": "Payment done"}