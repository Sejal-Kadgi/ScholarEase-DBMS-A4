"""
db.py  –  ScholarEase  |  Assignment 4
---------------------------------------
Provides connections to:
  - The PRIMARY (local) database  →  get_db()
  - A specific shard by index     →  get_shard_db(shard_index)
  - All three shards              →  get_all_shard_dbs()

Shard layout (Docker instances, IITGN network):
  Shard 0  →  port 3307   (MemberID % 3 == 0)
  Shard 1  →  port 3308   (MemberID % 3 == 1)
  Shard 2  →  port 3309   (MemberID % 3 == 2)
"""

import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

# ── shard connection config ────────────────────────────────────────────────────

SHARD_HOST     = os.getenv("SHARD_HOST")
SHARD_USER     = os.getenv("SHARD_USER")
SHARD_PASSWORD = os.getenv("SHARD_PASSWORD")
SHARD_DB       = os.getenv("SHARD_DB")

print("SHARD_HOST:", SHARD_HOST)

SHARD_PORTS = {
    0: 3307,
    1: 3308,
    2: 3309,
}


# ── primary db (original, unchanged) ──────────────────────────────────────────

def get_db():
    """Returns a connection to the primary local database."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )


# ── shard connections ──────────────────────────────────────────────────────────

def get_shard_db(shard_index: int):
    """
    Returns a live MySQL connection to the specified shard (0, 1, or 2).
    Each shard is a separate Docker container on the IITGN network.
    """
    if shard_index not in SHARD_PORTS:
        raise ValueError(f"Invalid shard index: {shard_index}. Must be 0, 1, or 2.")

    return mysql.connector.connect(
        host=SHARD_HOST,
        port=SHARD_PORTS[shard_index],
        user=SHARD_USER,
        password=SHARD_PASSWORD,
        database=SHARD_DB,
    )


def get_all_shard_dbs():
    """
    Returns a dict of {shard_index: connection} for all three shards.
    Used for range queries that must fan-out across every shard.
    Remember to close each connection after use.
    """
    return {i: get_shard_db(i) for i in range(3)}