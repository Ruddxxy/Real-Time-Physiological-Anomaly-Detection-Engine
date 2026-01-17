-- Physio Engine Schema

-- Patients
CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    baseline_hr_min INTEGER,
    baseline_hr_max INTEGER,
    baseline_temp_c NUMERIC(4, 2)
);

-- Raw Vitals Events (High volume, consider partitioning in prod)
CREATE TABLE IF NOT EXISTS vitals_events (
    id BIGSERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    hr INTEGER,
    bp_sys INTEGER,
    bp_dia INTEGER,
    spo2 INTEGER,
    rr INTEGER,
    temp NUMERIC(4, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uniq_patient_time UNIQUE (patient_id, timestamp)
);

CREATE INDEX idx_vitals_patient_time ON vitals_events(patient_id, timestamp DESC);

-- Window Summaries (Persisted state of sliding windows)
CREATE TABLE IF NOT EXISTS windows (
    id BIGSERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    window_size_seconds INTEGER NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    avg_hr NUMERIC,
    avg_spo2 NUMERIC,
    avg_temp NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_windows_patient_time ON windows(patient_id, end_time DESC);

-- Anomalies
CREATE TABLE IF NOT EXISTS anomalies (
    id BIGSERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    anomaly_type TEXT NOT NULL, -- 'drift', 'spike', 'multi-signal'
    score NUMERIC NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    details JSONB, -- Store snapshot of vitals that triggered it
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_anomalies_active ON anomalies(timestamp DESC);
CREATE INDEX idx_anomalies_patient ON anomalies(patient_id);
