ALTER TABLE anomaly_detections
    ADD COLUMN IF NOT EXISTS percentage_deviation NUMERIC,
    ADD COLUMN IF NOT EXISTS model_version TEXT NOT NULL DEFAULT 'unspecified',
    ADD COLUMN IF NOT EXISTS model_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS source_key TEXT,
    ADD COLUMN IF NOT EXISTS source_name TEXT,
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS analysis_version TEXT NOT NULL DEFAULT '1.0';

CREATE INDEX IF NOT EXISTS idx_anomalies_indicator_severity
    ON anomaly_detections (indicator_id, severity, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_anomalies_method_period
    ON anomaly_detections (detection_method, observation_period);
