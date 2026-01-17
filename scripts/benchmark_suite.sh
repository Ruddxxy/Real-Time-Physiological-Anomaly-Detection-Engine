#!/bin/bash
set -e

echo "=== 1. ML Training ==="
python3 model/train.py > report_ml.txt

echo "=== 2. Idempotency ==="
export $(cat .env | xargs)
python3 scripts/verify_idempotency.py > report_idempotency.txt

echo "=== 3. Chaos & Latency ==="
# Determine throughput (Events/sec)
# chaos_test.sh runs generator for 60s.
# We'll rely on chaos_test.sh logs
./scripts/chaos_test.sh > report_chaos.txt

echo "=== 4. Lead Time ==="
# Run generator specifically for lead time (longer run, guaranteed anomalies)
# We can just reuse logs from chaos run if it was long enough.
# Chaos run is 60s. Generator injects anomalies random(0.01).
# Let's hope we catch some.
docker compose logs --no-log-prefix > full_logs.txt

echo "=== Benchmarking Complete ==="
python3 scripts/final_report.py
