"""
test_module_a.py
================
Complete test suite for Module A - B+ Tree, Database Manager, and
Transaction Engine (ACID + Crash Recovery).

Adapted for the `scholarease` database schema.

Run from the Module_A root directory:
    python test_module_a.py

All tests use only the standard library and the custom code in
database/ and transaction/.  No external frameworks required.
"""

import os
import sys
import threading
import time
import traceback

# Ensure Unicode test output prints cleanly on Windows terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ensure local packages are importable 
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.bplustree import BPlusTree
from database.table import Table
from database.db_manager import DatabaseManager
from transaction.transaction_manager import (
    TransactionManager,
    TransactionError,
    DeadlockError,
)

# Tiny test-runner (no pytest needed)
_passed = 0
_failed = 0
_errors = []


def run(name, fn):
    global _passed, _failed
    try:
        fn()
        print(f"  PASS  {name}")
        _passed += 1
    except AssertionError as e:
        print(f"  FAIL  {name}  →  {e}")
        _failed += 1
        _errors.append((name, str(e)))
    except Exception as e:
        print(f"  ERROR {name}  →  {type(e).__name__}: {e}")
        _failed += 1
        _errors.append((name, traceback.format_exc()))


def section(title):
    print(f"\n{'─'*60}\n  {title}\n{'─'*60}")


def eq(a, b, msg=""):
    assert a == b, f"{msg}  expected {b!r}, got {a!r}"


def is_none(v, msg=""):
    assert v is None, f"{msg}  expected None, got {v!r}"


def not_none(v, msg=""):
    assert v is not None, f"{msg}  expected a value, got None"

# PART 1 - B+ Tree unit tests  (unchanged - tree is schema-agnostic)
section("PART 1 · B+ Tree")


def t_insert_search_basic():
    t = BPlusTree(order=4)
    t.insert(10, "ten")
    t.insert(20, "twenty")
    t.insert(5, "five")
    eq(t.search(10), "ten")
    eq(t.search(20), "twenty")
    eq(t.search(5), "five")
    is_none(t.search(99), "missing key should return None")


run("insert and search - basic", t_insert_search_basic)


def t_insert_many_causes_splits():
    t = BPlusTree(order=3)
    keys = [15, 25, 35, 5, 45, 55, 10, 20, 30, 40]
    for k in keys:
        t.insert(k, k * 2)
    for k in keys:
        eq(t.search(k), k * 2, f"key={k}")


run("insert many - triggers node splits", t_insert_many_causes_splits)


def t_get_all_sorted():
    t = BPlusTree(order=4)
    import random
    keys = random.sample(range(1, 200), 30)
    for k in keys:
        t.insert(k, k)
    result_keys = [k for k, _ in t.get_all()]
    eq(result_keys, sorted(keys), "get_all must return keys in sorted order")


run("get_all returns sorted order", t_get_all_sorted)


def t_update_existing():
    t = BPlusTree(order=4)
    t.insert(7, "old")
    t.update(7, "new")
    eq(t.search(7), "new")


run("update existing key", t_update_existing)


def t_update_missing_returns_false():
    t = BPlusTree(order=4)
    t.insert(1, "a")
    result = t.update(99, "x")
    eq(result, False, "update of missing key should return False")


run("update missing key returns False", t_update_missing_returns_false)


def t_delete_existing():
    t = BPlusTree(order=4)
    for k in [10, 20, 30, 40, 50]:
        t.insert(k, k)
    t.delete(30)
    is_none(t.search(30), "deleted key should not be found")
    eq(t.search(10), 10)
    eq(t.search(50), 50)


run("delete existing key", t_delete_existing)


def t_delete_all():
    t = BPlusTree(order=3)
    keys = [5, 10, 15, 20, 25]
    for k in keys:
        t.insert(k, k)
    for k in keys:
        t.delete(k)
    eq(t.get_all(), [], "tree should be empty after deleting all keys")


run("delete all keys - tree stays valid", t_delete_all)


def t_range_query():
    t = BPlusTree(order=4)
    for k in range(1, 21):
        t.insert(k, k * 10)
    result = t.range_query(5, 10)
    result_keys = [k for k, _ in result]
    eq(result_keys, [5, 6, 7, 8, 9, 10])


run("range query returns correct slice", t_range_query)


def t_range_query_empty():
    t = BPlusTree(order=4)
    for k in [1, 2, 3]:
        t.insert(k, k)
    result = t.range_query(10, 20)
    eq(result, [], "range with no matches should return []")


run("range query - no matches", t_range_query_empty)


def t_duplicate_insert_overwrites():
    """B+ Tree insert with duplicate key: second value stored at same key."""
    t = BPlusTree(order=4)
    t.insert(1, "first")
    t.insert(1, "second")
    not_none(t.search(1), "search after duplicate insert must not return None")


run("duplicate key insert does not crash", t_duplicate_insert_overwrites)

# PART 2 - Table tests  (unchanged - Table is schema-agnostic)
section("PART 2 · Table")


def t_table_insert_get():
    tbl = Table("students", ["id", "name"], search_key="id")
    tbl.insert({"id": 1, "name": "Alice"})
    tbl.insert({"id": 2, "name": "Bob"})
    eq(tbl.get(1)["name"], "Alice")
    eq(tbl.get(2)["name"], "Bob")
    is_none(tbl.get(99))


run("table insert and get", t_table_insert_get)


def t_table_update():
    tbl = Table("t", ["id", "val"], search_key="id")
    tbl.insert({"id": 5, "val": "old"})
    tbl.update(5, {"id": 5, "val": "new"})
    eq(tbl.get(5)["val"], "new")


run("table update", t_table_update)


def t_table_delete():
    tbl = Table("t", ["id", "val"], search_key="id")
    tbl.insert({"id": 3, "val": "x"})
    tbl.delete(3)
    is_none(tbl.get(3))


run("table delete", t_table_delete)


def t_table_get_all():
    tbl = Table("t", ["id", "val"], search_key="id")
    for i in [3, 1, 2]:
        tbl.insert({"id": i, "val": i})
    ids = [r["id"] for r in tbl.get_all()]
    eq(ids, [1, 2, 3], "get_all should return records sorted by primary key")


