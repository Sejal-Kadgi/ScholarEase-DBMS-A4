"""
Module B — test_system.py
=========================
Corrected version of the ACID engine-level tests.

Fixes applied:
  1. test_with_transactions / test_concurrency:
       tm.read(...) inside worker threads now passes txn=txn so the
       LockManager actually acquires a lock on the read, making the
       isolation test valid.
  2. test_atomicity:
       Inserts a complete member record (all 8 required columns) and
       raises RuntimeError so the rollback is exercised through the
       correct code path.
  3. test_recovery:
       Payment record now includes all 6 required columns so the WAL
       stores and replays the full record correctly.

Run from project root:
    python Module_B/test_system.py
"""

import os
import sys
import threading
import time

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, root_dir)

from Module_A.transaction.transaction_manager import TransactionManager, DeadlockError

DB = "scholarease"


def setup_schema(tm):
    if DB not in tm.list_databases():
        tm.create_database(DB)

    tm.create_table(DB, "member",
                    ["MemberID", "Name", "Email", "PhoneNo",
                     "WhatsAppNo", "Image", "Age", "Role"],
                    search_key="MemberID")

    tm.create_table(DB, "scholarship_application",
                    ["ApplicationID", "StudentID", "ScholarshipID",
                     "ApplicationDate", "Status", "ApprovedAmount"],
                    search_key="ApplicationID")

    tm.create_table(DB, "document",
                    ["DocumentID", "StudentID", "DocumentType",
                     "FileReference", "UploadDate", "Verified"],
                    search_key="DocumentID")

    tm.create_table(DB, "verification",
                    ["VerificationID", "ApplicationID", "AdminID",
                     "VerificationDate", "VerificationStatus", "Remarks"],
                    search_key="VerificationID")

    tm.create_table(DB, "payment",
                    ["PaymentID", "ApplicationID", "AmountPaid",
                     "PaymentDate", "BankAccountID", "Status"],
                    search_key="PaymentID")

    tm.create_table(DB, "bank_account",
                    ["BankAccountID", "AccountNo", "StudentID",
                     "NameAsPerPassbook", "BankName", "BranchName", "IFSC"],
                    search_key="BankAccountID")

    txn = tm.begin()
    try:
        if tm.read(DB, "member", 1) is None:
            tm.insert(txn, DB, "member", {
                "MemberID": 1, "Name": "Rahul", "Email": "rahul@gmail.com",
                "PhoneNo": "9876543210", "WhatsAppNo": "9876543210",
                "Image": "rahul.jpg", "Age": 20, "Role": "Student"
            })
        if tm.read(DB, "bank_account", 1) is None:
            tm.insert(txn, DB, "bank_account", {
                "BankAccountID": 1, "AccountNo": "123456789000000001",
                "StudentID": 1, "NameAsPerPassbook": "Rahul",
                "BankName": "SBI", "BranchName": "Gandhinagar",
                "IFSC": "SBIN0001234"
            })
        tm.commit(txn)
    except Exception:
        tm.rollback(txn)


# ─── TEST 0: Baseline — show what happens WITHOUT transaction control ───────

def test_without_control():
    print("\nTEST 0: WITHOUT CONTROL (RACE CONDITION — expected FAIL)")
    balance = 100

    def worker():
        nonlocal balance
        temp = balance       # all threads read same stale value
        time.sleep(0.01)
        balance = temp - 10  # all threads write same wrong result

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()

    print(f"  EXPECTED : 50")
    print(f"  ACTUAL   : {balance}")
    print(f"  RESULT   : {'FAIL (as expected — proves the problem)' if balance != 50 else 'UNEXPECTED PASS'}")


# ─── TEST 1: WITH transaction control — isolates concurrent reads ────────────

