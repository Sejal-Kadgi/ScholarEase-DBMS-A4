from datetime import datetime

def log_action(action):
    with open("logs/audit.log", "a") as f:
        f.write(f"[{datetime.now()}] {action}\n")