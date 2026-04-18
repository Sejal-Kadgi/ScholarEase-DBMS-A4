"""
shard_utils.py  –  ScholarEase  |  Assignment 4
------------------------------------------------
Central routing logic. All application code imports from here.

Strategy: Hash-based partitioning
    shard_index = MemberID % 3

Shard → Docker port mapping:
    shard 0  →  port 3307
    shard 1  →  port 3308
    shard 2  →  port 3309
"""

NUM_SHARDS = 3


def get_shard_index(member_id: int) -> int:
    """Returns the shard index (0, 1, or 2) for a given MemberID."""
    return member_id % NUM_SHARDS


def get_shard_table(member_id: int) -> str:
    """
    Returns the shard table name for a given MemberID.

    Examples:
        MemberID = 1  →  shard_1_member
        MemberID = 2  →  shard_2_member
        MemberID = 3  →  shard_0_member
    """
    return f"shard_{get_shard_index(member_id)}_member"


def all_shard_tables() -> list:
    """Returns all three shard table names. Used for range / fan-out queries."""
    return [f"shard_{i}_member" for i in range(NUM_SHARDS)]


def all_shard_indices() -> list:
    """Returns [0, 1, 2]. Used to iterate over shard DB connections."""
    return list(range(NUM_SHARDS))