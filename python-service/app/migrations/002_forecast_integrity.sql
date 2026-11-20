CREATE UNIQUE INDEX IF NOT EXISTS uq_forecasts_indicator_model_period
    ON forecasts (indicator_id, model_id, observation_period);

CREATE INDEX IF NOT EXISTS idx_forecasts_generated_at
    ON forecasts (indicator_id, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_training_runs_indicator_status
    ON model_training_runs (indicator_id, status, started_at DESC);
