"""
migrate_shards.py  –  ScholarEase  |  Assignment 4
----------------------------------------------------
Connects to all THREE real Docker shard servers and:

  STEP 1  – Creates shard_0_member / shard_1_member / shard_2_member
             on the correct shard server (shard 0 on port 3307, etc.)

  STEP 2  – Reads all records from the local `member` table
             and INSERTs each into the right shard server + table

  STEP 3  – Validates: count match, no duplicates, correct placement

Run from the project root (where .env lives):
    python migrate_shards.py

Requirements:
  - Must be on IITGN network (VPN or on-campus) to reach 10.0.116.184
  - .env must have DB_HOST / DB_USER / DB_PASSWORD / DB_NAME for local DB
"""

import os
import sys
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

# ── connection config ──────────────────────────────────────────────────────────

SHARD_HOST     = os.getenv("SHARD_HOST")
SHARD_USER     = os.getenv("SHARD_USER")
SHARD_PASSWORD = os.getenv("SHARD_PASSWORD")
SHARD_DB       = os.getenv("SHARD_DB")

SHARD_PORTS = {0: 3307, 1: 3308, 2: 3309}

# DDL — shard table mirrors the local `member` schema
CREATE_SHARD_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS shard_{shard_id}_member (
    MemberID   INT          NOT NULL,
    Name       VARCHAR(100) NOT NULL,
    Email      VARCHAR(100) NOT NULL,
    PhoneNo    VARCHAR(20),
    Age        INT,
    Role       ENUM('Student', 'Admin', 'Authority') NOT NULL,
    PRIMARY KEY (MemberID),
    UNIQUE KEY uq_email (Email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# ── helpers ────────────────────────────────────────────────────────────────────

def connect_local():
    """Connect to the local primary database."""
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "scholarease"),
        )
        print(f"  ✓  Connected to LOCAL db  ({os.getenv('DB_NAME')})")
        return conn
    except mysql.connector.Error as e:
        print(f"  ✗  Local DB connection failed: {e}")
        sys.exit(1)


def connect_shard(shard_id: int):
    """Connect to a specific shard server."""
    port = SHARD_PORTS[shard_id]
    try:
        conn = mysql.connector.connect(
            host=SHARD_HOST,
            port=port,
            user=SHARD_USER,
            password=SHARD_PASSWORD,
            database=SHARD_DB,
            connection_timeout=10,
        )
        print(f"  ✓  Connected to SHARD {shard_id}  ({SHARD_HOST}:{port})")
        return conn
    except mysql.connector.Error as e:
        print(f"  ✗  Shard {shard_id} ({SHARD_HOST}:{port}) connection failed: {e}")
        sys.exit(1)


def get_shard_index(member_id: int) -> int:
    return member_id % 3


# ── step 1: create shard tables ───────────────────────────────────────────────

def create_shard_tables(shard_conns: dict):
    print("\n[STEP 1] Creating shard tables on each shard server...")
    for shard_id, conn in shard_conns.items():
        cursor = conn.cursor()
        sql = CREATE_SHARD_TABLE_SQL.format(shard_id=shard_id)
        cursor.execute(sql)
        conn.commit()
        cursor.close()
        print(f"  ✓  shard_{shard_id}_member  created (or already exists) on port {SHARD_PORTS[shard_id]}")


# ── step 2: migrate data ───────────────────────────────────────────────────────

def migrate_data(local_conn, shard_conns: dict):
    print("\n[STEP 2] Reading records from local `member` table...")

    cursor = local_conn.cursor()
    cursor.execute("SELECT MemberID, Name, Email, PhoneNo, Age, Role FROM member")
    rows = cursor.fetchall()
    cursor.close()

    total = len(rows)
    print(f"  Total records found: {total}")

    if total == 0:
        print("  ⚠  No records in local `member` table. Nothing to migrate.")
        return total, {0: 0, 1: 0, 2: 0}

    print(f"\n[STEP 2] Migrating {total} records across 3 shards...")

    counts = {0: 0, 1: 0, 2: 0}
    shard_cursors = {i: shard_conns[i].cursor() for i in range(3)}

    for row in rows:
        member_id = row[0]
        shard_id  = get_shard_index(member_id)
        table     = f"shard_{shard_id}_member"

        shard_cursors[shard_id].execute(f"""
            INSERT IGNORE INTO {table}
                (MemberID, Name, Email, PhoneNo, Age, Role)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, row)

        # FIX: only count rows that were actually inserted
        # rowcount == 0 means INSERT IGNORE silently skipped a duplicate
        if shard_cursors[shard_id].rowcount > 0:
            counts[shard_id] += 1

    # commit all shards
    for shard_id, conn in shard_conns.items():
        conn.commit()
        shard_cursors[shard_id].close()

    print(f"\n  Records inserted per shard:")
    for shard_id in range(3):
        port = SHARD_PORTS[shard_id]
        print(f"    Shard {shard_id} (port {port})  →  shard_{shard_id}_member  :  {counts[shard_id]} records")

    return total, counts


# ── step 3: validate ───────────────────────────────────────────────────────────

def validate(shard_conns: dict, original_total: int, counts: dict):
    print("\n[STEP 3] Validating migration across all shard servers...")

    all_ids = []

    for shard_id, conn in shard_conns.items():
        table  = f"shard_{shard_id}_member"
        cursor = conn.cursor()
        cursor.execute(f"SELECT MemberID FROM {table}")
        ids_in_shard = [r[0] for r in cursor.fetchall()]
        cursor.close()

        all_ids.extend(ids_in_shard)

        # placement check
        wrong = [mid for mid in ids_in_shard if mid % 3 != shard_id]
        if wrong:
            print(f"  ✗  Shard {shard_id}: WRONG records found → MemberIDs {wrong}")
        else:
            print(f"  ✓  Shard {shard_id} (port {SHARD_PORTS[shard_id]}): "
                  f"{len(ids_in_shard)} records, all correctly placed")

    # duplicate check
    if len(all_ids) != len(set(all_ids)):
        dupes = len(all_ids) - len(set(all_ids))
        print(f"\n  ✗  {dupes} DUPLICATE record(s) detected across shards!")
    else:
        print(f"\n  ✓  No duplicates across shards")

    # count check — uses actual live DB counts, not in-memory counts
    if len(all_ids) == original_total:
        print(f"  ✓  Count check passed: {original_total} original == {len(all_ids)} in shards")
    else:
        diff = original_total - len(all_ids)
        print(f"  ✗  Count MISMATCH  –  original={original_total}, in shards={len(all_ids)}, missing={diff}")

    # distribution summary
    print(f"\n  Distribution summary:")
    for shard_id in range(3):
        n   = counts[shard_id]
        pct = (n / original_total * 100) if original_total else 0
        bar = "█" * int(pct / 2)
        print(f"    Shard {shard_id} → shard_{shard_id}_member : {n:>5} records  ({pct:.1f}%)  {bar}")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  ScholarEase – Shard Migration  |  Team: DataForge")
    print(f"  Shards: {SHARD_HOST}  ports 3307 / 3308 / 3309")
    print("=" * 65)

    # connect
    print("\n[CONNECTING]")
    local_conn  = connect_local()
    shard_conns = {i: connect_shard(i) for i in range(3)}

    # run steps
    create_shard_tables(shard_conns)
    original_total, counts = migrate_data(local_conn, shard_conns)
    validate(shard_conns, original_total, counts)

    # close all
    local_conn.close()
    for conn in shard_conns.values():
        conn.close()

    print("\n" + "=" * 65)
    print("  Migration complete.")
    print("=" * 65)


if __name__ == "__main__":
    main()