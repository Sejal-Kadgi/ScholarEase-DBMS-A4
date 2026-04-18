from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from app.auth import get_current_user
from app.db import get_db
from app.utils.logger import log_action
import mysql

router = APIRouter()

@router.get("/scholarships")
def get_scholarships():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM scholarship")
    return cursor.fetchall()


@router.get("/applications")
def get_applications(user=Depends(get_current_user)):
    if user["Role"] != "Student":
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM scholarship_application")
        return cursor.fetchall()
    elif user["Role"] in ["Admin", "Authority"]:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM scholarship_application where StudentID=%s", (user["MemberID"],))
        return cursor.fetchall()
    

# @router.post("/apply")
# def apply_scholarship(data: dict, user=Depends(get_current_user)):
#     if user["Role"] != "Student":
#         log_action(f"UNAUTHORIZED: {user['Role']} {user['MemberID']} tried to apply scholarship")
#         raise HTTPException(status_code=403, detail="Only students can apply")

#     # Extract data with proper validation
#     student_id = data.get("student_id")
#     scholarship_id = data.get("scholarship_id")
    
#     # Validate required fields
#     if student_id is None or scholarship_id is None:
#         log_action(f"Missing required fields: student_id={student_id}, scholarship_id={scholarship_id}")
#         raise HTTPException(status_code=400, detail="Missing student_id or scholarship_id")
    
#     # Verify student ID matches the logged-in user
#     if int(student_id) != user["MemberID"]:
#         log_action(f"Student ID mismatch: {student_id} vs {user['MemberID']}")
#         raise HTTPException(status_code=403, detail="You can only apply for yourself")
    
#     log_action(f"{user['Role']} {user['MemberID']} started applying for scholarship {scholarship_id}")

#     db = get_db()
#     cursor = db.cursor()

#     # Check if already applied
#     cursor.execute("""
#         SELECT * FROM scholarship_application 
#         WHERE StudentID=%s AND ScholarshipID=%s
#     """, (student_id, scholarship_id))
    
#     existing = cursor.fetchone()
#     if existing:
#         log_action(f"Duplicate application attempt: Student {student_id} for Scholarship {scholarship_id}")
#         raise HTTPException(status_code=400, detail="You have already applied for this scholarship")

#     # Insert application
#     try:
#         cursor.execute("""
#             INSERT INTO scholarship_application
#             (StudentID, ScholarshipID, ApplicationDate, Status)
#             VALUES (%s, %s, CURDATE(), 'Pending')
#         """, (student_id, scholarship_id))
#         db.commit()
#     except Exception as e:
#         db.rollback()
#         log_action(f"Database error: {str(e)}")
#         raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

#     log_action(f"{user['Role']} {user['MemberID']} applied for scholarship {scholarship_id}")

#     return {"message": "Application submitted successfully"}


@router.post("/apply")
def apply_scholarship(data: dict, user=Depends(get_current_user)):

    if user["Role"] != "Student":
        log_action(f"UNAUTHORIZED: {user['Role']} {user['MemberID']} tried to apply scholarship")
        raise HTTPException(status_code=403, detail="Only students can apply")

    log_action(f"{user['Role']} {user['MemberID']} started applying for scholarship {data['scholarship_id']}")

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute("""
            INSERT INTO scholarship_application
            (StudentID, ScholarshipID, ApplicationDate, Status)
            VALUES (%s, %s, CURDATE(), 'Pending')
        """, (user["MemberID"], data["scholarship_id"]))

        db.commit()

        log_action(f"{user['Role']} {user['MemberID']} applied for scholarship {data['scholarship_id']}")
        return {"message": "Application submitted"}

    except mysql.connector.IntegrityError:
        # ✅ This handles duplicate insert due to UNIQUE constraint
        db.rollback()
        return JSONResponse(
            status_code=400,
            content={"error": "Already applied for this scholarship"}
        )

    except Exception as e:
        # ✅ Catch any unexpected errors (important for stability)
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"}
        )


# @router.post("/apply")
# def apply_scholarship(data: dict, user=Depends(get_current_user)):

#     if user["Role"] != "Student":
#         log_action(f"UNAUTHORIZED: {user['Role']} {user['MemberID']} tried to apply scholarship")
#         raise HTTPException(status_code=403, detail="Only students can apply")

#     log_action(f"{user['Role']} {user['MemberID']} started applying for scholarship {data['scholarship_id']}")

#     db = get_db()
#     cursor = db.cursor()

#     cursor.execute("""
#         INSERT INTO scholarship_application
#         (StudentID, ScholarshipID, ApplicationDate, Status)
#         VALUES (%s, %s, CURDATE(), 'Pending')
#     """, (data["student_id"], data["scholarship_id"]))

#     db.commit()

#     log_action(f"{user['Role']} {user['MemberID']} applied for scholarship {data['scholarship_id']}")

#     return {"message": "Application submitted"}


@router.put("/verify")
def verify_application(data: dict, user=Depends(get_current_user)):

    if user["Role"] != "Admin": 
        log_action(f"UNAUTHORIZED: {user['Role']} {user['MemberID']} tried to verify application")
        raise HTTPException(status_code=403, detail="Only admin can verify")
    
    log_action(f"{user['Role']} {user['MemberID']} started verifying application {data['application_id']}")

    db = get_db()
    cursor = db.cursor() 

    # Insert verification record
    cursor.execute("""
        INSERT INTO verification
        (ApplicationID, AdminID, VerificationDate, VerificationStatus, Remarks)
        VALUES (%s, %s, CURDATE(), %s, %s)
    """, (data["application_id"], user["MemberID"], data["status"], data["remarks"]))

    # Update application
    cursor.execute("""
        UPDATE scholarship_application
        SET Status=%s
        WHERE ApplicationID=%s
    """, (data["status"], data["application_id"]))

    db.commit()

    log_action(f"{user['Role']} {user['MemberID']} verified application {data['application_id']}")

    return {"message": "Verification done"}


@router.delete("/scholarship/{scholarship_id}")
def delete_scholarship(scholarship_id: int, user=Depends(get_current_user)):

    if user["Role"] != "Authority":
        log_action(f"UNAUTHORIZED: {user['Role']} {user['MemberID']} tried to delete scholarship")
        raise HTTPException(status_code=403, detail="Only authority can delete scholarship")

    log_action(f"{user['Role']} {user['MemberID']} started deleting scholarship {scholarship_id}")
    
    db = get_db()
    cursor = db.cursor()

    cursor.execute("DELETE FROM scholarship WHERE ScholarshipID=%s", (scholarship_id,))
    db.commit()

    log_action(f"{user['Role']} {user['MemberID']} deleted scholarship {scholarship_id}")

    return {"message": "Scholarship deleted"}


# from fastapi import APIRouter, HTTPException
# from app.db import get_db

# router = APIRouter()

# @router.get("/scholarships")
# def get_scholarships():
#     db = get_db()
#     cursor = db.cursor(dictionary=True)

#     cursor.execute("SELECT * FROM scholarship")
#     return cursor.fetchall()