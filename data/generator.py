import random
import time
import random
import time
from datetime import datetime, timedelta, timezone
import requests
import json
import logging
import sys
import requests
import json
import logging
import sys

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger("generator")

# Configuration
API_URL = "http://localhost:8000/ingest"

class PatientSimulator:
    def __init__(self, patient_id):
        self.patient_id = patient_id
        # Baselines
        self.hr = 75
        self.bp_sys = 120
        self.bp_dia = 80
        self.spo2 = 98
        self.rr = 16
        self.temp = 37.0
        
        # Injection
        self.anomaly_active = False
        self.anomaly_start_time = None
        self.anomaly_type = None
        
    def _random_walk(self, val, min_val, max_val, step=1):
        delta = random.uniform(-step, step)
        new_val = val + delta
        return max(min_val, min(max_val, new_val))

    def generate_reading(self, force_anomaly=None, timestamp_override=None):
        if timestamp_override:
            # For backfilling or training data generation
            timestamp = timestamp_override
        else:
            timestamp = datetime.now(timezone.utc)
            
        # Drift logic
        if self.anomaly_active:
             # Deteriorate
            if self.anomaly_type == "spike":
                self.hr += 2 # Fast rise
            elif self.anomaly_type == "drop":
                self.spo2 -= 0.5 # Slow drop
            elif self.anomaly_type == "drift":
                 # Gradual deterioration of all signs (Shock pattern)
                 # HR Up, BP Down
                 self.hr += 0.5
                 self.bp_sys -= 0.5
                 self.bp_dia -= 0.3
        else:
            # Normal walk
            self.hr = self._random_walk(self.hr, 40, 180, step=2)
            self.bp_sys = self._random_walk(self.bp_sys, 80, 200, step=2)
            self.bp_dia = self._random_walk(self.bp_dia, 50, 120, step=1)
            self.spo2 = self._random_walk(self.spo2, 85, 100, step=0.5)
            self.rr = self._random_walk(self.rr, 8, 40, step=1)
            self.temp = self._random_walk(self.temp, 35.5, 40.0, step=0.1)
        
        # Force single point anomaly
        hr_out = int(self.hr)
        spo2_out = int(self.spo2)
        
        if force_anomaly == "spike":
            hr_out += 50
        elif force_anomaly == "drop":
            spo2_out = 80

        # Create payload
        return {
            "patient_id": self.patient_id,
            "timestamp": timestamp.isoformat(),
            "hr": hr_out,
            "bp_sys": int(self.bp_sys),
            "bp_dia": int(self.bp_dia),
            "spo2": spo2_out,
            "rr": int(self.rr),
            "temp": round(self.temp, 1)
        }
        
    def start_anomaly(self, type="spike"):
        self.anomaly_active = True
        self.anomaly_type = type
        self.anomaly_start_time = datetime.now(timezone.utc)
        logger.info(f"ANOMALY_INJECTED patient_id={self.patient_id} type={type} timestamp={self.anomaly_start_time.isoformat()}")

    def stop_anomaly(self):
        self.anomaly_active = False
        self.anomaly_type = None

def generate_training_data(n_samples=1000):
        self.anomaly_active = False
        self.anomaly_type = None

def generate_training_data(n_samples=1000):
    """Generate raw samples for training."""
    sim = PatientSimulator("train")
    data = []
    labels = [] # 1 normal, -1 anomaly
    
    for _ in range(n_samples):
        # 5% chance of anomaly in training data? or pure?
        # Isolation forest needs mostly pure.
        reading = sim.generate_reading()
        vector = [
            reading['hr'],
            reading['bp_sys'],
            reading['bp_dia'],
            reading['spo2'],
            reading['rr'],
            reading['temp']
        ]
        data.append(vector)
        labels.append(1) 
    return data, labels

def run_load_test(patients=3, duration_s=60, rate_limit_sleep=1.0):
    print(f"Starting generator with {patients} patients for {duration_s}s...")
    sims = [PatientSimulator(f"p-{i}") for i in range(1, patients + 1)]
    
    start_time = time.time()
    events_sent = 0
    
    try:
        while time.time() - start_time < duration_s:
            for sim in sims:
                # Random anomaly injection
                if not sim.anomaly_active and random.random() < 0.01:
                    sim.start_anomaly("spike" if random.random() > 0.5 else "drop")
                elif sim.anomaly_active and (datetime.now(timezone.utc) - sim.anomaly_start_time).total_seconds() > 20:
                    sim.stop_anomaly()
                
                data = sim.generate_reading()
                try:
                    resp = requests.post(API_URL, json=data, timeout=2)
                    if resp.status_code in [200, 202]:
                        events_sent += 1
                        if events_sent % 10 == 0:
                            sys.stdout.write(f"\rEvents sent: {events_sent}")
                            sys.stdout.flush()
                    elif resp.status_code == 429:
                        pass # Rate limit hit
                    else:
                        print(f" Error: {resp.status_code}")
                except Exception as e:
                    print(f" Request Failed: {e}")
            
            time.sleep(rate_limit_sleep)
            
    except KeyboardInterrupt:
        pass
    
    print(f"\nTotal events successfully sent: {events_sent}")
    return events_sent

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        pass # Imported by train.py
    else:
        # Default run
        duration = 60
        if len(sys.argv) > 1:
            try:
                duration = int(sys.argv[1])
            except: pass
        
        run_load_test(duration_s=duration)
