from collections import deque
from datetime import datetime
import numpy as np

class SlidingWindow:
    def __init__(self, size_seconds):
        self.size_seconds = size_seconds
        self.events = deque() # List of (timestamp, value_dict)
    
    def add_event(self, timestamp: datetime, data: dict):
        self.events.append((timestamp, data))
        self._prune(timestamp)
        
    def _prune(self, current_time: datetime):
        cutoff = current_time.timestamp() - self.size_seconds
        while self.events and self.events[0][0].timestamp() < cutoff:
            self.events.popleft()
            
    def get_aggregates(self):
        if not self.events:
            return None
        
        # Calculate stats for numeric fields
        count = len(self.events)
        
        # We focus on a few key metrics for summaries
        hrs = [e[1]['hr'] for e in self.events]
        spo2s = [e[1]['spo2'] for e in self.events]
        temps = [e[1]['temp'] for e in self.events]
        
        return {
            "window_size_s": self.size_seconds,
            "count": count,
            "end_time": self.events[-1][0],
            "avg_hr": round(float(np.mean(hrs)), 2),
            "avg_spo2": round(float(np.mean(spo2s)), 2),
            "avg_temp": round(float(np.mean(temps)), 2)
        }

class PatientStateManager:
    """Manages windows for a single patient."""
    def __init__(self, patient_id):
        self.patient_id = patient_id
        # Windows: 30s, 2m, 10m
        self.w_30s = SlidingWindow(30)
        self.w_2m = SlidingWindow(120)
        self.w_10m = SlidingWindow(600)
    
    def add_reading(self, reading: dict):
        # Expects reading to have 'timestamp' (datetime obj) and values
        ts = reading['timestamp']
        self.w_30s.add_event(ts, reading)
        self.w_2m.add_event(ts, reading)
        self.w_10m.add_event(ts, reading)
    
    def get_summaries(self):
        return [
            self.w_30s.get_aggregates(),
            self.w_2m.get_aggregates(),
            self.w_10m.get_aggregates()
        ]