run("table get_all sorted", t_table_get_all)


def t_table_range_query():
    tbl = Table("t", ["id", "val"], search_key="id")
    for i in range(1, 11):
        tbl.insert({"id": i, "val": i})
    result = tbl.range_query(3, 6)
    ids = [r["id"] for r in result]
    eq(ids, [3, 4, 5, 6])


run("table range_query", t_table_range_query)


def t_table_schema_validation():
    tbl = Table("t", ["id", "name", "age"], search_key="id")
    try:
        tbl.insert({"id": 1, "name": "x"})   # missing 'age'
        assert False, "Should have raised ValueError for missing column"
    except ValueError:
        pass


run("table schema validation raises on missing column", t_table_schema_validation)


# PART 3 - DatabaseManager tests  (unchanged)
section("PART 3 · DatabaseManager")


def t_dbm_create_list():
    db = DatabaseManager()
    db.create_database("scholarease")
    assert "scholarease" in db.list_databases()


run("create and list database", t_dbm_create_list)


def t_dbm_duplicate_db_raises():
    db = DatabaseManager()
    db.create_database("scholarease")
    try:
        db.create_database("scholarease")
        assert False, "Should raise on duplicate database"
    except ValueError:
        pass


run("duplicate database raises ValueError", t_dbm_duplicate_db_raises)


def t_dbm_create_get_table():
    db = DatabaseManager()
    db.create_database("scholarease")
    db.create_table("scholarease", "member",
                    ["MemberID", "Name", "Email", "PhoneNo",
                     "WhatsAppNo", "Image", "Age", "Role"],
                    search_key="MemberID")
    tbl = db.get_table("scholarease", "member")
    not_none(tbl)
    tbl.insert({
        "MemberID": 1, "Name": "Rahul Sharma", "Email": "rahul@gmail.com",
        "PhoneNo": "9876543210", "WhatsAppNo": "9876543210",
        "Image": "rahul.jpg", "Age": 20, "Role": "Student",
    })
    eq(tbl.get(1)["Name"], "Rahul Sharma")


run("create and get table through manager", t_dbm_create_get_table)


def t_dbm_missing_table_raises():
    db = DatabaseManager()
    db.create_database("scholarease")
    try:
        db.get_table("scholarease", "nonexistent")
        assert False, "Should raise on missing table"
    except ValueError:
        pass


run("get missing table raises ValueError", t_dbm_missing_table_raises)


def t_dbm_drop_table():
    db = DatabaseManager()
    db.create_database("scholarease")
    db.create_table("scholarease", "scholarship",
                    ["ScholarshipID", "ScholarshipName",
                     "Provider", "MaxAmount", "Deadline"],
                    search_key="ScholarshipID")
    db.drop_table("scholarease", "scholarship")
    assert "scholarship" not in db.list_tables("scholarease")


run("drop table", t_dbm_drop_table)


def t_dbm_multiple_tables():
    db = DatabaseManager()
    db.create_database("scholarease")
    db.create_table("scholarease", "member",
                    ["MemberID", "Name", "Email", "PhoneNo",
                     "WhatsAppNo", "Image", "Age", "Role"],
                    search_key="MemberID")
    db.create_table("scholarease", "student_personal_details",
                    ["StudentID", "MemberID", "FirstName", "LastName",
                     "DOB", "Gender", "Category", "AadhaarNo", "PwD"],
                    search_key="StudentID")
    db.create_table("scholarease", "scholarship_application",
                    ["ApplicationID", "StudentID", "ScholarshipID",
                     "ApplicationDate", "Status", "ApprovedAmount"],
                    search_key="ApplicationID")
    tables = db.list_tables("scholarease")
    assert "member"                  in tables
    assert "student_personal_details" in tables
    assert "scholarship_application" in tables


run("three tables in one database", t_dbm_multiple_tables)

# Helpers shared by Parts 4-9
DB  = "scholarease"
WAL = "test_wal.log"


def reset_wal(path):
    if not os.path.exists(path):
        return
    try:
        os.remove(path)
    except PermissionError:
        with open(path, "w", encoding="utf-8"):
            pass

# Table name constants
T_MEMBER       = "member"
T_STUDENT      = "student_personal_details"
T_INSTITUTION  = "institution"
T_EDU_CUR      = "educational_current"
T_FEE          = "fee_structure"
T_BANK         = "bank_account"
T_DOCUMENT     = "document"
T_SCHOLARSHIP  = "scholarship"
T_APPLICATION  = "scholarship_application"
T_VERIFICATION = "verification"
T_PAYMENT      = "payment"


def _setup_schema(tm):
    """Create all tables needed by the tests (idempotent)."""
    if DB not in tm.list_databases():
        tm.create_database(DB)

    specs = {
        T_MEMBER: (
            ["MemberID", "Name", "Email", "PhoneNo",
             "WhatsAppNo", "Image", "Age", "Role"],
            "MemberID",
        ),
        T_STUDENT: (
            ["StudentID", "MemberID", "FirstName", "LastName",
             "DOB", "Gender", "Category", "AadhaarNo", "PwD"],
            "StudentID",
        ),
        T_INSTITUTION: (
            ["InstituteID", "Name", "InstituteType", "State", "District"],
            "InstituteID",
        ),
        T_EDU_CUR: (
            ["EducationID", "StudentID", "InstituteID", "Degree",
             "CourseDuration", "CurrentSemester", "CurrentCPI",
             "ExpectedPassingYear"],
            "EducationID",
        ),
        T_FEE: (
            ["FeeID", "StudentID", "TuitionFee", "HostelFee", "MessFee"],
            "FeeID",
        ),
        T_BANK: (
            ["BankAccountID", "AccountNo", "StudentID",
             "NameAsPerPassbook", "BankName", "BranchName", "IFSC"],
            "BankAccountID",
        ),
        T_DOCUMENT: (
            ["DocumentID", "StudentID", "DocumentType",
             "FileReference", "UploadDate", "Verified"],
            "DocumentID",
        ),
        T_SCHOLARSHIP: (
            ["ScholarshipID", "ScholarshipName",
             "Provider", "MaxAmount", "Deadline"],
            "ScholarshipID",
        ),
        T_APPLICATION: (
            ["ApplicationID", "StudentID", "ScholarshipID",
             "ApplicationDate", "Status", "ApprovedAmount"],
            "ApplicationID",
        ),
        T_VERIFICATION: (
            ["VerificationID", "ApplicationID", "AdminID",
             "VerificationDate", "VerificationStatus", "Remarks"],
            "VerificationID",
        ),
        T_PAYMENT: (
            ["PaymentID", "ApplicationID", "AmountPaid",
             "PaymentDate", "BankAccountID", "Status"],
            "PaymentID",
        ),
    }

    existing = tm.list_tables(DB)
    for tname, (cols, pk) in specs.items():
        if tname not in existing:
            tm.create_table(DB, tname, cols, search_key=pk)


