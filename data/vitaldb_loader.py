import vitaldb
import pandas as pd
import numpy as np
import time
import os
import requests
import logging
import concurrent.futures
from joblib import hash

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger("vitaldb_loader")

# Configuration
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)

# Track mapping
TRACKS = [
    'Solar8000/HR', 
    'Solar8000/ART_SBP', 
    'Solar8000/ART_DBP', 
    'Solar8000/PLETH_SPO2', 
    'Solar8000/RR_CO2',
    'Solar8000/BT' 
]

COL_MAP = {
    'Solar8000/HR': 'hr',
    'Solar8000/ART_SBP': 'bp_sys',
    'Solar8000/ART_DBP': 'bp_dia',
    'Solar8000/PLETH_SPO2': 'spo2',
    'Solar8000/RR_CO2': 'rr',
    'Solar8000/BT': 'temp'
}

class VitalDBLoader:
    def __init__(self, max_cases=30):
        self.max_cases = max_cases
        
    def _download_single_case(self, caseid):
        cache_path = os.path.join(CACHE_DIR, f"case_{caseid}.parquet")
        
        # 1. Check Cache
        if os.path.exists(cache_path):
            return pd.read_parquet(cache_path)
            
        try:
            # 2. Download
            vals = vitaldb.load_case(caseid, TRACKS, 1) # 1 sec interval
            
            df = pd.DataFrame(vals, columns=TRACKS)
            df = df.rename(columns=COL_MAP)
            
            # Cleaning
            df = df.ffill().bfill()
            df = df.dropna()
            
            # Save to cache
            if not df.empty:
                df['patient_id'] = f"vitaldb-{caseid}"
                df.to_parquet(cache_path)
                return df
                
        except Exception as e:
            logger.error(f"Failed to load case {caseid}: {e}")
            return None

    def download_cases(self, caseids=None):
        if not caseids:
             # Basic deterministic list for reproducibility
             # Using specific case IDs often ensures data quality if curated
             # Here we just blindly pick first N that have data
             caseids = list(range(1, self.max_cases + 10))
        
        logger.info(f"Acquiring data for {self.max_cases} cases...")
        
        data_streams = []
        
        # Parallel Download
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_case = {executor.submit(self._download_single_case, cid): cid for cid in caseids}
            
            for future in concurrent.futures.as_completed(future_to_case):
                cid = future_to_case[future]
                try:
                    df = future.result()
                    if df is not None and not df.empty:
                        data_streams.append(df)
                        if len(data_streams) >= self.max_cases:
                            break
                except Exception as exc:
                    logger.error(f"Case {cid} generated an exception: {exc}")
                    
        return data_streams[:self.max_cases]

if __name__ == "__main__":
    loader = VitalDBLoader(max_cases=30)
    dfs = loader.download_cases()
    logger.info(f"Successfully loaded {len(dfs)} cases.")
    
    # Save combined dataset for training
    combined_path = os.path.join(os.path.dirname(__file__), 'vitaldb_train.parquet')
    if dfs:
        full_df = pd.concat(dfs)
        full_df.to_parquet(combined_path)
        logger.info(f"Saved combined training data to {combined_path}")
