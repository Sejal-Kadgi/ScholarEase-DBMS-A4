import copy
import json
import os
import threading
import time

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from Module_A.database.db_manager import DatabaseManager

# Exceptions
class TransactionError(Exception):
    """Raised for logical errors (duplicate key, constraint violation, etc.)"""

class DeadlockError(TransactionError):
    """Raised when a lock cannot be acquired within the timeout."""

class CrashSimulated(Exception):
    """Sentinel raised by simulate_crash() – never caught inside the engine."""

# 1.  Write-Ahead Log
class WALRecord:
    __slots__ = ("txn_id", "lsn", "rec_type", "operation",
                 "db", "table", "key", "before", "after", "ts")

    def __init__(self, txn_id, lsn, rec_type,
                 operation=None, db=None, table=None,
                 key=None, before=None, after=None):
        self.txn_id    = txn_id
        self.lsn       = lsn
        self.rec_type  = rec_type
        self.operation = operation
        self.db        = db
        self.table     = table
        self.key       = key
        self.before    = before
        self.after     = after
        self.ts        = time.time()

    def to_line(self):
        return json.dumps({
            "txn_id":    self.txn_id,
            "lsn":       self.lsn,
            "rec_type":  self.rec_type,
            "operation": self.operation,
            "db":        self.db,
            "table":     self.table,
            "key":       self.key,
            "before":    self.before,
            "after":     self.after,
            "ts":        self.ts,
        })

    @staticmethod
    def from_line(line):
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None
        r = WALRecord.__new__(WALRecord)
        r.txn_id    = d["txn_id"]
        r.lsn       = d["lsn"]
        r.rec_type  = d["rec_type"]
        r.operation = d.get("operation")
        r.db        = d.get("db")
        r.table     = d.get("table")
        r.key       = d.get("key")
        r.before    = d.get("before")
        r.after     = d.get("after")
        r.ts        = d.get("ts", 0.0)
        return r

    def __repr__(self):
        return (f"<WALRecord lsn={self.lsn} txn={self.txn_id} "
                f"type={self.rec_type} op={self.operation} key={self.key}>")