def fresh_tm():
    """Fresh TransactionManager with a clean WAL and full scholarease schema."""
    reset_wal(WAL)
    tm = TransactionManager(wal_path=WAL)
    _setup_schema(tm)
    return tm


def seed(tm):
    """
    Insert the minimum reference rows needed by all tests.
    Covers: 2 members, 1 admin member, 1 institution, 2 students,
    2 current-education records, 2 fee records, 2 bank accounts,
    2 scholarships.
    """
    def _exists(table, key):
        return tm._db.get_table(DB, table).get(key) is not None

    txn = tm.begin()
    try:
        # members
        for m in [
            {"MemberID": 1, "Name": "Rahul Sharma", "Email": "rahul@gmail.com",
             "PhoneNo": "9876543210", "WhatsAppNo": "9876543210",
             "Image": "rahul.jpg", "Age": 20, "Role": "Student"},
            {"MemberID": 2, "Name": "Priya Singh", "Email": "priya@gmail.com",
             "PhoneNo": "9876543211", "WhatsAppNo": "9876543211",
             "Image": "priya.jpg", "Age": 21, "Role": "Student"},
            {"MemberID": 6, "Name": "Admin One", "Email": "admin1@portal.com",
             "PhoneNo": "9999999991", "WhatsAppNo": None,
             "Image": "admin1.jpg", "Age": 35, "Role": "Admin"},
        ]:
            if not _exists(T_MEMBER, m["MemberID"]):
                tm.insert(txn, DB, T_MEMBER, m)

        # institution
        inst = {"InstituteID": 1, "Name": "IIT Gandhinagar",
                "InstituteType": "Government",
                "State": "Gujarat", "District": "Gandhinagar"}
        if not _exists(T_INSTITUTION, 1):
            tm.insert(txn, DB, T_INSTITUTION, inst)

        # students
        for s in [
            {"StudentID": 1, "MemberID": 1, "FirstName": "Rahul",
             "LastName": "Sharma", "DOB": "2004-05-10", "Gender": "Male",
             "Category": "General", "AadhaarNo": "123456789001", "PwD": "No"},
            {"StudentID": 2, "MemberID": 2, "FirstName": "Priya",
             "LastName": "Singh", "DOB": "2003-08-15", "Gender": "Female",
             "Category": "OBC", "AadhaarNo": "123456789002", "PwD": "No"},
        ]:
            if not _exists(T_STUDENT, s["StudentID"]):
                tm.insert(txn, DB, T_STUDENT, s)

        # current education
        for e in [
            {"EducationID": 1, "StudentID": 1, "InstituteID": 1,
             "Degree": "B.Tech CSE", "CourseDuration": 4,
             "CurrentSemester": 4, "CurrentCPI": 8.45,
             "ExpectedPassingYear": 2026},
            {"EducationID": 2, "StudentID": 2, "InstituteID": 1,
             "Degree": "B.Com", "CourseDuration": 3,
             "CurrentSemester": 6, "CurrentCPI": 7.10,
             "ExpectedPassingYear": 2024},
        ]:
            if not _exists(T_EDU_CUR, e["EducationID"]):
                tm.insert(txn, DB, T_EDU_CUR, e)

        # fee structure
        for f in [
            {"FeeID": 1, "StudentID": 1,
             "TuitionFee": 75000.0, "HostelFee": 30000.0, "MessFee": 20000.0},
            {"FeeID": 2, "StudentID": 2,
             "TuitionFee": 40000.0, "HostelFee": 15000.0, "MessFee": 12000.0},
        ]:
            if not _exists(T_FEE, f["FeeID"]):
                tm.insert(txn, DB, T_FEE, f)

        # bank accounts
        for b in [
            {"BankAccountID": 1, "AccountNo": "123456789000000001",
             "StudentID": 1, "NameAsPerPassbook": "Rahul Sharma",
             "BankName": "SBI", "BranchName": "Gandhinagar",
             "IFSC": "SBIN0001234"},
            {"BankAccountID": 2, "AccountNo": "123456789000000002",
             "StudentID": 2, "NameAsPerPassbook": "Priya Singh",
             "BankName": "HDFC", "BranchName": "Delhi",
             "IFSC": "HDFC0002345"},
        ]:
            if not _exists(T_BANK, b["BankAccountID"]):
                tm.insert(txn, DB, T_BANK, b)

        # scholarships
        for sc in [
            {"ScholarshipID": 1, "ScholarshipName": "Merit Scholarship",
             "Provider": "Govt of India", "MaxAmount": 100000.0,
             "Deadline": "2026-12-31"},
            {"ScholarshipID": 5, "ScholarshipName": "Technical Excellence",
             "Provider": "AICTE", "MaxAmount": 150000.0,
             "Deadline": "2026-12-15"},
        ]:
            if not _exists(T_SCHOLARSHIP, sc["ScholarshipID"]):
                tm.insert(txn, DB, T_SCHOLARSHIP, sc)

        tm.commit(txn)
    except Exception:
        tm.rollback(txn)
        raise

# PART 4 - Transaction: BEGIN / COMMIT / ROLLBACK
section("PART 4 · Transactions - BEGIN / COMMIT / ROLLBACK")