def test_with_transactions(tm):
    print("\nTEST 1: WITH TRANSACTION CONTROL (Isolation via 2PL)")

    tm.create_table(DB, "counter", ["ID", "Value"], search_key="ID")

    txn = tm.begin()
    try:
        if tm.read(DB, "counter", 1) is None:
            tm.insert(txn, DB, "counter", {"ID": 1, "Value": 100})
        tm.commit(txn)
    except Exception:
        tm.rollback(txn)

    def worker():
        txn = tm.begin()
        try:
            # FIX: pass txn so LockManager acquires lock on this read
            row = tm.read(DB, "counter", 1, txn=txn)
            val = row["Value"]
            time.sleep(0.01)   # hold lock — forces serialisation
            tm.update(txn, DB, "counter", 1, {"ID": 1, "Value": val - 10})
            tm.commit(txn)
        except Exception:
            tm.rollback(txn)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()

    final = tm.read(DB, "counter", 1)["Value"]
    print(f"  EXPECTED : 50")
    print(f"  ACTUAL   : {final}")
    print(f"  RESULT   : {'PASS' if final == 50 else 'FAIL'}")


# ─── TEST 2: ATOMICITY ───────────────────────────────────────────────────────

def test_atomicity(tm):
    print("\nTEST 2: ATOMICITY (rolled-back insert leaves no trace)")

    txn = tm.begin()
    try:
        # FIX: insert complete record with all 8 required columns
        tm.insert(txn, DB, "member", {
            "MemberID": 10, "Name": "Charlie", "Email": "charlie@test.com",
            "PhoneNo": "9000000009", "WhatsAppNo": None,
            "Image": None, "Age": 22, "Role": "Student"
        })
        # Simulate crash / error before commit
        raise RuntimeError("Simulated mid-transaction failure")
    except RuntimeError:
        tm.rollback(txn)

    res = tm.read(DB, "member", 10)
    print(f"  RESULT   : {'PASS — member 10 not found (correctly rolled back)' if res is None else 'FAIL — member 10 found (not rolled back)'}")


# ─── TEST 3: CONCURRENCY ISOLATION (Lost Update prevention) ─────────────────

def test_concurrency(tm):
    print("\nTEST 3: CONCURRENCY ISOLATION (Lost Update — 5 threads increment Age)")

    # Ensure starting Age is known
    existing = tm.read(DB, "member", 1)
    if existing:
        reset_txn = tm.begin()
        tm.update(reset_txn, DB, "member", 1, {**existing, "Age": 20})
        tm.commit(reset_txn)

    def worker():
        txn = tm.begin()
        try:
            # FIX: pass txn so the read acquires the lock
            user = tm.read(DB, "member", 1, txn=txn)
            tm.update(txn, DB, "member", 1, {**user, "Age": user["Age"] + 1})
            tm.commit(txn)
        except Exception:
            tm.rollback(txn)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()

    final = tm.read(DB, "member", 1)["Age"]
    print(f"  EXPECTED : 25")
    print(f"  ACTUAL   : {final}")
    print(f"  RESULT   : {'PASS' if final == 25 else 'FAIL'}")


# ─── TEST 4: DEADLOCK DETECTION ─────────────────────────────────────────────

def test_deadlock(tm):
    print("\nTEST 4: DEADLOCK HANDLING (timeout-based detection)")

    results = []

    def t1():
        txn = tm.begin()
        try:
            tm.update(txn, DB, "member", 1, tm.read(DB, "member", 1))
            time.sleep(1)   # hold member lock; t2 needs it
            tm.update(txn, DB, "bank_account", 1, tm.read(DB, "bank_account", 1))
            tm.commit(txn)
            results.append(True)
        except DeadlockError:
            tm.rollback(txn)
            results.append(False)

    def t2():
        txn = tm.begin()
        try:
            tm.update(txn, DB, "bank_account", 1, tm.read(DB, "bank_account", 1))
            time.sleep(1)   # hold bank_account lock; t1 needs it
            tm.update(txn, DB, "member", 1, tm.read(DB, "member", 1))
            tm.commit(txn)
            results.append(True)
        except DeadlockError:
            tm.rollback(txn)
            results.append(False)

    a = threading.Thread(target=t1)
    b = threading.Thread(target=t2)
    a.start(); b.start()
    a.join(); b.join()

    one_rolled_back = not all(results)
    print(f"  At least one txn rolled back: {one_rolled_back}")
    print(f"  RESULT   : {'PASS — deadlock detected and resolved' if one_rolled_back else 'FAIL — no deadlock resolution'}")


