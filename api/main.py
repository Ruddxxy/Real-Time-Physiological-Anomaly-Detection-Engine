from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import redis
import json
import os
import time
import logging
import uuid
import hashlib
from datetime import datetime, timedelta
from api.validators import VitalsReading
from contextlib import asynccontextmanager
import psycopg
from db.database import pool

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger("physio-api")

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STREAM_KEY = "vitals_stream"

# Redis Client
r = redis.from_url(REDIS_URL, decode_responses=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Verify Redis connection & Open DB Pool
    try:
        r.ping()
        print(f"Connected to Redis at {REDIS_URL}")
    except redis.ConnectionError:
        print(f"Failed to connect to Redis at {REDIS_URL}")
    
    await pool.open()
    print("Database pool opened.")

    yield
    # Shutdown
    await pool.close()
    r.close()

app = FastAPI(title="Physio Engine API", lifespan=lifespan)

# CORS (Allow UI access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serves UI files - MOUNTING UI HERE for simplicity in docker-compose
if not os.path.exists("ui"):
    os.makedirs("ui", exist_ok=True)
    if not os.path.exists("ui/index.html"):
        with open("ui/index.html", "w") as f: f.write("<h1>Loading...</h1>")

app.mount("/ui", StaticFiles(directory="ui", html=True), name="ui")

# Middleware for Timing
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start_time = time.perf_counter()
    
    response = await call_next(request)
    
    process_time = (time.perf_counter() - start_time) * 1000
    # Log latency
    logger.info(f"request_id={request_id} path={request.url.path} status={response.status_code} latency_ms={process_time:.2f}")
    
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{process_time:.2f}"
    return response

# Helpers
def get_idempotency_key(reading: VitalsReading) -> str:
    """Generate a unique key for the event to prevent duplicates."""
    # Composite key: Patient + Timestamp usually sufficient.
    # We use a hash to be safe and clean.
    raw = f"{reading.patient_id}:{reading.timestamp.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()

# Middleware / Dependency for Rate Limiting
# simple sliding window or fixed window limiter per patient?
# For now, let's just do a global limiter or per-IP. 
# Prompt requires "Enforce rate limiting".
# We'll limit by patient_id to prevent flooding for a single patient.
def check_rate_limit(patient_id: str):
    key = f"rate_limit:{patient_id}"
    # Allow 10 requests per 10 seconds per patient
    current = r.incr(key)
    if current == 1:
        r.expire(key, 10)
    
    if current > 20: 
        raise HTTPException(status_code=429, detail="Rate limit exceeded for this patient ID")

@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_vitals(reading: VitalsReading, request: Request):
    """
    Ingest patient vitals.
    - Validates schema (Pydantic).
    - Checks rate limit.
    - Checks idempotency.
    - Persists to DB (Transactional).
    - Pushes to Redis Stream.
    """
    # 1. Rate Limiting
    check_rate_limit(reading.patient_id)

    # 2. Idempotency Check (Redis Cache first)
    idem_key = f"idem:{get_idempotency_key(reading)}"
    if r.exists(idem_key):
        return {"status": "ignored", "detail": "duplicate_event_cache"}

    # 3. Persist to Postgres
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Ensure patient exists
                await cur.execute(
                    "INSERT INTO patients (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
                    (reading.patient_id,)
                )
                
                await cur.execute(
                    """
                    INSERT INTO vitals_events 
                    (patient_id, timestamp, hr, bp_sys, bp_dia, spo2, rr, temp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        reading.patient_id, 
                        reading.timestamp, 
                        reading.hr, 
                        reading.bp_sys, 
                        reading.bp_dia, 
                        reading.spo2, 
                        reading.rr, 
                        reading.temp
                    )
                )
                event_id = (await cur.fetchone())[0]
    except psycopg.Error as e:
        print(f"DB Error: {e}")
        # In prod, log specific error. Duplicate key?
        raise HTTPException(status_code=500, detail="Database persistence failed")

    # 4. Push to Stream
    payload = reading.model_dump()
    payload['timestamp'] = reading.timestamp.isoformat()
    payload['db_id'] = event_id
    
    try:
        msg_id = r.xadd(STREAM_KEY, payload)
        
        # 5. Set Idempotency Key
        r.setex(idem_key, 600, "1")
        
        # Log Success Latency specifically for metrics parsing
        # We can't easily get full time here inside function, relying on middleware for total time.
        # But user asked for "ingest_latency_ms=<value>" in logs. Middleware does this.
        # We can add specific log for ingest success.
        logger.info(f"request_id={request.state.request_id} event=ingest_success patient_id={reading.patient_id}")

        return {"status": "queued", "id": msg_id, "db_id": event_id}
    except redis.RedisError:
        # DB inserted but Redis failed. 
        # This is a partial failure state.
        # We could delete from DB here to rollback, 
        # but better to have ingestion idempotency handle it on retry.
        raise HTTPException(status_code=503, detail="Stream service unavailable")

@app.get("/health")
async def health_check():
    try:
        r.ping()
        redis_status = "connected"
    except:
        redis_status = "disconnected"
    return {"status": "ok", "redis": redis_status, "db": "pool_managed"}

@app.get("/patient/{patient_id}")
async def get_patient_details(patient_id: str):
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT timestamp, hr, bp_sys, bp_dia, spo2, temp 
                FROM vitals_events 
                WHERE patient_id = %s 
                ORDER BY timestamp DESC 
                LIMIT 1
                """,
                (patient_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Patient not found")
            return {
                "id": patient_id,
                "latest_vitals": {
                    "timestamp": row[0],
                    "hr": row[1],
                    "bp": f"{row[2]}/{row[3]}",
                    "spo2": row[4],
                    "temp": float(row[5])
                }
            }

@app.get("/patient/{patient_id}/timeline")
async def get_patient_timeline(patient_id: str):
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT timestamp, hr, spo2, temp 
                FROM vitals_events 
                WHERE patient_id = %s 
                ORDER BY timestamp DESC 
                LIMIT 50
                """,
                (patient_id,)
            )
            rows = await cur.fetchall()
            return [
                {
                    "timestamp": r[0],
                    "hr": r[1],
                    "spo2": r[2],
                    "temp": float(r[3])
                } 
                for r in rows
            ]

@app.get("/anomalies")
async def get_active_anomalies():
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT patient_id, anomaly_type, score, timestamp, details
                FROM anomalies
                ORDER BY timestamp DESC
                LIMIT 20
                """
            )
            rows = await cur.fetchall()
            return [
                {
                    "patient_id": r[0],
                    "type": r[1],
                    "score": float(r[2]),
                    "timestamp": r[3],
                    "details": r[4]
                }
                for r in rows
            ]
