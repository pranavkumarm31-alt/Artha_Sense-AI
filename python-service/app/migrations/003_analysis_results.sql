ALTER TABLE economic_analysis
    ADD COLUMN IF NOT EXISTS analysis_version TEXT NOT NULL DEFAULT '1.0';

CREATE INDEX IF NOT EXISTS idx_economic_analysis_type_period
    ON economic_analysis (analysis_type, observation_period, analysis_version);