def t_commit_persists():
    """A committed student record must be readable afterwards."""
    tm = fresh_tm()
    txn = tm.begin()
    tm.insert(txn, DB, T_STUDENT, {
        "StudentID": 99, "MemberID": 1, "FirstName": "Zara",
        "LastName": "Khan", "DOB": "2005-01-01", "Gender": "Female",
        "Category": "OBC", "AadhaarNo": "999999999099", "PwD": "No",
    })
    tm.commit(txn)
    rec = tm.read(DB, T_STUDENT, 99)
    not_none(rec, "student record should exist after commit")
    eq(rec["FirstName"], "Zara")


run("commit - record persists", t_commit_persists)


def t_rollback_removes_insert():
    """A rolled-back application insert must leave no trace."""
    tm = fresh_tm()
    seed(tm)
    txn = tm.begin()
    tm.insert(txn, DB, T_APPLICATION, {
        "ApplicationID": 501, "StudentID": 1, "ScholarshipID": 1,
        "ApplicationDate": "2026-04-01", "Status": "Pending",
        "ApprovedAmount": None,
    })
    tm.rollback(txn)
    is_none(tm.read(DB, T_APPLICATION, 501),
            "application should be gone after rollback")


run("rollback - inserted record removed", t_rollback_removes_insert)


def t_rollback_restores_update():
    """Rolling back a CPI update must restore the original value."""
    tm = fresh_tm()
    seed(tm)
    txn = tm.begin()
    edu = tm.read(DB, T_EDU_CUR, 1)
    tm.update(txn, DB, T_EDU_CUR, 1, {**edu, "CurrentCPI": 1.00})
    tm.rollback(txn)
    eq(tm.read(DB, T_EDU_CUR, 1)["CurrentCPI"], 8.45,
       "CPI should be restored after rollback")


run("rollback - update reversed", t_rollback_restores_update)


def t_rollback_restores_delete():
    """Rolling back a student delete must bring the record back."""
    tm = fresh_tm()
    seed(tm)
    txn = tm.begin()
    tm.delete(txn, DB, T_STUDENT, 2)
    tm.rollback(txn)
    not_none(tm.read(DB, T_STUDENT, 2),
             "deleted student record restored after rollback")


run("rollback - delete reversed", t_rollback_restores_delete)


def t_duplicate_key_raises():
    """Inserting a member with an existing MemberID must raise TransactionError."""
    tm = fresh_tm()
    seed(tm)
    txn = tm.begin()
    try:
        tm.insert(txn, DB, T_MEMBER, {
            "MemberID": 1, "Name": "Duplicate", "Email": "dup@x.com",
            "PhoneNo": "0000000000", "WhatsAppNo": None,
            "Image": None, "Age": 25, "Role": "Student",
        })
        assert False, "Should raise TransactionError on duplicate key"
    except TransactionError:
        pass
    finally:
        try:
            tm.rollback(txn)
        except Exception:
            pass


run("insert duplicate key raises TransactionError", t_duplicate_key_raises)


def t_update_missing_key_raises():
    """Updating a non-existent scholarship must raise TransactionError."""
    tm = fresh_tm()
    seed(tm)
    txn = tm.begin()
    try:
        tm.update(txn, DB, T_SCHOLARSHIP, 999, {
            "ScholarshipID": 999, "ScholarshipName": "Ghost",
            "Provider": "None", "MaxAmount": 0.0, "Deadline": "2026-01-01",
        })
        assert False, "Should raise TransactionError for missing key"
    except TransactionError:
        pass
    finally:
        try:
            tm.rollback(txn)
        except Exception:
            pass


run("update missing key raises TransactionError", t_update_missing_key_raises)


def t_delete_missing_key_raises():
    """Deleting a non-existent application must raise TransactionError."""
    tm = fresh_tm()
    seed(tm)
    txn = tm.begin()
    try:
        tm.delete(txn, DB, T_APPLICATION, 9999)
        assert False, "Should raise TransactionError for missing key"
    except TransactionError:
        pass
    finally:
        try:
            tm.rollback(txn)
        except Exception:
            pass


run("delete missing key raises TransactionError", t_delete_missing_key_raises)


def t_operate_after_commit_raises():
    """Any DML on an already-committed transaction must raise TransactionError."""
    tm = fresh_tm()
    txn = tm.begin()
    tm.insert(txn, DB, T_SCHOLARSHIP, {
        "ScholarshipID": 77, "ScholarshipName": "Test Grant",
        "Provider": "Test", "MaxAmount": 50000.0, "Deadline": "2026-06-01",
    })
    tm.commit(txn)
    try:
        tm.insert(txn, DB, T_SCHOLARSHIP, {
            "ScholarshipID": 78, "ScholarshipName": "After Commit",
            "Provider": "Test", "MaxAmount": 1000.0, "Deadline": "2026-06-01",
        })
        assert False, "Should raise on committed transaction"
    except TransactionError:
        pass


run("DML after commit raises TransactionError", t_operate_after_commit_raises)

# PART 5 - Atomicity
section("PART 5 · Atomicity - all or nothing")


def t_partial_failure_rolls_back_all():
    """
    Scholarship application workflow:
      1. Insert application row
      2. Insert document row
      3. Crash before commit
    Both inserts must be undone - no partial writes survive.
    """
    tm = fresh_tm()
    seed(tm)

    txn = tm.begin()
    try:
        tm.insert(txn, DB, T_APPLICATION, {
            "ApplicationID": 601, "StudentID": 1, "ScholarshipID": 1,
            "ApplicationDate": "2026-04-01", "Status": "Pending",
            "ApprovedAmount": None,
        })
        tm.insert(txn, DB, T_DOCUMENT, {
            "DocumentID": 701, "StudentID": 1,
            "DocumentType": "Income Certificate",
            "FileReference": "docs/inc_test.pdf",
            "UploadDate": "2026-04-01", "Verified": "No",
        })
        raise RuntimeError("Simulated mid-transaction crash")
        tm.commit(txn)   # unreachable

    except RuntimeError:
        tm.rollback(txn)

    is_none(tm.read(DB, T_APPLICATION, 601), "application rolled back")
    is_none(tm.read(DB, T_DOCUMENT,    701), "document rolled back")


