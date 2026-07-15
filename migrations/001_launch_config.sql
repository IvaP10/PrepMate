BEGIN;

CREATE TABLE IF NOT EXISTS SchemaMigrations (
    migration_id VARCHAR(120) PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS PlanDefinitions (
    plan_type VARCHAR(40) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    amount NUMERIC(10,2) NOT NULL DEFAULT 0,
    currency VARCHAR(10) NOT NULL DEFAULT 'INR',
    duration_days INTEGER NOT NULL DEFAULT 30,
    is_unlimited BOOLEAN NOT NULL DEFAULT FALSE,
    features JSONB NOT NULL DEFAULT '[]'::jsonb,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS PlanEntitlements (
    plan_type VARCHAR(40) PRIMARY KEY REFERENCES PlanDefinitions(plan_type) ON DELETE CASCADE,
    entitlements JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS FeatureFlags (
    flag_key VARCHAR(80) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ExerciseModeDefinitions (
    mode VARCHAR(50) PRIMARY KEY,
    title VARCHAR(120) NOT NULL,
    description TEXT NOT NULL,
    input_type VARCHAR(40) NOT NULL,
    timer_seconds INTEGER,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ModelPolicyRules (
    event_type VARCHAR(80) PRIMARY KEY,
    provider_policy VARCHAR(32) NOT NULL,
    max_cost_usd NUMERIC(10,4),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS LLMCache (
    cache_key VARCHAR(160) PRIMARY KEY,
    event_type VARCHAR(80) NOT NULL,
    payload JSONB NOT NULL,
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE GeneratedExercises ADD COLUMN IF NOT EXISTS exercise_mode VARCHAR(50);
ALTER TABLE GeneratedExercises ADD COLUMN IF NOT EXISTS input_type VARCHAR(40);
ALTER TABLE GeneratedExercises ADD COLUMN IF NOT EXISTS timer_seconds INTEGER;
ALTER TABLE GeneratedExercises ADD COLUMN IF NOT EXISTS source_response_id VARCHAR(64);
ALTER TABLE GeneratedExercises ADD COLUMN IF NOT EXISTS priority_score NUMERIC(5,2) NOT NULL DEFAULT 0;

ALTER TABLE Transactions ADD COLUMN IF NOT EXISTS provider_order_id VARCHAR(120);
ALTER TABLE Transactions ADD COLUMN IF NOT EXISTS provider_payment_id VARCHAR(120);
ALTER TABLE Transactions ADD COLUMN IF NOT EXISTS provider_signature_hash VARCHAR(128);
ALTER TABLE Transactions ADD COLUMN IF NOT EXISTS provider_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb;

INSERT INTO SchemaMigrations (migration_id)
VALUES ('001_launch_config')
ON CONFLICT (migration_id) DO NOTHING;

COMMIT;