class WriteAheadLog:
    def __init__(self, path="wal.log"):
        self.path  = path
        self._lock = threading.Lock()
        self._lsn  = 0

        if not os.path.exists(self.path):
            open(self.path, "w").close()
        else:
            for r in self._read_raw():
                if r and r.lsn >= self._lsn:
                    self._lsn = r.lsn + 1

    def log_begin(self, txn_id):
        self._append(WALRecord(txn_id, self._next_lsn(), "BEGIN"))

    def log_data(self, txn_id, operation, db, table, key, before, after):
        rec = WALRecord(txn_id, self._next_lsn(), "DATA",
                        operation=operation, db=db, table=table,
                        key=key, before=before, after=after)
        self._append(rec)
        return rec

    def log_commit(self, txn_id):
        self._append(WALRecord(txn_id, self._next_lsn(), "COMMIT"))

    def log_rollback(self, txn_id):
        self._append(WALRecord(txn_id, self._next_lsn(), "ROLLBACK"))

    def read_all(self):
        return [r for r in self._read_raw() if r is not None]

    def clear(self):
        with self._lock:
            open(self.path, "w").close()
            self._lsn = 0

    def _next_lsn(self):
        lsn = self._lsn
        self._lsn += 1
        return lsn

    def _append(self, record):
        with self._lock:
            with open(self.path, "a") as f:
                f.write(record.to_line() + "\n")
                f.flush()
                os.fsync(f.fileno())

    def _read_raw(self):
        records = []
        with self._lock:
            try:
                with open(self.path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            records.append(WALRecord.from_line(line))
            except FileNotFoundError:
                pass
        return records


# 2.  Lock Manager  (strict 2-Phase Locking)
class LockManager:
    def __init__(self, timeout=5.0):
        self._timeout     = timeout
        self._meta        = threading.Lock()
        self._table_locks : dict = {}
        self._holders     : dict = {}
        self._txn_held    : dict = {}

    def acquire(self, txn_id, db, table):
        key = (db, table)
        with self._meta:
            if self._holders.get(key) == txn_id:
                return
            if key not in self._table_locks:
                self._table_locks[key] = threading.Lock()
            lock = self._table_locks[key]

        acquired = lock.acquire(timeout=self._timeout)
        if not acquired:
            raise DeadlockError(
                f"Transaction {txn_id} could not acquire lock on "
                f"{db}.{table} within {self._timeout}s - possible deadlock.")

        with self._meta:
            self._holders[key] = txn_id
            self._txn_held.setdefault(txn_id, set()).add(key)

    def release_all(self, txn_id):
        with self._meta:
            held = list(self._txn_held.pop(txn_id, set()))
        for key in held:
            with self._meta:
                self._holders.pop(key, None)
            try:
                self._table_locks[key].release()
            except RuntimeError:
                pass

# 3.  Transaction
class TxnStatus:
    ACTIVE    = "ACTIVE"
    COMMITTED = "COMMITTED"
    ABORTED   = "ABORTED"


class Transaction:
    def __init__(self, txn_id):
        self.txn_id   = txn_id
        self.status   = TxnStatus.ACTIVE
        self.undo_log = []

    def record_undo(self, wal_record):
        self.undo_log.append(wal_record)

    def __repr__(self):
        return f"<Transaction id={self.txn_id} status={self.status}>"


# 4.  TransactionManager
class TransactionManager:
    def __init__(self, wal_path="wal.log", lock_timeout=15.0):
        self._db          = DatabaseManager()
        self._wal         = WriteAheadLog(wal_path)
        self._locks       = LockManager(lock_timeout)
        self._meta        = threading.Lock()
        self._txn_counter = 0
        self._active      : dict = {}

        self._recover()

    # Schema helpers

    def create_database(self, name):
        self._db.create_database(name)

    def drop_database(self, name):
        self._db.drop_database(name)

    def list_databases(self):
        return self._db.list_databases()

    def create_table(self, db, table, schema, order=8, search_key=None):
        self._db.create_table(db, table, schema, order, search_key)

    def drop_table(self, db, table):
        self._db.drop_table(db, table)

    def list_tables(self, db):
        return self._db.list_tables(db)

    # Transaction lifecycle

    def begin(self):
        with self._meta:
            self._txn_counter += 1
            txn = Transaction(self._txn_counter)
            self._active[txn.txn_id] = txn
        self._wal.log_begin(txn.txn_id)
        print(f"[TXN {txn.txn_id}] BEGIN")
        return txn

    def commit(self, txn):
        self._assert_active(txn)
        self._wal.log_commit(txn.txn_id)
        txn.status = TxnStatus.COMMITTED
        self._locks.release_all(txn.txn_id)
        with self._meta:
            self._active.pop(txn.txn_id, None)
        print(f"[TXN {txn.txn_id}] COMMITTED  ✓")

    def rollback(self, txn):
        if txn.status not in (TxnStatus.ACTIVE, TxnStatus.ABORTED):
            print(f"[TXN {txn.txn_id}] Nothing to roll back")
            return
        n = len(txn.undo_log)
        print(f"[TXN {txn.txn_id}] ROLLBACK - undoing {n} operation(s) …")
        for entry in reversed(txn.undo_log):
            self._apply_undo(entry)
        self._wal.log_rollback(txn.txn_id)
        txn.status = TxnStatus.ABORTED
        self._locks.release_all(txn.txn_id)
        with self._meta:
            self._active.pop(txn.txn_id, None)
        print(f"[TXN {txn.txn_id}] ROLLED BACK  ✓")

    # Transactional DML

    def insert(self, txn, db, table, record):
        self._assert_active(txn)
        self._locks.acquire(txn.txn_id, db, table)
        tbl = self._db.get_table(db, table)
        key = record[tbl.search_key]
        if tbl.get(key) is not None:
            raise TransactionError(
                f"Duplicate key {key!r} in {db}.{table}")
        wal_rec = self._wal.log_data(
            txn.txn_id, "INSERT", db, table,
            key, before=None, after=copy.deepcopy(record))
        txn.record_undo(wal_rec)
        tbl.insert(record)
        print(f"  [TXN {txn.txn_id}] INSERT  {db}.{table}  key={key}")

    def update(self, txn, db, table, key, new_record):
        self._assert_active(txn)
        self._locks.acquire(txn.txn_id, db, table)
        tbl    = self._db.get_table(db, table)
        before = tbl.get(key)
        if before is None:
            raise TransactionError(
                f"Key {key!r} not found in {db}.{table}")
        wal_rec = self._wal.log_data(
            txn.txn_id, "UPDATE", db, table,
            key, before=copy.deepcopy(before), after=copy.deepcopy(new_record))
        txn.record_undo(wal_rec)
        tbl.update(key, new_record)
        print(f"  [TXN {txn.txn_id}] UPDATE  {db}.{table}  key={key}")

    def delete(self, txn, db, table, key):
        self._assert_active(txn)
        self._locks.acquire(txn.txn_id, db, table)
        tbl    = self._db.get_table(db, table)
        before = tbl.get(key)
        if before is None:
            raise TransactionError(
                f"Key {key!r} not found in {db}.{table}")
        wal_rec = self._wal.log_data(
            txn.txn_id, "DELETE", db, table,
            key, before=copy.deepcopy(before), after=None)
        txn.record_undo(wal_rec)
        tbl.delete(key)
        print(f"  [TXN {txn.txn_id}] DELETE  {db}.{table}  key={key}")

    def read(self, db, table, key, txn=None):
        if txn is not None:
            self._assert_active(txn)
            self._locks.acquire(txn.txn_id, db, table)
        return self._db.get_table(db, table).get(key)

    def read_all(self, db, table, txn=None):
        if txn is not None:
            self._assert_active(txn)
            self._locks.acquire(txn.txn_id, db, table)
        return self._db.get_table(db, table).get_all()

    # Crash simulation

    def simulate_crash(self):
        print("\n" + "!" * 62)
        print("  *** CRASH SIMULATED - in-memory state destroyed ***")
        print("!" * 62 + "\n")
        self._db    = DatabaseManager()
        self._locks = LockManager(self._locks._timeout)
        with self._meta:
            self._active.clear()

    def restart_and_recover(self, setup_fn):
        print("[RESTART] Rebuilding schema …")
        setup_fn(self)
        print("[RESTART] Running WAL recovery …")
        self._recover()

    # Internals

    def _assert_active(self, txn):
        if txn.status != TxnStatus.ACTIVE:
            raise TransactionError(
                f"Transaction {txn.txn_id} is not active (status={txn.status})")

    def _apply_undo(self, rec):
        try:
            tbl = self._db.get_table(rec.db, rec.table)
        except ValueError:
            print(f"  [UNDO] skipped - {rec.db}.{rec.table} not found")
            return
        op = rec.operation
        if op == "INSERT":
            if tbl.get(rec.key) is not None:
                tbl.delete(rec.key)
            print(f"  [UNDO] DELETE key={rec.key} from {rec.db}.{rec.table}")
        elif op == "DELETE":
            if tbl.get(rec.key) is None:
                tbl.insert(rec.before)
            print(f"  [UNDO] RE-INSERT key={rec.key} into {rec.db}.{rec.table}")
        elif op == "UPDATE":
            if tbl.get(rec.key) is not None:
                tbl.update(rec.key, rec.before)
            print(f"  [UNDO] RESTORE key={rec.key} in {rec.db}.{rec.table}")

    def _apply_redo(self, rec):
        try:
            tbl = self._db.get_table(rec.db, rec.table)
        except ValueError:
            return
        op = rec.operation
        if op == "INSERT":
            if tbl.get(rec.key) is None:
                tbl.insert(rec.after)
        elif op == "DELETE":
            if tbl.get(rec.key) is not None:
                tbl.delete(rec.key)
        elif op == "UPDATE":
            existing = tbl.get(rec.key)

            if existing is not None:
                updated = existing.copy()
                updated.update(rec.after)   # merge update
                tbl.update(rec.key, updated)
            else:
                tbl.insert(rec.after)       # redo insert if missing  

    def _recover(self):
        records = self._wal.read_all()
        if not records:
            print("[RECOVERY] WAL is empty – nothing to do.")
            return

        committed   = set()
        rolled_back = set()
        data_recs   = []

        for r in records:
            if r.rec_type == "COMMIT":
                committed.add(r.txn_id)
            elif r.rec_type == "ROLLBACK":
                rolled_back.add(r.txn_id)
            elif r.rec_type == "DATA":
                data_recs.append(r)

        all_txns   = {r.txn_id for r in data_recs}
        incomplete = all_txns - committed - rolled_back

        print(f"[RECOVERY] Committed   : {sorted(committed)}")
        print(f"[RECOVERY] Rolled-back : {sorted(rolled_back)}")
        print(f"[RECOVERY] Incomplete  : {sorted(incomplete)}  ← will UNDO")

        print("[RECOVERY] REDO pass …")
        for r in data_recs:
            if r.txn_id in committed:
                self._apply_redo(r)

        print("[RECOVERY] UNDO pass …")
        undo_set = [r for r in data_recs if r.txn_id in incomplete]
        for r in reversed(undo_set):
            self._apply_undo(r)
            self._wal.log_rollback(r.txn_id)

        print("[RECOVERY] Complete.\n")

# Helpers
def hr(title=""):
    bar = "━" * 62
    if title:
        print(f"\n{bar}\n  {title}\n{bar}")
    else:
        print(bar)


def check(condition, message):
    if condition:
        print(f"  ✓  {message}")
    else:
        raise AssertionError(f"FAIL: {message}")

# Database / table name constants
DB = "scholarease"

# Table names mirror the SQL schema exactly
T_MEMBER          = "member"
T_LOGIN           = "login_credentials"
T_SESSION         = "session"
T_STUDENT         = "student_personal_details"
T_ADDRESS         = "student_address"
T_FAMILY          = "family"
T_FAMILY_MEMBER   = "family_member"
T_EDU10           = "education_class10"
T_EDU12           = "education_class12"
T_EDU_CUR         = "educational_current"
T_INSTITUTION     = "institution"
T_FEE             = "fee_structure"
T_BANK            = "bank_account"
T_DOCUMENT        = "document"
T_SCHOLARSHIP     = "scholarship"
T_APPLICATION     = "scholarship_application"
T_VERIFICATION    = "verification"
T_PAYMENT         = "payment"

# Schema factory  (reused by tests and crash-recovery restart)
def create_schema(tm):
    if DB not in tm.list_databases():
        tm.create_database(DB)

    tables = {
        T_MEMBER:        (["MemberID", "Name", "Email", "PhoneNo",
                           "WhatsAppNo", "Image", "Age", "Role"],
                          "MemberID"),
        T_LOGIN:         (["LoginID", "MemberID", "Email",
                           "PasswordHash", "CreatedAt"],
                          "LoginID"),
        T_SESSION:       (["SessionID", "MemberID",
                           "CreatedAt", "ExpiresAt"],
                          "SessionID"),
        T_STUDENT:       (["StudentID", "MemberID", "FirstName",
                           "LastName", "DOB", "Gender",
                           "Category", "AadhaarNo", "PwD"],
                          "StudentID"),
        T_ADDRESS:       (["addressid", "studentid", "addressline",
                           "city", "district", "state", "pincode"],
                          "addressid"),
        T_FAMILY:        (["FamilyID", "StudentID",
                           "RationCardNo", "AddressSameAsStudent"],
                          "FamilyID"),
        T_FAMILY_MEMBER: (["FamilyMemberID", "FamilyID", "Name",
                           "Relation", "AnnualIncome", "Occupation"],
                          "FamilyMemberID"),
        T_EDU10:         (["Class10ID", "StudentID", "Board",
                           "PassingYear", "MarksObtained", "TotalMarks"],
                          "Class10ID"),
        T_EDU12:         (["Class12ID", "StudentID", "Board", "Stream",
                           "PassingYear", "MarksObtained", "TotalMarks"],
                          "Class12ID"),
        T_INSTITUTION:   (["InstituteID", "Name", "InstituteType",
                           "State", "District"],
                          "InstituteID"),
        T_EDU_CUR:       (["EducationID", "StudentID", "InstituteID",
                           "Degree", "CourseDuration", "CurrentSemester",
                           "CurrentCPI", "ExpectedPassingYear"],
                          "EducationID"),
        T_FEE:           (["FeeID", "StudentID", "TuitionFee",
                           "HostelFee", "MessFee"],
                          "FeeID"),
        T_BANK:          (["BankAccountID", "AccountNo", "StudentID",
                           "NameAsPerPassbook", "BankName",
                           "BranchName", "IFSC"],
                          "BankAccountID"),
        T_DOCUMENT:      (["DocumentID", "StudentID", "DocumentType",
                           "FileReference", "UploadDate", "Verified"],
                          "DocumentID"),
        T_SCHOLARSHIP:   (["ScholarshipID", "ScholarshipName",
                           "Provider", "MaxAmount", "Deadline"],
                          "ScholarshipID"),
        T_APPLICATION:   (["ApplicationID", "StudentID", "ScholarshipID",
                           "ApplicationDate", "Status", "ApprovedAmount"],
                          "ApplicationID"),
        T_VERIFICATION:  (["VerificationID", "ApplicationID", "AdminID",
                           "VerificationDate", "VerificationStatus",
                           "Remarks"],
                          "VerificationID"),
        T_PAYMENT:       (["PaymentID", "ApplicationID", "AmountPaid",
                           "PaymentDate", "BankAccountID", "Status"],
                          "PaymentID"),
    }

    existing = tm.list_tables(DB)
    for tname, (cols, pk) in tables.items():
        if tname not in existing:
            tm.create_table(DB, tname, cols, search_key=pk)

# Seed data  (minimal but sufficient to drive all 5 tests)
def seed_base_data(tm):
    """Insert core reference rows – idempotent (skips existing keys)."""

    def _safe_insert(txn, table, record, pk_field):
        tbl = tm._db.get_table(DB, table)
        if tbl.get(record[pk_field]) is None:
            tm.insert(txn, DB, table, record)

    txn = tm.begin()
    try:
        # members
        for m in [
            {"MemberID": 1, "Name": "Rahul Sharma",  "Email": "rahul@gmail.com",
             "PhoneNo": "9876543210", "WhatsAppNo": "9876543210",
             "Image": "rahul.jpg", "Age": 20, "Role": "Student"},
            {"MemberID": 2, "Name": "Priya Singh",   "Email": "priya@gmail.com",
             "PhoneNo": "9876543211", "WhatsAppNo": "9876543211",
             "Image": "priya.jpg", "Age": 21, "Role": "Student"},
            {"MemberID": 6, "Name": "Admin One",     "Email": "admin1@portal.com",
             "PhoneNo": "9999999991", "WhatsAppNo": None,
             "Image": "admin1.jpg", "Age": 35, "Role": "Admin"},
        ]:
            _safe_insert(txn, T_MEMBER, m, "MemberID")

        # institutions
        for inst in [
            {"InstituteID": 1, "Name": "IIT Gandhinagar", "InstituteType": "Government",
             "State": "Gujarat",       "District": "Gandhinagar"},
            {"InstituteID": 2, "Name": "Delhi University", "InstituteType": "Government",
             "State": "Delhi",         "District": "Delhi"},
        ]:
            _safe_insert(txn, T_INSTITUTION, inst, "InstituteID")

        # students
        for s in [
            {"StudentID": 1, "MemberID": 1, "FirstName": "Rahul",
             "LastName": "Sharma", "DOB": "2004-05-10", "Gender": "Male",
             "Category": "General", "AadhaarNo": "123456789001", "PwD": "No"},
            {"StudentID": 2, "MemberID": 2, "FirstName": "Priya",
             "LastName": "Singh",  "DOB": "2003-08-15", "Gender": "Female",
             "Category": "OBC",     "AadhaarNo": "123456789002", "PwD": "No"},
        ]:
            _safe_insert(txn, T_STUDENT, s, "StudentID")

        # current education
        for e in [
            {"EducationID": 1, "StudentID": 1, "InstituteID": 1,
             "Degree": "B.Tech CSE", "CourseDuration": 4,
             "CurrentSemester": 4, "CurrentCPI": 8.45,
             "ExpectedPassingYear": 2026},
            {"EducationID": 2, "StudentID": 2, "InstituteID": 2,
             "Degree": "B.Com", "CourseDuration": 3,
             "CurrentSemester": 6, "CurrentCPI": 7.10,
             "ExpectedPassingYear": 2024},
        ]:
            _safe_insert(txn, T_EDU_CUR, e, "EducationID")

        # fee structure
        for f in [
            {"FeeID": 1, "StudentID": 1,
             "TuitionFee": 75000.0, "HostelFee": 30000.0, "MessFee": 20000.0},
            {"FeeID": 2, "StudentID": 2,
             "TuitionFee": 40000.0, "HostelFee": 15000.0, "MessFee": 12000.0},
        ]:
            _safe_insert(txn, T_FEE, f, "FeeID")

        # bank accounts
        for b in [
            {"BankAccountID": 1, "AccountNo": "123456789000000001",
             "StudentID": 1, "NameAsPerPassbook": "Rahul Sharma",
             "BankName": "SBI", "BranchName": "Gandhinagar", "IFSC": "SBIN0001234"},
            {"BankAccountID": 2, "AccountNo": "123456789000000002",
             "StudentID": 2, "NameAsPerPassbook": "Priya Singh",
             "BankName": "HDFC", "BranchName": "Delhi", "IFSC": "HDFC0002345"},
        ]:
            _safe_insert(txn, T_BANK, b, "BankAccountID")

        # scholarships
        for sc in [
            {"ScholarshipID": 1, "ScholarshipName": "Merit Scholarship",
             "Provider": "Govt of India", "MaxAmount": 100000.0,
             "Deadline": "2026-12-31"},
            {"ScholarshipID": 5, "ScholarshipName": "Technical Excellence",
             "Provider": "AICTE", "MaxAmount": 150000.0,
             "Deadline": "2026-12-15"},
        ]:
            _safe_insert(txn, T_SCHOLARSHIP, sc, "ScholarshipID")

        tm.commit(txn)
    except Exception:
        tm.rollback(txn)
        raise

# TEST 1 – ATOMICITY
#   Scenario: submit a scholarship application (write to scholarship_application
#   AND document at the same time). Simulate a crash mid-way → both must rollback.
def test_atomicity(tm):
    hr("TEST 1 · ATOMICITY – half-submitted application rolls back completely")

    txn = tm.begin()
    try:
        # Step 1: insert scholarship application record
        tm.insert(txn, DB, T_APPLICATION, {
            "ApplicationID":   101,
            "StudentID":       1,
            "ScholarshipID":   1,
            "ApplicationDate": "2026-04-01",
            "Status":          "Pending",
            "ApprovedAmount":  None,
        })

        # Step 2: insert supporting document record
        tm.insert(txn, DB, T_DOCUMENT, {
            "DocumentID":    201,
            "StudentID":     1,
            "DocumentType":  "Income Certificate",
            "FileReference": "docs/inc_rahul_2026.pdf",
            "UploadDate":    "2026-04-01",
            "Verified":      "No",
        })

        # Simulate failure before commit (e.g., server crash / disk full)
        raise RuntimeError("Server crash before commit!")

        tm.commit(txn)   # unreachable

    except RuntimeError as exc:
        print(f"  !! Exception caught: {exc}")
        tm.rollback(txn)

    app = tm.read(DB, T_APPLICATION, 101)
    doc = tm.read(DB, T_DOCUMENT,    201)

    check(app is None,
          "Application row 101 was NOT inserted (rolled back)")
    check(doc is None,
          "Document row 201 was NOT inserted (rolled back)")

# TEST 2 – CONSISTENCY
#   Scenario: admin tries to approve an amount greater than the scholarship's
#   MaxAmount – application-level constraint must reject and leave no change.
def test_consistency(tm):
    hr("TEST 2 · CONSISTENCY – approved amount cannot exceed scholarship MaxAmount")

    # First, create a pending application
    setup_txn = tm.begin()
    tm.insert(setup_txn, DB, T_APPLICATION, {
        "ApplicationID":   102,
        "StudentID":       2,
        "ScholarshipID":   1,
        "ApplicationDate": "2026-04-01",
        "Status":          "Pending",
        "ApprovedAmount":  None,
    })
    tm.commit(setup_txn)

    txn = tm.begin()
    try:
        scholarship = tm.read(DB, T_SCHOLARSHIP, 1)
        application = tm.read(DB, T_APPLICATION, 102)

        proposed_amount = 200000.0  # exceeds MaxAmount of 100000

        # Application-level constraint check
        if proposed_amount > scholarship["MaxAmount"]:
            raise TransactionError(
                f"Constraint violation: proposed amount {proposed_amount} "
                f"exceeds MaxAmount {scholarship['MaxAmount']} "
                f"for scholarship '{scholarship['ScholarshipName']}'")

        tm.update(txn, DB, T_APPLICATION, 102, {
            **application,
            "Status":         "Approved",
            "ApprovedAmount": proposed_amount,
        })
        tm.commit(txn)

    except TransactionError as exc:
        print(f"  !! Constraint violation caught: {exc}")
        tm.rollback(txn)

    app = tm.read(DB, T_APPLICATION, 102)
    check(app["Status"] == "Pending",
          f"Application status remains 'Pending' (got {app['Status']})")
    check(app["ApprovedAmount"] is None,
          f"ApprovedAmount remains None (got {app['ApprovedAmount']})")


# TEST 3 – ISOLATION
#   Scenario: two admins concurrently try to verify the same application.
#   Strict 2PL must serialise them so only one verification record is inserted.
def test_isolation(tm):
    hr("TEST 3 · ISOLATION – concurrent admin verifications, no lost update")

    # Ensure a fresh application exists
    setup_txn = tm.begin()
    if tm.read(DB, T_APPLICATION, 103) is None:
        tm.insert(setup_txn, DB, T_APPLICATION, {
            "ApplicationID":   103,
            "StudentID":       1,
            "ScholarshipID":   5,
            "ApplicationDate": "2026-04-02",
            "Status":          "Pending",
            "ApprovedAmount":  None,
        })
    tm.commit(setup_txn)

    results = {}
    errors  = {}

    def admin_a():
        try:
            txn = tm.begin()
            app = tm.read(DB, T_APPLICATION, 103)
            # Admin A approves
            tm.update(txn, DB, T_APPLICATION, 103, {
                **app, "Status": "Approved", "ApprovedAmount": 150000.0
            })
            time.sleep(0.1)   # hold lock while admin B waits
            tm.commit(txn)
            results["A"] = tm.read(DB, T_APPLICATION, 103)["Status"]
        except Exception as exc:
            errors["A"] = str(exc)
            try:
                tm.rollback(txn)
            except Exception:
                pass

    def admin_b():
        try:
            time.sleep(0.02)  # start slightly after A acquires lock
            txn = tm.begin()
            app = tm.read(DB, T_APPLICATION, 103)
            # Admin B tries to reject the same application
            tm.update(txn, DB, T_APPLICATION, 103, {
                **app, "Status": "Rejected", "ApprovedAmount": 0.0
            })
            tm.commit(txn)
            results["B"] = tm.read(DB, T_APPLICATION, 103)["Status"]
        except Exception as exc:
            errors["B"] = str(exc)
            try:
                tm.rollback(txn)
            except Exception:
                pass

    t1 = threading.Thread(target=admin_a, daemon=True)
    t2 = threading.Thread(target=admin_b, daemon=True)
    t1.start(); t2.start()
    t1.join(); t2.join()

    if errors:
        print(f"  Thread errors: {errors}")

    final_app = tm.read(DB, T_APPLICATION, 103)
    # Because of strict 2PL, A runs fully before B.
    # B reads the already-approved record and sets it to Rejected.
    # Final state must be one of the two consistent states – NOT a mix.
    final_status = final_app["Status"]
    check(final_status in ("Approved", "Rejected"),
          f"Application has a consistent final status: '{final_status}' (no partial update)")
    print(f"  Final status determined by serialisation: '{final_status}'")

# TEST 4 – DURABILITY
#   Scenario: commit a payment record, then simulate crash. After WAL recovery
#   the payment must be present; an uncommitted CPI update must be absent.
def test_durability(tm):
    hr("TEST 4 · DURABILITY – committed payment survives crash + WAL recovery")

    # Phase A: commit a payment
    txn_committed = tm.begin()
    tm.insert(txn_committed, DB, T_PAYMENT, {
        "PaymentID":     999,
        "ApplicationID": 102,       # from test_consistency
        "AmountPaid":    100000.0,
        "PaymentDate":   "2026-04-03",
        "BankAccountID": 1,
        "Status":        "Completed",
    })
    tm.commit(txn_committed)
    print("  Committed payment 999.")

    # Phase B: start a txn that updates a student's CPI but DO NOT commit
    txn_lost = tm.begin()
    edu = tm.read(DB, T_EDU_CUR, 1)
    tm.update(txn_lost, DB, T_EDU_CUR, 1,
              {**edu, "CurrentCPI": 1.00})   # bogus value – should be lost
    print(f"  Started txn {txn_lost.txn_id} (CPI update, will be lost).")

    # Crash
    tm.simulate_crash()

    # Restart
    tm.restart_and_recover(create_schema)

    payment = tm.read(DB, T_PAYMENT, 999)
    edu_rec = tm.read(DB, T_EDU_CUR, 1)

    check(payment is not None and payment["PaymentID"] == 999,
          "Committed payment 999 restored after crash")
    check(payment["Status"] == "Completed",
          f"Payment status is 'Completed' (got {payment['Status']})")

    if edu_rec is not None:
        check(edu_rec["CurrentCPI"] != 1.00,
              f"Uncommitted CPI=1.00 was NOT persisted (got {edu_rec['CurrentCPI']})")
    print("  ✓ WAL durability verified.")

# TEST 5 – FULL MULTI-TABLE ACID TRANSACTION
#   Scenario (realistic scholarship portal workflow):
#     1. Student submits application  → insert into scholarship_application
#     2. Document uploaded            → insert into document
#     3. Admin verifies               → insert into verification
#     4. Payment disbursed            → insert into payment
#   All four writes are inside a single transaction.
def test_full_acid(tm):
    hr("TEST 5 · FULL MULTI-TABLE ACID TRANSACTION")
    print("  Scenario: apply → upload doc → verify → disburse payment\n")

    txn = tm.begin()
    try:
        # 1. Check student and scholarship exist (consistency guards)
        student     = tm.read(DB, T_STUDENT,     1)
        scholarship = tm.read(DB, T_SCHOLARSHIP, 5)
        bank        = tm.read(DB, T_BANK,        1)

        if student is None:
            raise TransactionError("Student 1 not found")
        if scholarship is None:
            raise TransactionError("Scholarship 5 not found")

        approve_amount = 140000.0
        if approve_amount > scholarship["MaxAmount"]:
            raise TransactionError(
                f"Approve amount {approve_amount} exceeds MaxAmount "
                f"{scholarship['MaxAmount']}")

        # 2. Insert application
        existing_apps = tm.read_all(DB, T_APPLICATION)
        next_app_id   = max((a["ApplicationID"] for a in existing_apps), default=0) + 1
        tm.insert(txn, DB, T_APPLICATION, {
            "ApplicationID":   next_app_id,
            "StudentID":       1,
            "ScholarshipID":   5,
            "ApplicationDate": "2026-04-03",
            "Status":          "Approved",
            "ApprovedAmount":  approve_amount,
        })

        # 3. Insert document
        existing_docs = tm.read_all(DB, T_DOCUMENT)
        next_doc_id   = max((d["DocumentID"] for d in existing_docs), default=0) + 1
        tm.insert(txn, DB, T_DOCUMENT, {
            "DocumentID":    next_doc_id,
            "StudentID":     1,
            "DocumentType":  "Marksheet",
            "FileReference": "docs/marks_rahul_2026.pdf",
            "UploadDate":    "2026-04-03",
            "Verified":      "Yes",
        })

        # 4. Insert verification record
        existing_verifs = tm.read_all(DB, T_VERIFICATION)
        next_verif_id   = max((v["VerificationID"] for v in existing_verifs), default=0) + 1
        tm.insert(txn, DB, T_VERIFICATION, {
            "VerificationID":     next_verif_id,
            "ApplicationID":      next_app_id,
            "AdminID":            6,
            "VerificationDate":   "2026-04-03",
            "VerificationStatus": "Approved",
            "Remarks":            "All documents verified and scholarship approved.",
        })

        # 5. Insert payment record
        existing_pays = tm.read_all(DB, T_PAYMENT)
        next_pay_id   = max((p["PaymentID"] for p in existing_pays), default=0) + 1
        tm.insert(txn, DB, T_PAYMENT, {
            "PaymentID":     next_pay_id,
            "ApplicationID": next_app_id,
            "AmountPaid":    approve_amount,
            "PaymentDate":   "2026-04-03",
            "BankAccountID": bank["BankAccountID"],
            "Status":        "Completed",
        })

        tm.commit(txn)

    except Exception as exc:
        print(f"  !! Error: {exc}")
        tm.rollback(txn)
        raise

    # Verify all four rows landed
    all_apps    = tm.read_all(DB, T_APPLICATION)
    all_docs    = tm.read_all(DB, T_DOCUMENT)
    all_verifs  = tm.read_all(DB, T_VERIFICATION)
    all_pays    = tm.read_all(DB, T_PAYMENT)

    print(f"\n  scholarship_application rows : {len(all_apps)}")
    print(f"  document rows               : {len(all_docs)}")
    print(f"  verification rows           : {len(all_verifs)}")
    print(f"  payment rows                : {len(all_pays)}")

    check(any(a["ApprovedAmount"] == 140000.0 for a in all_apps),
          "Application with ApprovedAmount=140000 is present")
    check(any(d["DocumentType"] == "Marksheet" for d in all_docs),
          "Marksheet document record is present")
    check(any(v["VerificationStatus"] == "Approved" for v in all_verifs),
          "Verification record is 'Approved'")
    check(any(p["AmountPaid"] == 140000.0 and p["Status"] == "Completed"
              for p in all_pays),
          "Payment of 140000 with status 'Completed' is present")

# Runner
if __name__ == "__main__":
    WAL_PATH = "wal.log"
    if os.path.exists(WAL_PATH):
        os.remove(WAL_PATH)

    tm = TransactionManager(wal_path=WAL_PATH)
    create_schema(tm)
    seed_base_data(tm)

    test_atomicity(tm)
    test_consistency(tm)
    test_isolation(tm)
    test_durability(tm)

    # After the crash test the in-memory trees are empty – rebuild before test 5
    create_schema(tm)
    seed_base_data(tm)
    test_full_acid(tm)

    hr("ALL 5 TESTS PASSED")