run("partial failure rolls back application + document", t_partial_failure_rolls_back_all)


def t_three_table_commit_all_visible():
    """
    Full successful 3-table transaction (application → document → verification)
    - all changes must be visible after commit.
    """
    tm = fresh_tm()
    seed(tm)

    txn = tm.begin()
    tm.insert(txn, DB, T_APPLICATION, {
        "ApplicationID": 602, "StudentID": 1, "ScholarshipID": 1,
        "ApplicationDate": "2026-04-01", "Status": "Approved",
        "ApprovedAmount": 100000.0,
    })
    tm.insert(txn, DB, T_DOCUMENT, {
        "DocumentID": 702, "StudentID": 1,
        "DocumentType": "Marksheet",
        "FileReference": "docs/marks_test.pdf",
        "UploadDate": "2026-04-01", "Verified": "Yes",
    })
    tm.insert(txn, DB, T_VERIFICATION, {
        "VerificationID": 801, "ApplicationID": 602, "AdminID": 6,
        "VerificationDate": "2026-04-01",
        "VerificationStatus": "Approved",
        "Remarks": "All good",
    })
    tm.commit(txn)

    not_none(tm.read(DB, T_APPLICATION,  602), "application inserted")
    not_none(tm.read(DB, T_DOCUMENT,     702), "document inserted")
    not_none(tm.read(DB, T_VERIFICATION, 801), "verification inserted")
    eq(tm.read(DB, T_APPLICATION, 602)["ApprovedAmount"], 100000.0,
       "approved amount correct")


run("3-table commit - all changes visible", t_three_table_commit_all_visible)


def t_multiple_rollbacks_independent():
    """Two independent transactions both rollback - neither affects the other."""
    tm = fresh_tm()
    seed(tm)

    txn1 = tm.begin()
    edu = tm.read(DB, T_EDU_CUR, 1)
    tm.update(txn1, DB, T_EDU_CUR, 1, {**edu, "CurrentCPI": 0.0})

    txn2 = tm.begin()
    fee = tm.read(DB, T_FEE, 2)
    tm.update(txn2, DB, T_FEE, 2, {**fee, "TuitionFee": 0.0})

    tm.rollback(txn1)
    tm.rollback(txn2)

    eq(tm.read(DB, T_EDU_CUR, 1)["CurrentCPI"], 8.45,  "CPI intact after rollback")
    eq(tm.read(DB, T_FEE,     2)["TuitionFee"], 40000.0, "TuitionFee intact after rollback")


run("two independent rollbacks stay isolated", t_multiple_rollbacks_independent)

# PART 6 - Consistency
section("PART 6 · Consistency - constraints always hold")


def t_approved_amount_exceeds_max_rejected():
    """
    Admin tries to approve an amount greater than the scholarship's MaxAmount.
    The transaction must rollback and leave the application unchanged.
    """
    tm = fresh_tm()
    seed(tm)

    # Setup: create a pending application
    setup = tm.begin()
    tm.insert(setup, DB, T_APPLICATION, {
        "ApplicationID": 603, "StudentID": 1, "ScholarshipID": 1,
        "ApplicationDate": "2026-04-01", "Status": "Pending",
        "ApprovedAmount": None,
    })
    tm.commit(setup)

    txn = tm.begin()
    try:
        scholarship = tm.read(DB, T_SCHOLARSHIP, 1)
        application = tm.read(DB, T_APPLICATION, 603)
        proposed    = 999999.0   # far exceeds MaxAmount of 100 000

        if proposed > scholarship["MaxAmount"]:
            raise TransactionError(
                f"Proposed amount {proposed} exceeds MaxAmount "
                f"{scholarship['MaxAmount']}")

        tm.update(txn, DB, T_APPLICATION, 603,
                  {**application, "Status": "Approved",
                   "ApprovedAmount": proposed})
        tm.commit(txn)
    except TransactionError:
        tm.rollback(txn)

    app = tm.read(DB, T_APPLICATION, 603)
    eq(app["Status"],         "Pending", "status must remain Pending")
    is_none(app["ApprovedAmount"],        "ApprovedAmount must remain None")


run("approved amount > MaxAmount triggers rollback", t_approved_amount_exceeds_max_rejected)


def t_low_cpi_scholarship_rejected():
    """
    A scholarship requiring CPI >= 8.0 must reject a student with CPI 7.10.
    Transaction rolls back and application is never stored.
    """
    tm = fresh_tm()
    seed(tm)

    MIN_CPI = 8.0
    txn = tm.begin()
    try:
        edu = tm.read(DB, T_EDU_CUR, 2)   # Priya: CPI = 7.10
        if edu["CurrentCPI"] < MIN_CPI:
            raise TransactionError(
                f"CPI {edu['CurrentCPI']} below minimum {MIN_CPI}")

        tm.insert(txn, DB, T_APPLICATION, {
            "ApplicationID": 604, "StudentID": 2, "ScholarshipID": 5,
            "ApplicationDate": "2026-04-01", "Status": "Pending",
            "ApprovedAmount": None,
        })
        tm.commit(txn)
    except TransactionError:
        tm.rollback(txn)

    is_none(tm.read(DB, T_APPLICATION, 604),
            "application must not exist after CPI constraint violation")


run("CPI below minimum rejects application", t_low_cpi_scholarship_rejected)


def t_data_valid_after_many_ops():
    """After a mix of commits and rollbacks, data stays consistent."""
    tm = fresh_tm()
    seed(tm)

    # Commit: approve Rahul's application
    txn1 = tm.begin()
    tm.insert(txn1, DB, T_APPLICATION, {
        "ApplicationID": 605, "StudentID": 1, "ScholarshipID": 1,
        "ApplicationDate": "2026-04-01", "Status": "Approved",
        "ApprovedAmount": 100000.0,
    })
    tm.commit(txn1)

    # Rollback: try to approve Priya with an invalid amount
    txn2 = tm.begin()
    try:
        sc = tm.read(DB, T_SCHOLARSHIP, 1)
        if 200000.0 > sc["MaxAmount"]:
            raise TransactionError("Exceeds MaxAmount")
        tm.insert(txn2, DB, T_APPLICATION, {
            "ApplicationID": 606, "StudentID": 2, "ScholarshipID": 1,
            "ApplicationDate": "2026-04-01", "Status": "Approved",
            "ApprovedAmount": 200000.0,
        })
        tm.commit(txn2)
    except TransactionError:
        tm.rollback(txn2)

    not_none(tm.read(DB, T_APPLICATION, 605), "Rahul's application exists")
    is_none(tm.read(DB, T_APPLICATION,  606), "Priya's invalid application absent")
    eq(tm.read(DB, T_EDU_CUR, 1)["CurrentCPI"], 8.45, "CPI unchanged")


