import subprocess
import time
import requests
import psycopg
import sys
import os

# Config
DB_USER = os.getenv("POSTGRES_USER", "user")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "password")
DB_NAME = os.getenv("POSTGRES_DB", "physio")
DB_HOST = os.getenv("WN_DB_HOST", "localhost")
DB_PORT = os.getenv("WN_DB_PORT", "5433")

DB_DSN = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
GENERATOR_CMD = ["python3", "data/generator.py", "30"] # Run for 30s

def get_db_count():
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM vitals_events")
                return cur.fetchone()[0]
    except Exception as e:
        print(f"DB Error: {e}")
        return 0

def clean_db():
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE vitals_events CASCADE")
                cur.execute("TRUNCATE anomalies CASCADE")
    except Exception as e:
        print(f"DB Clean Error: {e}")

def main():
    print("=== Idempotency & Integrity Test ===")
    
    # 1. Clean DB
    clean_db()
    print("DB Cleaned.")
    
    # 2. Start Generator in background
    print("Starting Generator (30s)...")
    gen_process = subprocess.Popen(GENERATOR_CMD, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # 3. Wait 10s then kill Worker
    time.sleep(10)
    print("Killing Worker container...")
    subprocess.run(["docker", "compose", "stop", "worker"], check=True)
    
    # 4. Wait 5s
    time.sleep(5)
    
    # 5. Restart Worker
    print("Restarting Worker container...")
    subprocess.run(["docker", "compose", "start", "worker"], check=True)
    
    # 6. Wait for generator to finish
    stdout, stderr = gen_process.communicate()
    
    # Parse sent count from stdout
    # "Total events successfully sent: <N>"
    sent_events = 0
    for line in stdout.splitlines():
        if "Total events successfully sent:" in line:
            sent_events = int(line.split(":")[1].strip())
    
    print(f"Generator finished. Sent: {sent_events}")
    
    # 7. Wait for worker to catch up (drain stream)
    print("Waiting for worker to drain stream (10s)...")
    time.sleep(10)
    
    # 8. Verify
    stored_events = get_db_count()
    print(f"Stored in DB: {stored_events}")
    
    # Check duplicates query
    duplicates = 0
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT patient_id, timestamp, count(*) 
                FROM vitals_events 
                GROUP BY patient_id, timestamp 
                HAVING count(*) > 1
            """)
            duplicates = len(cur.fetchall())
    
    print(f"Duplicates found: {duplicates}")
    
    # Assertions
    # Note: If valid requests were rejected by API (e.g. 503 during some restart?), sent_events might be higher than stored.
    # But generator only counts successful 202s.
    # However, if API crashed, generator would fail. Here we only crashed Worker.
    # So valid 202s -> Redis -> Worker -> DB.
    # If Worker was down, Redis held them. Worker restart -> Process.
    # Stored should equal Sent.
    
    diff = abs(sent_events - stored_events)
    if diff == 0 and duplicates == 0:
        print("SUCCESS: Integrity Verified.")
        sys.exit(0)
    else:
        print(f"FAILURE: Mismatch (Diff={diff}) or Duplicates ({duplicates})")
        sys.exit(1)

if __name__ == "__main__":
    main()
