# ScholarEase – Scholarship Management System
### CS 432 – Databases | Assignment 4: Sharding
**Team DataForge | IIT Gandhinagar | Semester II (2025–2026)**

## Project Overview

ScholarEase is a scholarship management system that allows students to apply for scholarships, authorities to verify applications, and admins to manage members. This version (Assignment 4) extends the system with **horizontal sharding** of the `member` table across three simulated Docker nodes.

---

## Sharding Architecture

| Property | Value |
|---|---|
| Shard Key | `MemberID` |
| Strategy | Hash-based: `shard_id = MemberID % 3` |
| Number of Shards | 3 |
| Shard Host | `10.0.116.184` (IITGN Server) |
| Shard 0 | Port `3307` → `shard_0_member` |
| Shard 1 | Port `3308` → `shard_1_member` |
| Shard 2 | Port `3309` → `shard_2_member` |

Each shard runs as an independent Docker container with its own MySQL instance. All routing logic is centralised in `Module_B/app/utils/shard_utils.py`.

---

## Repository Structure

```
ScholarEase-DBMS-A4/
│
├── migrate_shards.py           # Shard migration script (3-step: create, migrate, validate)
│
├── Module_A/                   # Custom B+ Tree DB engine (Assignment 1)
│   ├── main.py
│   ├── database/
│   │   ├── bplustree.py
│   │   ├── bruteforce.py
│   │   ├── db_manager.py
│   │   └── table.py
│   └── transaction/
│       └── transaction_manager.py
│
└── Module_B/                   # FastAPI application (Assignments 2, 3, 4)
    ├── app/
    │   ├── main.py             # FastAPI app entry point
    │   ├── auth.py             # Session-based authentication
    │   ├── db.py               # Primary DB + shard DB connections
    │   ├── routes/
    │   │   ├── auth_routes.py
    │   │   ├── member_routes.py        # All shard-aware member routing
    │   │   ├── scholarship_routes.py
    │   │   └── payment_routes.py
    │   ├── utils/
    │   │   ├── shard_utils.py          # Core shard routing logic
    │   │   └── logger.py
    │   └── static/
    │       └── api.js
    ├── templates/              # HTML templates
    ├── sql/
    │   └── indexes.sql
    ├── test_system.py
    ├── test_api_acid.py
    ├── test_race_condition.py
    ├── concurrency_tests.py
    └── locustfile.py
```

---

## Setup and Installation

### Prerequisites
- Python 3.10+
- MySQL running locally
- Access to IITGN network or VPN (for shard containers)

### 1. Clone the repository
```bash
git clone https://github.com/DataForge/ScholarEase-DBMS-A4.git
cd ScholarEase-DBMS-A4
```

### 2. Install dependencies
```bash
pip install fastapi uvicorn mysql-connector-python python-dotenv
```

### 3. Create the `.env` file
Create a `.env` file inside the `Module_B/` directory:
```
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=yourpassword
DB_NAME=scholarease
```

SHARD_HOST=10.0.116.184
SHARD_USER=DataForge
SHARD_PASSWORD=your_shard_password
SHARD_DB=DataForge
SHARD_PORT_0=3307
SHARD_PORT_1=3308
SHARD_PORT_2=3309

> Shard containers are hosted on the IITGN server. You must be on the IITGN campus network or VPN to reach them.
---

## Running the Application

```bash
cd Module_B
uvicorn app.main:app --reload --port 8000
```

Visit `http://127.0.0.1:8000/docs` to access the interactive API documentation.

---

## Running the Shard Migration

> Requires IITGN network access (on-campus or VPN).

From the project root:
```bash
python migrate_shards.py
```

This performs three steps automatically:
1. Creates `shard_0_member`, `shard_1_member`, `shard_2_member` on each Docker node
2. Migrates all records from the primary `member` table into the correct shard
3. Validates placement correctness, no duplicates, and count integrity

---

## API Endpoints

| Method | Endpoint | Routing Behaviour |
|---|---|---|
| `POST` | `/login` | Authenticates user; creates session in primary DB |
| `GET` | `/profile` | Student: single shard lookup. Admin/Authority: fan-out across all 3 shards |
| `POST` | `/member` | Two-phase write: primary (get ID) → correct shard |
| `GET` | `/member/{id}` | Single-key lookup on exactly one shard |
| `DELETE` | `/member/{id}` | Delete from correct shard + primary |
| `GET` | `/members/range` | Fan-out across all 3 shards; merge and sort by MemberID |