# ─── TEST 5: DURABILITY (committed data survives crash + WAL recovery) ───────

def test_recovery(tm):
    print("\nTEST 5: DURABILITY (WAL crash recovery)")

    txn = tm.begin()
    try:
        # FIX: insert with all 6 required columns so WAL stores full record
        tm.insert(txn, DB, "payment", {
            "PaymentID": 555, "ApplicationID": 1,
            "AmountPaid": 100000.0, "PaymentDate": "2026-04-03",
            "BankAccountID": 1, "Status": "Completed"
        })
        tm.commit(txn)
    except Exception:
        tm.rollback(txn)

    # Simulate crash — wipes all in-memory state
    tm.simulate_crash()

    # Restart and recover from WAL
    tm.restart_and_recover(setup_schema)

    res = tm.read(DB, "payment", 555)
    print(f"  RESULT   : {'PASS — payment 555 restored from WAL' if res and res.get('Status') == 'Completed' else 'FAIL — payment 555 not found after recovery'}")


# ─── TEST 6: FULL ACID — 4-table atomic commit ───────────────────────────────

def test_acid(tm):
    print("\nTEST 6: FULL ACID — 4-table atomic commit (application + doc + verification + payment)")

    txn = tm.begin()
    try:
        tm.insert(txn, DB, "scholarship_application", {
            "ApplicationID": 500, "StudentID": 1,
            "ScholarshipID": 1, "ApplicationDate": "2026-04-03",
            "Status": "Approved", "ApprovedAmount": 100000.0
        })
        tm.insert(txn, DB, "document", {
            "DocumentID": 600, "StudentID": 1,
            "DocumentType": "Marksheet",
            "FileReference": "docs/marks_1.pdf",
            "UploadDate": "2026-04-03", "Verified": "Yes"
        })
        tm.insert(txn, DB, "verification", {
            "VerificationID": 700, "ApplicationID": 500,
            "AdminID": 6, "VerificationDate": "2026-04-03",
            "VerificationStatus": "Approved",
            "Remarks": "All documents verified"
        })
        tm.insert(txn, DB, "payment", {
            "PaymentID": 800, "ApplicationID": 500,
            "AmountPaid": 100000.0, "PaymentDate": "2026-04-03",
            "BankAccountID": 1, "Status": "Completed"
        })
        tm.commit(txn)

        # Verify all 4 rows landed
        app   = tm.read(DB, "scholarship_application", 500)
        doc   = tm.read(DB, "document", 600)
        verif = tm.read(DB, "verification", 700)
        pay   = tm.read(DB, "payment", 800)

        all_present = all([app, doc, verif, pay])
        print(f"  Application : {'found' if app else 'MISSING'}")
        print(f"  Document    : {'found' if doc else 'MISSING'}")
        print(f"  Verification: {'found' if verif else 'MISSING'}")
        print(f"  Payment     : {'found' if pay else 'MISSING'}")
        print(f"  RESULT      : {'PASS' if all_present else 'FAIL'}")

    except Exception as e:
        tm.rollback(txn)
        print(f"  RESULT   : FAIL — exception: {e}")


def main():
    tm = TransactionManager()
    setup_schema(tm)

    test_without_control()
    test_with_transactions(tm)
    test_atomicity(tm)
    test_concurrency(tm)
    test_deadlock(tm)
    test_recovery(tm)
    test_acid(tm)

    print("\n" + "=" * 50)
    print("  ALL TESTS COMPLETE")
    print("=" * 50)


if __name__ == "__main__":
    main()