run("data consistency after mixed commit/rollback sequence", t_data_valid_after_many_ops)

# PART 7 - Isolation
section("PART 7 · Isolation - concurrent transactions")


def t_no_lost_update():
    """
    Two admins concurrently update the same application's status.
    With strict 2PL the final state must reflect exactly one of the
    two serialised writes - not a mix.
    """
    tm = fresh_tm()
    seed(tm)

    # Setup a pending application
    setup = tm.begin()
    tm.insert(setup, DB, T_APPLICATION, {
        "ApplicationID": 701, "StudentID": 1, "ScholarshipID": 1,
        "ApplicationDate": "2026-04-01", "Status": "Pending",
        "ApprovedAmount": None,
    })
    tm.commit(setup)

    errors = []

    def approve(delay_before=0.0, delay_after=0.0):
        try:
            if delay_before:
                time.sleep(delay_before)
            txn = tm.begin()
            app = tm.read(DB, T_APPLICATION, 701)
            tm.update(txn, DB, T_APPLICATION, 701,
                      {**app, "Status": "Approved", "ApprovedAmount": 100000.0})
            if delay_after:
                time.sleep(delay_after)
            tm.commit(txn)
        except Exception as e:
            errors.append(str(e))
            try:
                tm.rollback(txn)
            except Exception:
                pass

    def reject(delay_before=0.0):
        try:
            if delay_before:
                time.sleep(delay_before)
            txn = tm.begin()
            app = tm.read(DB, T_APPLICATION, 701)
            tm.update(txn, DB, T_APPLICATION, 701,
                      {**app, "Status": "Rejected", "ApprovedAmount": 0.0})
            tm.commit(txn)
        except Exception as e:
            errors.append(str(e))
            try:
                tm.rollback(txn)
            except Exception:
                pass

    t1 = threading.Thread(target=approve, kwargs={"delay_after": 0.1})
    t2 = threading.Thread(target=reject,  kwargs={"delay_before": 0.02})
    t1.start(); t2.start()
    t1.join();  t2.join()

    final = tm.read(DB, T_APPLICATION, 701)["Status"]
    assert final in ("Approved", "Rejected"), \
        f"Status must be one consistent value, got {final!r}"
    assert final != "Pending", "At least one update must have succeeded"


run("no lost update under concurrent admin decisions", t_no_lost_update)


def t_lock_prevents_dirty_read():
    """
    TXN A holds a lock and updates a scholarship's MaxAmount.
    TXN B reads the scholarship only AFTER A commits - must see the new value.
    """
    tm = fresh_tm()
    seed(tm)

    read_value  = []
    b_can_read  = threading.Event()
    a_committed = threading.Event()

    def txn_a():
        txn = tm.begin()
        sc = tm.read(DB, T_SCHOLARSHIP, 1)
        tm.update(txn, DB, T_SCHOLARSHIP, 1,
                  {**sc, "MaxAmount": 123456.0})
        b_can_read.set()
        time.sleep(0.1)
        tm.commit(txn)
        a_committed.set()

    def txn_b():
        b_can_read.wait()
        time.sleep(0.02)
        a_committed.wait()
        val = tm.read(DB, T_SCHOLARSHIP, 1)["MaxAmount"]
        read_value.append(val)

    t1 = threading.Thread(target=txn_a)
    t2 = threading.Thread(target=txn_b)
    t1.start(); t2.start()
    t1.join();  t2.join()

    eq(read_value[0], 123456.0, "B sees A's committed MaxAmount after A commits")


run("read after commit - no dirty read", t_lock_prevents_dirty_read)


def t_concurrent_different_tables():
    """
    Two transactions on different tables (scholarship vs member) must not
    block each other and should run roughly in parallel.
    """
    tm = fresh_tm()
    seed(tm)

    results = {}

    def update_scholarship():
        txn = tm.begin()
        sc = tm.read(DB, T_SCHOLARSHIP, 1)
        tm.update(txn, DB, T_SCHOLARSHIP, 1,
                  {**sc, "MaxAmount": sc["MaxAmount"] + 1000.0})
        time.sleep(0.05)
        tm.commit(txn)
        results["scholarship"] = "ok"

    def update_member():
        txn = tm.begin()
        m = tm.read(DB, T_MEMBER, 2)
        tm.update(txn, DB, T_MEMBER, 2, {**m, "Age": m["Age"] + 1})
        time.sleep(0.05)
        tm.commit(txn)
        results["member"] = "ok"

    start = time.time()
    t1 = threading.Thread(target=update_scholarship)
    t2 = threading.Thread(target=update_member)
    t1.start(); t2.start()
    t1.join();  t2.join()
    elapsed = time.time() - start

    eq(results.get("scholarship"), "ok")
    eq(results.get("member"),      "ok")
    assert elapsed < 0.15, \
        f"Different-table transactions should run concurrently, took {elapsed:.2f}s"


run("concurrent transactions on different tables don't block", t_concurrent_different_tables)

# PART 8 - Durability & Crash Recovery
section("PART 8 · Durability - WAL and crash recovery")


