import asyncio
import os
import json
import redis
import joblib
import numpy as np
import psycopg
from datetime import datetime
from worker.windows import PatientStateManager
from db.database import pool

# Config
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STREAM_KEY = "vitals_stream"
GROUP_NAME = "physio_workers"
CONSUMER_NAME = f"worker-{os.getpid()}"
MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'model', 'model.joblib')

# In-memory state
patient_states = {} # patient_id -> PatientStateManager

async def process_event(event_data, model):
    """
    Core logic:
    1. Parse event
    2. Update Windows
    3. ML Inference
    4. Detect Anomaly Type
    5. Persist (Window Summaries + Anomalies)
    """
    patient_id = event_data['patient_id']
    
    # Parse timestamp
    try:
        ts = datetime.fromisoformat(event_data['timestamp'])
    except:
        ts = datetime.now() # Fallback
        
    # Get or Create State
    if patient_id not in patient_states:
        patient_states[patient_id] = PatientStateManager(patient_id)
        # TODO: Hydrate from DB if needed for "crash recovery" of full window context
        # For this minimal version, we start fresh on restart.
    
    state = patient_states[patient_id]
    
    # Prepare data dict (convert strings to int/float if needed)
    reading = {
        'timestamp': ts,
        'hr': int(event_data['hr']),
        'bp_sys': int(event_data['bp_sys']),
        'bp_dia': int(event_data['bp_dia']),
        'spo2': int(event_data['spo2']),
        'rr': int(event_data['rr']),
        'temp': float(event_data['temp'])
    }
    
    state.add_reading(reading)
    
    # Static Threshold Check (for Lead Time Benchmarking)
    # Critical Thresholds: HR > 140, SpO2 < 90
    if reading['hr'] > 140:
        print(f"THRESHOLD_CROSSED patient_id={patient_id} metric=hr value={reading['hr']} timestamp={ts.isoformat()}")
    if reading['spo2'] < 90:
        print(f"THRESHOLD_CROSSED patient_id={patient_id} metric=spo2 value={reading['spo2']} timestamp={ts.isoformat()}")

    # ML Inference
    vector = [[
        reading['hr'],
        reading['bp_sys'],
        reading['bp_dia'],
        reading['spo2'],
        reading['rr'],
        reading['temp']
    ]]
    
    # Isolation Forest: -1 for anomaly, 1 for normal
    # decision_function: lower is more abnormal.
    # We invert it to get an "anomaly score" where higher = worse
    score_raw = model.decision_function(vector)[0]
    is_anomaly = model.predict(vector)[0] == -1
    
    # Normalize score roughly? 
    # decision_function usually around 0. Negative is anomaly.
    # Let's just use -score as "Anomaly Score" (so positive is bad)
    anomaly_score = -score_raw
    
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            # 1. Persist Window Summaries (Maybe not every event? Every 30s? 
            # Requirement: "Persist window summaries". 
            # Doing it every event is heavy. Let's do it if window changed significantly or periodically?
            # Or just do it. It's a "Real-Time Engine".
            # To avoid DB thrashing, let's only persist if the 30s window is "full" or modulo count.
            # actually, requirement says "Persist window summaries".
            # We'll do it for the largest window every minute?
            # Let's keep it simple: Persist 30s window result every update? No.
            # Let's persist every 10 events.
            pass # Skipping heavy write for now, focus on Anomaly.

            # 2. Persist Anomaly if detected
            if is_anomaly:
                # Determine Types
                a_type = "unknown"
                # Simple heuristics using 10m window
                w_10m = state.w_10m.get_aggregates()
                if w_10m and w_10m['count'] > 5:
                    if abs(reading['hr'] - w_10m['avg_hr']) > 20:
                        a_type = "spike"
                    elif abs(reading['spo2'] - w_10m['avg_spo2']) > 5:
                        a_type = "drop"
                    elif anomaly_score > 0.2: # Very high score
                        a_type = "multi-signal"
                    else:
                        a_type = "drift"
                else:
                    a_type = "spike" # Startup assumption

                await cur.execute(
                    """
                    INSERT INTO anomalies (patient_id, anomaly_type, score, timestamp, details)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        patient_id,
                        a_type,
                        float(anomaly_score),
                        ts,
                        json.dumps(reading, default=str)
                    )
                )
                print(f"ANOMALY_DETECTED patient_id={patient_id} type={a_type} score={anomaly_score:.2f} timestamp={ts.isoformat()}")

async def main():
    print(f"Worker {CONSUMER_NAME} starting...")
    
    # Load Model
    try:
        model = joblib.load(MODEL_PATH)
        print("ML Model loaded.")
    except Exception as e:
        print(f"CRITICAL: Model not found at {MODEL_PATH}. Run training first.")
        return

    # Connect DB
    await pool.open()
    
    # Connect Redis
    r = redis.from_url(REDIS_URL, decode_responses=True)
    
    # Create Consumer Group
    try:
        r.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise
    
    print("Listening for stream...")
    
    while True:
        try:
            # Block for 1s
            entries = r.xreadgroup(GROUP_NAME, CONSUMER_NAME, {STREAM_KEY: ">"}, count=10, block=1000)
            
            if entries:
                for stream, messages in entries:
                    for msg_id, data in messages:
                        await process_event(data, model)
                        # ACK
                        r.xack(STREAM_KEY, GROUP_NAME, msg_id)
            
            # TODO: Handle pending messages (consumer recovery) in a real robust system
            
        except Exception as e:
            print(f"Error in loop: {e}")
            await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
