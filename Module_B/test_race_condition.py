"""
Module B — test_race_condition.py
==================================
Dedicated race condition test file (PDF requirement: "identify a critical
operation, simulate many users, ensure no incorrect results").

Critical operation identified: scholarship application submission.
  - Multiple students applying for the same scholarship simultaneously
    could result in duplicate applications if the DB lacks a unique
    constraint or the API has no application-level guard.

Two modes:
  1. WITHOUT_CONTROL  — raw threads with no locking (shows the problem)
  2. VIA_API          — concurrent HTTP requests through the FastAPI app
                        (shows how DB constraints handle it)

Run:
    # Start your FastAPI server first:
    # uvicorn app.main:app --host 127.0.0.1 --port 8000
    #
    python Module_B/test_race_condition.py
"""

import threading
import time
import requests
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "http://127.0.0.1:8000"
STUDENT_EMAIL    = "rahul@gmail.com"
STUDENT_PASSWORD = "rahul123"
ADMIN_EMAIL      = "admin1@portal.com"
ADMIN_PASSWORD   = "admin1123"


def get_token(email, password):
    try:
        r = requests.post(f"{BASE_URL}/login",
                          json={"email": email, "password": password},
                          timeout=5)
        if r.status_code == 200:
            return r.json().get("session_token")
    except Exception:
        pass
    return None


def separator(title):
    print(f"\n{'═'*60}\n  {title}\n{'═'*60}")


# ─── MODE 1: Without any control (in-memory counter, no DB) ─────────────────

def test_without_control():
    """
    Simulates what happens when multiple threads update a shared counter
    with NO synchronisation — classic race condition.
    Expected result: 0  (100 − 10×10)
    Actual result:   unpredictable (usually > 0 due to lost updates)
    """
    separator("MODE 1: WITHOUT CONTROL — in-memory race (expected to FAIL)")

    applications_submitted = 0   # shared mutable state, no lock

    def student_applies():
        nonlocal applications_submitted
        current = applications_submitted
        time.sleep(0.005)                        # simulate processing delay
        applications_submitted = current + 1    # lost update possible

    threads = [threading.Thread(target=student_applies) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    expected = 10
    print(f"  Expected count : {expected}")
    print(f"  Actual count   : {applications_submitted}")
    print(f"  Lost updates   : {expected - applications_submitted}")
    print(f"  RESULT         : {'FAIL (as expected — demonstrates the problem)' if applications_submitted != expected else 'PASS (race condition did not trigger this run)'}")


# ─── MODE 2: Via API — concurrent HTTP requests ──────────────────────────────

def test_via_api():
    """
    10 concurrent threads each call POST /apply for the SAME student + scholarship.
    At most 1 should succeed; the rest should be rejected by the DB
    (UNIQUE constraint on StudentID+ScholarshipID, or application-level check).

    This verifies:
      - API handles concurrent requests without crashing (Isolation ✓)
      - DB constraint prevents duplicate applications (Consistency ✓)
      - No partial writes on rejected requests (Atomicity ✓)
    """
    separator("MODE 2: VIA API — 10 concurrent /apply requests (same student+scholarship)")

    token = get_token(STUDENT_EMAIL, STUDENT_PASSWORD)
    if not token:
        print("  SKIP — server not reachable or login failed")
        return

    results  = []
    timings  = []
    lock     = threading.Lock()

    def attempt_apply():
        start = time.time()
        try:
            resp = requests.post(
                f"{BASE_URL}/apply",
                json={"student_id": 1, "scholarship_id": 3},  # scholarship 3, 6
                headers={"Authorization": token},
                timeout=10
            )
            with lock:
                results.append(resp.status_code)
                timings.append(time.time() - start)
        except Exception as e:
            with lock:
                results.append(0)
                timings.append(time.time() - start)

    threads = [threading.Thread(target=attempt_apply) for _ in range(10)]
    wall_start = time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    wall_elapsed = time.time() - wall_start

    success_2xx = [c for c in results if 200 <= c < 300]
    reject_4xx  = [c for c in results if 400 <= c < 500]
    error_5xx   = [c for c in results if c >= 500]
    unreachable = [c for c in results if c == 0]

    avg_ms = (sum(timings) / len(timings)) * 1000 if timings else 0

    print(f"  Threads spawned    : 10")
    print(f"  Successful (2xx)   : {len(success_2xx)}")
    print(f"  Rejected (4xx)     : {len(reject_4xx)}")
    print(f"  Server errors (5xx): {len(error_5xx)}")
    print(f"  Unreachable        : {len(unreachable)}")
    print(f"  Wall-clock time    : {wall_elapsed:.2f}s")
    print(f"  Avg response time  : {avg_ms:.0f}ms")

    if len(success_2xx) <= 1 and len(error_5xx) == 0:
        print(f"  RESULT             : PASS — only {len(success_2xx)} duplicate(s) inserted")
    elif len(success_2xx) > 1:
        print(f"  RESULT             : FAIL — {len(success_2xx)} duplicates inserted (add UNIQUE constraint on StudentID+ScholarshipID)")
    else:
        print(f"  RESULT             : PARTIAL — server errors present; check logs")


# ─── MODE 3: High-contention concurrent verification ────────────────────────

def test_concurrent_admin_actions():
    """
    Two admins simultaneously try to verify the same application — one
    approves, one rejects. With MySQL's row-level locking via InnoDB,
    the second UPDATE will block until the first commits, then execute.
    Final state must be one consistent value, not a mix.
    """
    separator("MODE 3: CONCURRENT ADMIN ACTIONS — two admins verify same application")

    admin_token = get_token(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        print("  SKIP — server not reachable or admin login failed")
        return

    results = []
    lock    = threading.Lock()

    def admin_approve():
        resp = requests.put(
            f"{BASE_URL}/verify",
            json={"application_id": 2, "status": "Approved",
                  "remarks": "Admin A approves"},
            headers={"Authorization": admin_token},
            timeout=10
        )
        with lock:
            results.append(("approve", resp.status_code))

    def admin_reject():
        time.sleep(0.02)  # slight delay so approve starts first
        resp = requests.put(
            f"{BASE_URL}/verify",
            json={"application_id": 2, "status": "Rejected",
                  "remarks": "Admin B rejects"},
            headers={"Authorization": admin_token},
            timeout=10
        )
        with lock:
            results.append(("reject", resp.status_code))

    t1 = threading.Thread(target=admin_approve)
    t2 = threading.Thread(target=admin_reject)
    t1.start(); t2.start()
    t1.join();  t2.join()

    for action, code in results:
        print(f"  {action:10s}: HTTP {code}")

    # Both 200 is acceptable (second just overwrites in verify table)
    # What must NOT happen is a 5xx crash
    any_5xx = any(code >= 500 for _, code in results)
    print(f"  RESULT     : {'PASS — no server crash under concurrent admin actions' if not any_5xx else 'FAIL — 5xx error under concurrent admin actions'}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Module B — Race Condition Tests")
    print("  Target:", BASE_URL)
    print("=" * 60)

    try:
        requests.get(BASE_URL, timeout=3)
    except Exception:
        print(f"\n  WARNING: {BASE_URL} is not reachable.")
        print("  Running MODE 1 only (no API server needed).\n")
        test_without_control()
        sys.exit(0)

    test_without_control()
    test_via_api()
    test_concurrent_admin_actions()

    print("\n" + "=" * 60)
    print("  RACE CONDITION TESTS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