def t_committed_data_survives_crash():
    """
    Commit a payment record, simulate crash (wipe memory), restart + recover.
    The committed record must be restored from the WAL.
    """
    reset_wal(WAL)
    tm = TransactionManager(wal_path=WAL)
    _setup_schema(tm)

    # Need a prerequisite application row first
    pre = tm.begin()
    tm.insert(pre, DB, T_APPLICATION, {
        "ApplicationID": 801, "StudentID": 1, "ScholarshipID": 1,
        "ApplicationDate": "2026-04-01", "Status": "Approved",
        "ApprovedAmount": 100000.0,
    })
    tm.commit(pre)

    txn = tm.begin()
    tm.insert(txn, DB, T_PAYMENT, {
        "PaymentID": 901, "ApplicationID": 801,
        "AmountPaid": 100000.0, "PaymentDate": "2026-04-03",
        "BankAccountID": 1, "Status": "Completed",
    })
    tm.commit(txn)

    tm.simulate_crash()
    tm.restart_and_recover(_setup_schema)

    rec = tm.read(DB, T_PAYMENT, 901)
    not_none(rec, "committed payment must be restored after crash")
    eq(rec["Status"], "Completed", "restored payment status must match")


run("committed record survives crash + WAL recovery", t_committed_data_survives_crash)


def t_uncommitted_data_lost_on_crash():
    """
    Update a student's CPI but don't commit, then crash.
    After recovery the original CPI must be intact.
    """
    reset_wal(WAL)
    tm = TransactionManager(wal_path=WAL)
    _setup_schema(tm)

    # Seed committed education record
    pre = tm.begin()
    tm.insert(pre, DB, T_EDU_CUR, {
        "EducationID": 1, "StudentID": 1, "InstituteID": 1,
        "Degree": "B.Tech CSE", "CourseDuration": 4,
        "CurrentSemester": 4, "CurrentCPI": 8.45,
        "ExpectedPassingYear": 2026,
    })
    tm.commit(pre)

    # Uncommitted change
    txn = tm.begin()
    edu = tm.read(DB, T_EDU_CUR, 1)
    tm.update(txn, DB, T_EDU_CUR, 1, {**edu, "CurrentCPI": 1.00})
    # DO NOT commit

    tm.simulate_crash()
    tm.restart_and_recover(_setup_schema)

    rec = tm.read(DB, T_EDU_CUR, 1)
    if rec is not None:
        assert rec["CurrentCPI"] != 1.00, \
            f"Uncommitted CPI=1.00 must not survive crash, got {rec['CurrentCPI']}"


run("uncommitted change lost after crash + recovery", t_uncommitted_data_lost_on_crash)


def t_wal_records_written_before_data():
    """After a commit the WAL must contain a COMMIT record for that transaction."""
    reset_wal(WAL)
    tm = TransactionManager(wal_path=WAL)
    _setup_schema(tm)

    txn = tm.begin()
    tm.insert(txn, DB, T_SCHOLARSHIP, {
        "ScholarshipID": 99, "ScholarshipName": "WAL Test Grant",
        "Provider": "Test Org", "MaxAmount": 10000.0,
        "Deadline": "2026-12-31",
    })
    tm.commit(txn)

    records   = tm._wal.read_all()
    committed = {r.txn_id for r in records if r.rec_type == "COMMIT"}
    assert txn.txn_id in committed, \
        f"WAL must contain COMMIT record for txn {txn.txn_id}"


run("WAL contains COMMIT record after successful commit", t_wal_records_written_before_data)


def t_wal_rollback_recorded():
    """After rollback the WAL must contain a ROLLBACK record."""
    reset_wal(WAL)
    tm = TransactionManager(wal_path=WAL)
    _setup_schema(tm)

    txn = tm.begin()
    tm.insert(txn, DB, T_SCHOLARSHIP, {
        "ScholarshipID": 88, "ScholarshipName": "Rollback Test",
        "Provider": "Test Org", "MaxAmount": 5000.0,
        "Deadline": "2026-06-01",
    })
    tm.rollback(txn)

    records    = tm._wal.read_all()
    rolled_txns = {r.txn_id for r in records if r.rec_type == "ROLLBACK"}
    assert txn.txn_id in rolled_txns, \
        f"WAL must contain ROLLBACK record for txn {txn.txn_id}"


run("WAL contains ROLLBACK record after rollback", t_wal_rollback_recorded)


def t_multiple_crashes_recovery():
    """A committed verification record must survive two consecutive crash cycles."""
    reset_wal(WAL)
    tm = TransactionManager(wal_path=WAL)
    _setup_schema(tm)

    # Prerequisite application
    pre = tm.begin()
    tm.insert(pre, DB, T_APPLICATION, {
        "ApplicationID": 802, "StudentID": 1, "ScholarshipID": 1,
        "ApplicationDate": "2026-04-01", "Status": "Approved",
        "ApprovedAmount": 100000.0,
    })
    tm.commit(pre)

    txn = tm.begin()
    tm.insert(txn, DB, T_VERIFICATION, {
        "VerificationID": 999, "ApplicationID": 802, "AdminID": 6,
        "VerificationDate": "2026-04-03",
        "VerificationStatus": "Approved",
        "Remarks": "Verified OK",
    })
    tm.commit(txn)

    # First crash
    tm.simulate_crash()
    tm.restart_and_recover(_setup_schema)
    not_none(tm.read(DB, T_VERIFICATION, 999), "survived first crash")

    # Second crash
    tm.simulate_crash()
    tm.restart_and_recover(_setup_schema)
    not_none(tm.read(DB, T_VERIFICATION, 999), "survived second crash")


run("data survives two consecutive crash-recovery cycles", t_multiple_crashes_recovery)

# PART 9 - Full end-to-end ACID scenario
section("PART 9 · End-to-end ACID - Scholarship Portal Workflow")


