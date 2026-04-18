import os
import sys
import threading
import time
import random

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, root_dir)

from Module_A.transaction.transaction_manager import TransactionManager, DeadlockError

DB = "scholarease"
TABLE = "seats"
WAL = os.path.join(os.path.dirname(__file__), "wal.log")


def clean():
    try:
        os.remove(WAL)
    except:
        pass


def setup(tm, slots):
    if DB not in tm.list_databases():
        tm.create_database(DB)

    tm.create_table(DB, TABLE, ["ID", "Slots"], search_key="ID")

    txn = tm.begin()
    try:
        if tm.read(DB, TABLE, 1) is None:
            tm.insert(txn, DB, TABLE, {"ID": 1, "Slots": slots})
        tm.commit(txn)
    except:
        tm.rollback(txn)


def worker(tm, results):
    txn = tm.begin()
    try:
        row = tm.read(DB, TABLE, 1, txn=txn)

        if row["Slots"] <= 0:
            tm.commit(txn)
            results.append(False)
            return

        time.sleep(random.uniform(0.01, 0.05))

        tm.update(txn, DB, TABLE, 1, {"ID": 1, "Slots": row["Slots"] - 1})
        tm.commit(txn)
        results.append(True)
    except DeadlockError:
        tm.rollback(txn)
        results.append(False)
    except:
        tm.rollback(txn)
        results.append(False)


def run_test(users, slots):
    clean()
    tm = TransactionManager(wal_path=WAL)
    setup(tm, slots)

    results = []
    threads = [threading.Thread(target=worker, args=(tm, results)) for _ in range(users)]

    for t in threads: t.start()
    for t in threads: t.join()

    final = tm.read(DB, TABLE, 1)["Slots"]
    success = sum(results)

    expected = slots

    print("EXPECTED SUCCESS:", expected)
    print("ACTUAL SUCCESS  :", success)
    print("FINAL SLOTS     :", final)
    print("RESULT          :", "PASS" if success == expected and final == 0 else "FAIL")


def lost_update():
    print("\nTEST 1: LOST UPDATE")
    run_test(10, 1)


def high_contention():
    print("\nTEST 2: HIGH CONTENTION")
    run_test(50, 5)


def stress():
    print("\nTEST 3: STRESS TEST")
    start = time.time()
    run_test(200, 20)
    print("TIME:", round(time.time() - start, 2), "s")


def crash():
    print("\nTEST 4: CRASH + RECOVERY")

    clean()
    tm = TransactionManager(wal_path=WAL)
    setup(tm, 5)

    txn = tm.begin()
    tm.update(txn, DB, TABLE, 1, {"ID": 1, "Slots": 3})
    tm.commit(txn)

    tm.simulate_crash()
    tm.restart_and_recover(lambda m: setup(m, 5))

    final = tm.read(DB, TABLE, 1)
    print("RESULT:", "PASS" if final else "FAIL")


def deadlock():
    print("\nTEST 5: DEADLOCK")

    tm = TransactionManager(wal_path=WAL)

    tm.create_database(DB)
    tm.create_table(DB, "A", ["id"], search_key="id")
    tm.create_table(DB, "B", ["id"], search_key="id")

    txn = tm.begin()
    tm.insert(txn, DB, "A", {"id": 1})
    tm.insert(txn, DB, "B", {"id": 1})
    tm.commit(txn)

    results = []

    def t1():
        txn = tm.begin()
        try:
            tm.update(txn, DB, "A", 1, {"id": 1})
            time.sleep(1)
            tm.update(txn, DB, "B", 1, {"id": 1})
            tm.commit(txn)
            results.append(True)
        except:
            tm.rollback(txn)
            results.append(False)

    def t2():
        txn = tm.begin()
        try:
            tm.update(txn, DB, "B", 1, {"id": 1})
            time.sleep(1)
            tm.update(txn, DB, "A", 1, {"id": 1})
            tm.commit(txn)
            results.append(True)
        except:
            tm.rollback(txn)
            results.append(False)

    a = threading.Thread(target=t1)
    b = threading.Thread(target=t2)
    a.start(); b.start()
    a.join(); b.join()

    print("RESULT:", "PASS" if not all(results) else "FAIL")


def main():
    lost_update()
    high_contention()
    stress()
    crash()
    deadlock()
    print("\nALL TESTS COMPLETE")


if __name__ == "__main__":
    main()