"""
Module B — locustfile.py
========================
Locust stress test for the ScholarEase FastAPI API.

Covers (from PDF + evaluator update):
  ✓ Stress testing — hundreds/thousands of requests
  ✓ Observe performance under load
  ✓ Check correctness and response time

Install:
    pip install locust

Run (headless, 100 users, 10/sec spawn, 60s duration):
    locust -f Module_B/locustfile.py --headless -u 100 -r 10 -t 60s \
           --host http://127.0.0.1:8000 \
           --html Module_B/locust_report.html

Run (interactive web UI at http://localhost:8089):
    locust -f Module_B/locustfile.py --host http://127.0.0.1:8000

The --html flag saves a full HTML report with throughput, latency,
failures graphs — include this in your report PDF.
"""

from locust import HttpUser, task, between, events
import random
import time
import json

# ── Credentials ─────────────────────────────────────────────────────────────
ADMIN_CREDS   = {"email": "admin1@portal.com",  "password": "admin1123"}
STUDENT_CREDS = {"email": "rahul@gmail.com",    "password": "rahul123"}

SCHOLARSHIP_IDS = [1, 2, 3, 4, 5]   # must exist in your DB


# ── Base user class with login ────────────────────────────────────────────────

class ScholarEaseUser(HttpUser):
    """
    Simulates a generic ScholarEase user.
    Subclasses override credentials and task weights.
    """
    wait_time = between(0.5, 2)  # realistic think-time between requests
    abstract  = True
    _token    = None

    def on_start(self):
        """Login once at the start of each simulated user session."""
        resp = self.client.post("/login", json=self.CREDENTIALS,
                                name="/login")
        if resp.status_code == 200:
            self._token = resp.json().get("session_token")
        else:
            # If login fails, all subsequent requests will get 401 — visible in stats
            self._token = "invalid"

    def _auth(self):
        return {"Authorization": self._token}

    def on_stop(self):
        """No explicit logout endpoint — session expires by TTL."""
        pass


# ── Student user ─────────────────────────────────────────────────────────────

class StudentUser(ScholarEaseUser):
    """
    Simulates a student:
      - Reads scholarship list (frequent)
      - Reads own profile (frequent)
      - Submits a scholarship application (occasional)
    """
    CREDENTIALS = STUDENT_CREDS
    weight = 7   # 70% of virtual users are students

    @task(5)
    def view_scholarships(self):
        self.client.get("/scholarships", name="GET /scholarships",
                        headers=self._auth())

    @task(4)
    def view_profile(self):
        self.client.get("/profile", name="GET /profile",
                        headers=self._auth())

    @task(1)
    def apply_scholarship(self):
        """
        Try to apply for a scholarship.
        Multiple students applying concurrently tests race conditions
        at the DB level (unique constraint on StudentID+ScholarshipID).
        """
        sc_id = random.choice(SCHOLARSHIP_IDS)
        self.client.post(
            "/apply",
            json={"student_id": 1, "scholarship_id": sc_id},
            headers=self._auth(),
            name="POST /apply",
        )


# ── Admin user ───────────────────────────────────────────────────────────────

class AdminUser(ScholarEaseUser):
    """
    Simulates an admin:
      - Reads all profiles (frequent)
      - Verifies applications (occasional)
    """
    CREDENTIALS = ADMIN_CREDS
    weight = 3   # 30% of virtual users are admins

    @task(4)
    def view_all_profiles(self):
        self.client.get("/profile", name="GET /profile (admin)",
                        headers=self._auth())

    @task(2)
    def verify_application(self):
        """
        Verifying an application that may not exist is expected to
        return a non-200. Locust marks those as failures unless we
        tell it the response is acceptable — here we accept any status
        to measure throughput without false failure counts.
        """
        with self.client.put(
            "/verify",
            json={"application_id": random.randint(1, 20),
                  "status": "Approved",
                  "remarks": "Locust stress test verification"},
            headers=self._auth(),
            name="PUT /verify",
            catch_response=True,
        ) as resp:
            # Accept any response — we care about throughput, not correctness here
            resp.success()

    @task(1)
    def view_scholarships(self):
        self.client.get("/scholarships", name="GET /scholarships (admin)",
                        headers=self._auth())


# ── Spike test shape (optional — uncomment to use) ──────────────────────────
# from locust import LoadTestShape
#
# class SpikeShape(LoadTestShape):
#     """
#     Ramps to 100 users in 30s, holds for 60s, then drops to 10 for 30s.
#     Shows how the system recovers after a traffic spike.
#     """
#     stages = [
#         {"duration": 30,  "users": 100, "spawn_rate": 10},
#         {"duration": 90,  "users": 100, "spawn_rate": 10},
#         {"duration": 120, "users": 10,  "spawn_rate": 5},
#     ]
#
#     def tick(self):
#         run_time = self.get_run_time()
#         for stage in self.stages:
#             if run_time < stage["duration"]:
#                 return (stage["users"], stage["spawn_rate"])
#         return None