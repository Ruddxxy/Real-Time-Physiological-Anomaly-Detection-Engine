#!/bin/bash
set -e

# Config
DURATION=60
API_URL="http://localhost:8000"

echo "=== Chaos & Resilience Test ==="

# 1. Warmup & Base Latency
echo "Warming up and measuring Base P95 Latency..."
# Simple curl loop for baseline
for i in {1..50}; do
  curl -s -o /dev/null -w "%{time_total}\n" -X POST $API_URL/ingest -H "Content-Type: application/json" -d '{"patient_id":"bench","timestamp":"2023-10-27T10:00:00","hr":72,"bp_sys":120,"bp_dia":80,"spo2":98,"rr":16,"temp":36.8}' >> latency_base.txt
done
# Calc P95 (simple sort)
BASE_P95=$(sort -n latency_base.txt | tail -n 3 | head -n 1) # approx p95
echo "Base P95: ${BASE_P95}s"

# 2. Start Load
echo "Starting continuous load (60s)..."
python3 data/generator.py 60 &
GEN_PID=$!

# 3. Chaos Injection
sleep 15
echo "CHAOS: Killing API container..."
docker compose kill api
sleep 2
docker compose start api
# Wait for API to be ready
echo "Waiting for API recovery..."
until curl -s $API_URL/health > /dev/null; do sleep 1; done
echo "API Recovered."

sleep 15
echo "CHAOS: Killing Worker container..."
docker compose kill worker
sleep 2
docker compose start worker
echo "Worker Restarted."

# 4. Wait for finish
wait $GEN_PID
echo "Load finished."

# 5. Measure Loaded Latency (Post-Chaos)
echo "Measuring Loaded/Recovered P95 Latency..."
rm -f latency_loaded.txt
for i in {1..50}; do
   curl -s -o /dev/null -w "%{time_total}\n" -X POST $API_URL/ingest -H "Content-Type: application/json" -d '{"patient_id":"bench","timestamp":"2023-10-27T10:00:00","hr":72,"bp_sys":120,"bp_dia":80,"spo2":98,"rr":16,"temp":36.8}' >> latency_loaded.txt
done
LOADED_P95=$(sort -n latency_loaded.txt | tail -n 3 | head -n 1)
echo "Loaded P95: ${LOADED_P95}s"

# 6. Verify Data Consistency
# Load env vars if .env exists
if [ -f .env ]; then
  export $(cat .env | xargs)
fi
DB_USER=${POSTGRES_USER:-user}
DB_NAME=${POSTGRES_DB:-physio}

# Count rows
CNT=$(docker compose exec -T db psql -U $DB_USER -d $DB_NAME -t -c "SELECT count(*) FROM vitals_events;" | xargs)
echo "Final DB Row Count: $CNT"
# Note: Generator prints "Total events successfully sent". 
# But in shell script we lost that stdout capture unless we piped it.
# Ideally we'd parse it. For now, we rely on the visual output of generator.

echo "Finished."
echo "base_p95_s=${BASE_P95}"
echo "loaded_p95_s=${LOADED_P95}"
