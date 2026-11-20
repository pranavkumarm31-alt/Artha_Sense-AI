CREATE TABLE IF NOT EXISTS data_sources (
    id BIGSERIAL PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    dataset TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS economic_indicators (
    id BIGSERIAL PRIMARY KEY,
    metric_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    frequency TEXT NOT NULL CHECK (frequency IN ('monthly', 'quarterly')),
    unit TEXT NOT NULL,
    base_year TEXT,
    source_id BIGINT NOT NULL REFERENCES data_sources(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS economic_observations (
    id BIGSERIAL PRIMARY KEY,
    indicator_id BIGINT NOT NULL REFERENCES economic_indicators(id),
    observation_period TEXT NOT NULL,
    observation_start DATE NOT NULL,
    fiscal_year TEXT,
    quarter TEXT CHECK (quarter IS NULL OR quarter IN ('Q1', 'Q2', 'Q3', 'Q4')),
    month SMALLINT CHECK (month IS NULL OR month BETWEEN 1 AND 12),
    value NUMERIC NOT NULL,
    value_type TEXT NOT NULL CHECK (value_type IN ('official', 'calculated', 'forecast', 'scenario')),
    unit TEXT NOT NULL,
    base_year TEXT,
    source_id BIGINT NOT NULL REFERENCES data_sources(id),
    source_status TEXT NOT NULL CHECK (source_status IN ('LIVE', 'STALE')),
    last_fetched_at TIMESTAMPTZ NOT NULL,
    publication_date DATE,
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (indicator_id, observation_period)
);

CREATE INDEX IF NOT EXISTS idx_economic_observations_period
    ON economic_observations (indicator_id, observation_start DESC);
CREATE INDEX IF NOT EXISTS idx_economic_observations_fiscal_year
    ON economic_observations (fiscal_year, quarter);
CREATE INDEX IF NOT EXISTS idx_economic_observations_source
    ON economic_observations (source_id, last_fetched_at DESC);

CREATE TABLE IF NOT EXISTS data_ingestion_logs (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES data_sources(id),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
    observations_read INTEGER NOT NULL DEFAULT 0 CHECK (observations_read >= 0),
    observations_upserted INTEGER NOT NULL DEFAULT 0 CHECK (observations_upserted >= 0),
    error TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_ingestion_logs_source_time
    ON data_ingestion_logs (source_id, started_at DESC);

CREATE TABLE IF NOT EXISTS model_registry (
    id BIGSERIAL PRIMARY KEY,
    model_key TEXT NOT NULL UNIQUE,
    model_name TEXT NOT NULL,
    version TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    artifact_path TEXT,
    status TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'retired', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_training_runs (
    id BIGSERIAL PRIMARY KEY,
    model_id BIGINT REFERENCES model_registry(id),
    indicator_id BIGINT NOT NULL REFERENCES economic_indicators(id),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'insufficient_data', 'failed')),
    observations_used INTEGER NOT NULL DEFAULT 0 CHECK (observations_used >= 0),
    training_period_start DATE,
    training_period_end DATE,
    validation_method TEXT,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_training_runs_indicator_time
    ON model_training_runs (indicator_id, started_at DESC);

CREATE TABLE IF NOT EXISTS forecast_metrics (
    id BIGSERIAL PRIMARY KEY,
    training_run_id BIGINT NOT NULL REFERENCES model_training_runs(id),
    model_id BIGINT REFERENCES model_registry(id),
    indicator_id BIGINT NOT NULL REFERENCES economic_indicators(id),
    metric_name TEXT NOT NULL,
    metric_value NUMERIC,
    test_period_start DATE,
    test_period_end DATE,
    test_observations INTEGER NOT NULL DEFAULT 0 CHECK (test_observations >= 0),
    baseline_model TEXT,
    baseline_value NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (training_run_id, metric_name)
);
CREATE INDEX IF NOT EXISTS idx_forecast_metrics_indicator
    ON forecast_metrics (indicator_id, created_at DESC);

CREATE TABLE IF NOT EXISTS forecasts (
    id BIGSERIAL PRIMARY KEY,
    indicator_id BIGINT NOT NULL REFERENCES economic_indicators(id),
    model_id BIGINT NOT NULL REFERENCES model_registry(id),
    training_run_id BIGINT NOT NULL REFERENCES model_training_runs(id),
    observation_period TEXT NOT NULL,
    observation_start DATE NOT NULL,
    horizon INTEGER NOT NULL CHECK (horizon > 0),
    value NUMERIC NOT NULL,
    lower_bound NUMERIC,
    upper_bound NUMERIC,
    unit TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (indicator_id, model_id, observation_period, generated_at)
);
CREATE INDEX IF NOT EXISTS idx_forecasts_indicator_period
    ON forecasts (indicator_id, observation_start DESC);

CREATE TABLE IF NOT EXISTS anomaly_detections (
    id BIGSERIAL PRIMARY KEY,
    indicator_id BIGINT NOT NULL REFERENCES economic_indicators(id),
    observation_period TEXT NOT NULL,
    actual_value NUMERIC NOT NULL,
    expected_value NUMERIC,
    deviation NUMERIC,
    anomaly_score NUMERIC NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    detection_method TEXT NOT NULL,
    explanation TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (indicator_id, observation_period, detection_method)
);
CREATE INDEX IF NOT EXISTS idx_anomalies_indicator_time
    ON anomaly_detections (indicator_id, detected_at DESC);

CREATE TABLE IF NOT EXISTS economic_analysis (
    id BIGSERIAL PRIMARY KEY,
    analysis_type TEXT NOT NULL,
    observation_period TEXT,
    content JSONB NOT NULL,
    source_observations JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_economic_analysis_type_time
    ON economic_analysis (analysis_type, created_at DESC);