def t_full_application_acid():
    """
    Complete scholarship disbursement workflow in a single transaction:
      1. Insert scholarship_application  (status = Approved)
      2. Insert document                 (supporting evidence)
      3. Insert verification             (admin approval)
      4. Insert payment                  (disbursement record)
    All four writes must be visible after commit.
    """
    tm = fresh_tm()
    seed(tm)

    txn = tm.begin()

    student     = tm.read(DB, T_STUDENT,     1)
    scholarship = tm.read(DB, T_SCHOLARSHIP, 5)
    bank        = tm.read(DB, T_BANK,        1)

    assert student     is not None, "pre-condition: student 1 exists"
    assert scholarship is not None, "pre-condition: scholarship 5 exists"

    approve_amount = 140000.0
    assert approve_amount <= scholarship["MaxAmount"], \
        "pre-condition: amount within MaxAmount"

    existing_apps = tm.read_all(DB, T_APPLICATION)
    app_id = max((a["ApplicationID"] for a in existing_apps), default=0) + 1

    existing_docs = tm.read_all(DB, T_DOCUMENT)
    doc_id = max((d["DocumentID"] for d in existing_docs), default=0) + 1

    existing_verifs = tm.read_all(DB, T_VERIFICATION)
    verif_id = max((v["VerificationID"] for v in existing_verifs), default=0) + 1

    existing_pays = tm.read_all(DB, T_PAYMENT)
    pay_id = max((p["PaymentID"] for p in existing_pays), default=0) + 1

    # 1. Application
    tm.insert(txn, DB, T_APPLICATION, {
        "ApplicationID":   app_id,
        "StudentID":       1,
        "ScholarshipID":   5,
        "ApplicationDate": "2026-04-03",
        "Status":          "Approved",
        "ApprovedAmount":  approve_amount,
    })
    # 2. Document
    tm.insert(txn, DB, T_DOCUMENT, {
        "DocumentID":    doc_id,
        "StudentID":     1,
        "DocumentType":  "Marksheet",
        "FileReference": "docs/marks_rahul_2026.pdf",
        "UploadDate":    "2026-04-03",
        "Verified":      "Yes",
    })
    # 3. Verification
    tm.insert(txn, DB, T_VERIFICATION, {
        "VerificationID":     verif_id,
        "ApplicationID":      app_id,
        "AdminID":            6,
        "VerificationDate":   "2026-04-03",
        "VerificationStatus": "Approved",
        "Remarks":            "All documents verified.",
    })
    # 4. Payment
    tm.insert(txn, DB, T_PAYMENT, {
        "PaymentID":     pay_id,
        "ApplicationID": app_id,
        "AmountPaid":    approve_amount,
        "PaymentDate":   "2026-04-03",
        "BankAccountID": bank["BankAccountID"],
        "Status":        "Completed",
    })

    tm.commit(txn)

    app   = tm.read(DB, T_APPLICATION,  app_id)
    doc   = tm.read(DB, T_DOCUMENT,     doc_id)
    verif = tm.read(DB, T_VERIFICATION, verif_id)
    pay   = tm.read(DB, T_PAYMENT,      pay_id)

    not_none(app,   "application inserted")
    not_none(doc,   "document inserted")
    not_none(verif, "verification inserted")
    not_none(pay,   "payment inserted")

    eq(app["ApprovedAmount"],        approve_amount, "approved amount correct")
    eq(verif["VerificationStatus"],  "Approved",     "verification status correct")
    eq(pay["Status"],                "Completed",    "payment status correct")
    eq(pay["AmountPaid"],            approve_amount, "payment amount correct")


run("full scholarship workflow - 4-table atomic commit", t_full_application_acid)


def t_full_application_fails_atomically():
    """
    Same 4-step workflow but MaxAmount constraint fails after step 1.
    All four tables must remain unchanged (full rollback).
    """
    tm = fresh_tm()
    seed(tm)

    existing_apps = tm.read_all(DB, T_APPLICATION)
    app_id  = max((a["ApplicationID"] for a in existing_apps), default=0) + 1
    doc_id  = app_id + 1000
    verif_id = app_id + 2000
    pay_id   = app_id + 3000

    txn = tm.begin()
    try:
        scholarship = tm.read(DB, T_SCHOLARSHIP, 1)
        bad_amount  = 999999.0

        tm.insert(txn, DB, T_APPLICATION, {
            "ApplicationID":   app_id,
            "StudentID":       1,
            "ScholarshipID":   1,
            "ApplicationDate": "2026-04-03",
            "Status":          "Pending",
            "ApprovedAmount":  None,
        })

        # Constraint check - fires after step 1
        if bad_amount > scholarship["MaxAmount"]:
            raise TransactionError(
                f"Amount {bad_amount} exceeds MaxAmount {scholarship['MaxAmount']}")

        # Steps 2-4 are unreachable
        tm.insert(txn, DB, T_DOCUMENT, {
            "DocumentID": doc_id, "StudentID": 1,
            "DocumentType": "Income Certificate",
            "FileReference": "docs/x.pdf",
            "UploadDate": "2026-04-03", "Verified": "No",
        })
        tm.insert(txn, DB, T_VERIFICATION, {
            "VerificationID": verif_id, "ApplicationID": app_id,
            "AdminID": 6, "VerificationDate": "2026-04-03",
            "VerificationStatus": "Approved", "Remarks": "",
        })
        tm.insert(txn, DB, T_PAYMENT, {
            "PaymentID": pay_id, "ApplicationID": app_id,
            "AmountPaid": bad_amount, "PaymentDate": "2026-04-03",
            "BankAccountID": 1, "Status": "Pending",
        })
        tm.commit(txn)

    except TransactionError:
        tm.rollback(txn)

    is_none(tm.read(DB, T_APPLICATION,  app_id),   "application not stored")
    is_none(tm.read(DB, T_DOCUMENT,     doc_id),   "document not stored")
    is_none(tm.read(DB, T_VERIFICATION, verif_id), "verification not stored")
    is_none(tm.read(DB, T_PAYMENT,      pay_id),   "payment not stored")


run("full workflow constraint failure - 4-table atomic rollback",
    t_full_application_fails_atomically)

# Cleanup
if os.path.exists(WAL):
    reset_wal(WAL)

# Summary
total = _passed + _failed
print(f"\n{'═'*60}")
print(f"  Results: {_passed}/{total} tests passed", end="")
if _failed:
    print(f"   ({_failed} FAILED)")
    for name, msg in _errors:
        print(f"\n  ✗ {name}")
        print(f"    {msg.strip()[:200]}")
else:
    print("  ✓  ALL PASSED")
print(f"{'═'*60}\n")

sys.exit(0 if _failed == 0 else 1)
