import joblib
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score
import numpy as np
import pandas as pd
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from data.generator import generate_training_data

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.joblib')

def train_and_eval():
    print("Generating synthetic data...")
    # Train: 5000 normal
    X_train, y_train = generate_training_data(n_samples=5000)
    
    # Test: 1000 normal + 100 anomalies (we need to inject anomalies manually for test set)
    # Generator currently returns all '1' (Normal). 
    # Let's create a manual test set with anomalies.
    X_test_normal, _ = generate_training_data(n_samples=1000)
    
    # Create anomalies
    X_test_anom = []
    for _ in range(100):
        # Spikes / drops
        vec = [
             np.random.randint(150, 200), # HR spike
             120, 80, 98, 16, 37.0
        ]
        X_test_anom.append(vec)
        
    X_test = np.array(X_test_normal + X_test_anom)
    # 1 for normal, -1 for anomaly is IF convention. 
    # But for metrics, usually 1=Positive(Anomaly), 0=Negative(Normal).
    # IF predict: 1=Normal, -1=Anomaly.
    
    # Ground truth for metrics (Anomaly=1)
    y_test_true = np.array([0]*1000 + [1]*100)
    
    print(f"Training on {len(X_train)} samples...")
    clf = IsolationForest(contamination=0.02, random_state=42)
    clf.fit(X_train)
    
    print("Evaluating...")
    # decision_function: average anomaly score of X of the base classifiers.
    # The anomaly score of an input sample is computed as the mean anomaly score of the trees in the forest.
    # The measure of normality of an observation given a tree is the depth of the leaf containing this observation.
    # Lower = more abnormal.
    scores = clf.decision_function(X_test) 
    
    # We want Score -> Probability of Anomaly.
    # low score = anomaly.
    # So invert: -score
    y_scores = -scores
    
    # Preds
    preds_if = clf.predict(X_test)
    # Convert IF preds (1/-1) to Binary (0/1) for metrics
    # IF: -1 (Anomaly) -> 1, 1 (Normal) -> 0
    y_preds = np.where(preds_if == -1, 1, 0)
    
    auc = roc_auc_score(y_test_true, y_scores)
    prec = precision_score(y_test_true, y_preds)
    rec = recall_score(y_test_true, y_preds)
    f1 = f1_score(y_test_true, y_preds)
    
    print(f"Metrics: AUC={auc:.4f} Precision={prec:.4f} Recall={rec:.4f} F1={f1:.4f}")
    
    print(f"Saving model to {MODEL_PATH}...")
    joblib.dump(clf, MODEL_PATH)



if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=str, default="synthetic", choices=["synthetic", "vitaldb"])
    args = parser.parse_args()
    
    if args.source == "vitaldb":
        # 1. Load from Parquet (Cached/Prepared)
        try:
            parquet_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'vitaldb_train.parquet')
            if not os.path.exists(parquet_path):
                print(f"Cache miss: {parquet_path}")
                print("Run 'python3 data/vitaldb_loader.py' first to acquire data.")
                sys.exit(1)

            full_df = pd.read_parquet(parquet_path)
            # Convert to numpy array
            X_all = full_df[['hr', 'bp_sys', 'bp_dia', 'spo2', 'rr', 'temp']].values
            
            # Split 80/20
            split_idx = int(len(X_all) * 0.8)
            X_train = X_all[:split_idx]
            X_test = X_all[split_idx:]
            
        except Exception as e:
            print(f"Error loading cached data: {e}")
            sys.exit(1)
        
        # 2. Generate Ground Truth Labels via Clinical Rules (No Synthesis)
        # We need to map X_test features back to metrics to check rules.
        # Order: ['hr', 'bp_sys', 'bp_dia', 'spo2', 'rr', 'temp']
        y_test_true = []
        for row in X_test:
            hr, bp_sys, bp_dia, spo2, rr, temp = row
            is_anomaly = 0
            # Clinical Thresholds (ICU Alarms)
            if (hr < 40 or hr > 140) or \
               (bp_sys < 80 or bp_sys > 180) or \
               (spo2 < 90) or \
               (rr < 8 or rr > 30):
                is_anomaly = 1
            y_test_true.append(is_anomaly)
            
        y_test_true = np.array(y_test_true)
        
        print(f"Training on {len(X_train)} real samples...")
        clf = IsolationForest(contamination=0.01, random_state=42)
        clf.fit(X_train)
        
        print("Evaluating on Real Data (Rule-Based Labels)...")
        scores = clf.decision_function(X_test)
        # Invert: Higher = Anomaly
        y_scores = -scores
        
        print(f"positive_labels: {sum(y_test_true)}")
        print(f"total_windows: {len(y_scores)}")
        
        # 4. Enforce Non-Zero Operating Point
        # Force threshold to catch top 5% as anomalies
        threshold = np.percentile(y_scores, 95)
        print(f"Forced Threshold (95th percentile): {threshold:.4f}")
        
        y_preds = (y_scores >= threshold).astype(int)
        
        scores_above_threshold = sum(y_preds)
        print(f"scores_above_threshold={scores_above_threshold}")
        
        try:
            auc = roc_auc_score(y_test_true, y_scores)
            prec = precision_score(y_test_true, y_preds, zero_division=0)
            rec = recall_score(y_test_true, y_preds, zero_division=0)
        except Exception as e:
            print(f"Metric Error: {e}")
            auc, prec, rec = 0, 0, 0
        
        print(f"dataset=vitaldb")
        print(f"AUC={auc:.4f}")
        print(f"precision={prec:.4f}")
        print(f"recall={rec:.4f}")
        
        joblib.dump(clf, MODEL_PATH)
        
    else:
        train_and_eval()
