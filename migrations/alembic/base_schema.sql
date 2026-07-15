CREATE TABLE IF NOT EXISTS Login (
    user_id         VARCHAR(64)  PRIMARY KEY,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password        TEXT         DEFAULT NULL,
    auth_provider   VARCHAR(20)  NOT NULL DEFAULT 'local',
    google_id       VARCHAR(255),
    is_verified     BOOLEAN      NOT NULL DEFAULT FALSE,
    verification_token VARCHAR(255),
    token_expiry    TIMESTAMP,
    reset_token     VARCHAR(255),
    reset_token_expiry TIMESTAMP,
    token_version   INTEGER      NOT NULL DEFAULT 1,
    date_created    TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_login_email ON Login (email);
CREATE INDEX IF NOT EXISTS idx_login_verification_token ON Login (verification_token);
CREATE INDEX IF NOT EXISTS idx_login_reset_token ON Login (reset_token);

CREATE TABLE IF NOT EXISTS Jobs (
    job_id           SERIAL       PRIMARY KEY,
    title            VARCHAR(255) NOT NULL,
    description      TEXT,
    company          VARCHAR(255),
    location         VARCHAR(255),
    salary_range     VARCHAR(100),
    experience_level VARCHAR(50),
    created_at       TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS UserInfo (
    user_id                  VARCHAR(64) PRIMARY KEY REFERENCES Login(user_id),
    full_name                VARCHAR(255),
    job_id                   INTEGER REFERENCES Jobs(job_id) ON DELETE SET NULL,
    resume_text_encrypted    BYTEA,
    resume_json              JSONB,
    profile_json             JSONB,
    external_profile_signals JSONB,
    profile_completed        BOOLEAN     NOT NULL DEFAULT FALSE,
    mock_interview_count     INTEGER     NOT NULL DEFAULT 0,
    practice_interview_count INTEGER     NOT NULL DEFAULT 0,
    interviews_remaining     INTEGER     DEFAULT 3 CHECK (interviews_remaining >= 0),
    is_unlimited             BOOLEAN     NOT NULL DEFAULT FALSE,
    is_admin                 BOOLEAN     NOT NULL DEFAULT FALSE,
    plan_type                VARCHAR(50) NOT NULL DEFAULT 'starter',
    interview_profile_type   VARCHAR(32) NOT NULL DEFAULT 'mid_tier',
    avatar_url               TEXT,
    notification_prefs       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    resume_uploaded_at       TIMESTAMP,
    updated_at               TIMESTAMP   NOT NULL DEFAULT NOW(),
    date_created             TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_userinfo_job ON UserInfo (job_id);

CREATE TABLE IF NOT EXISTS Interviews (
    interview_id     VARCHAR(64)  PRIMARY KEY,
    user_id          VARCHAR(64)  NOT NULL REFERENCES UserInfo(user_id),
    interview_mode   VARCHAR(20)  NOT NULL,
    interview_type   VARCHAR(50)  NOT NULL,
    job_title        VARCHAR(255),
    strictness_level VARCHAR(20)  NOT NULL DEFAULT 'medium',
    status           VARCHAR(20)  NOT NULL DEFAULT 'in_progress',
    session_id       VARCHAR(64),
    persona_data     JSONB,
    questions_data   JSONB,
    settings         JSONB,
    overall_score    NUMERIC(5,2),
    feedback_summary TEXT,
    report_json      JSONB,
    duration_seconds INTEGER,
    full_transcript  JSONB,
    created_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    completed_at     TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_interviews_user ON Interviews (user_id);
CREATE INDEX IF NOT EXISTS idx_interviews_status ON Interviews (status);
CREATE INDEX IF NOT EXISTS idx_interviews_created ON Interviews (created_at DESC);

CREATE TABLE IF NOT EXISTS JobProfiles (
    profile_id  SERIAL      PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    role        VARCHAR(255) NOT NULL,
    company     VARCHAR(255),
    tech_stack  JSONB       NOT NULL DEFAULT '[]'::jsonb,
    is_selected BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_profiles_user ON JobProfiles (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS InterviewQuestions (
    question_id        VARCHAR(64)  PRIMARY KEY,
    interview_id       VARCHAR(64)  NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    question_text      TEXT         NOT NULL,
    question_order     INTEGER      NOT NULL,
    question_type      VARCHAR(50)  NOT NULL DEFAULT 'main',
    topic_label        VARCHAR(255),
    profile_type       VARCHAR(32),
    rubric_version     VARCHAR(40),
    source             VARCHAR(40),
    expected_signal    TEXT,
    quality_score      NUMERIC(5,2),
    validation_failures JSONB DEFAULT '[]'::jsonb,
    generation_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    difficulty_level   VARCHAR(20)  NOT NULL DEFAULT 'medium',
    is_followup        BOOLEAN      NOT NULL DEFAULT FALSE,
    parent_question_id VARCHAR(64)  REFERENCES InterviewQuestions(question_id),
    created_at         TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_iq_interview ON InterviewQuestions (interview_id);

CREATE TABLE IF NOT EXISTS InterviewResponses (
    response_id           VARCHAR(64) PRIMARY KEY,
    interview_id          VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    question_id           VARCHAR(64) NOT NULL REFERENCES InterviewQuestions(question_id) ON DELETE CASCADE,
    user_response         TEXT,
    response_time_seconds INTEGER,
    ai_feedback           TEXT,
    score                 NUMERIC(5,2),
    evaluation_json       JSONB,
    technical_accuracy    NUMERIC(5,2),
    communication         NUMERIC(5,2),
    problem_solving       NUMERIC(5,2),
    confidence            NUMERIC(5,2),
    relevance             NUMERIC(5,2),
    answer_quality_flags  JSONB DEFAULT '[]'::jsonb,
    evidence_quotes       JSONB DEFAULT '[]'::jsonb,
    retry_state           JSONB,
    stt_confidence        NUMERIC(5,2),
    nonverbal_metrics     JSONB,
    coaching_hint         TEXT,
    created_at            TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ir_interview ON InterviewResponses (interview_id);

CREATE TABLE IF NOT EXISTS AIEventLogs (
    event_id       BIGSERIAL PRIMARY KEY,
    user_id        VARCHAR(64),
    interview_id   VARCHAR(64),
    event_type     VARCHAR(80) NOT NULL,
    provider       VARCHAR(40),
    model          VARCHAR(120),
    prompt_tokens  INTEGER,
    output_tokens  INTEGER,
    latency_ms     INTEGER,
    success        BOOLEAN NOT NULL DEFAULT TRUE,
    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_event_logs_created ON AIEventLogs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_event_logs_interview ON AIEventLogs (interview_id, created_at DESC);

CREATE TABLE IF NOT EXISTS LocalModelInferenceLogs (
    inference_id       BIGSERIAL PRIMARY KEY,
    user_id            VARCHAR(64),
    interview_id       VARCHAR(64),
    event_type         VARCHAR(80) NOT NULL,
    provider_policy    VARCHAR(32) NOT NULL,
    endpoint_model     VARCHAR(160) NOT NULL,
    prompt_tokens      INTEGER,
    output_tokens      INTEGER,
    estimated_cost_usd NUMERIC(10,6),
    latency_ms         INTEGER,
    success            BOOLEAN NOT NULL DEFAULT TRUE,
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_local_model_inference_interview ON LocalModelInferenceLogs (interview_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_local_model_inference_user ON LocalModelInferenceLogs (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS LearnerSkillStates (
    state_id         BIGSERIAL PRIMARY KEY,
    user_id          VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    skill_key        VARCHAR(120) NOT NULL,
    skill_category   VARCHAR(40) NOT NULL,
    mastery_score    NUMERIC(5,2) NOT NULL DEFAULT 0,
    confidence_score NUMERIC(5,2) NOT NULL DEFAULT 0,
    evidence_count   INTEGER NOT NULL DEFAULT 0,
    last_evidence_at TIMESTAMP,
    next_review_at   TIMESTAMP,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, skill_key)
);

CREATE INDEX IF NOT EXISTS idx_learner_skill_states_user ON LearnerSkillStates (user_id, mastery_score ASC, next_review_at ASC);

CREATE TABLE IF NOT EXISTS SkillEvidenceEvents (
    evidence_id   BIGSERIAL PRIMARY KEY,
    user_id       VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    interview_id  VARCHAR(64) REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    response_id   VARCHAR(64) REFERENCES InterviewResponses(response_id) ON DELETE SET NULL,
    skill_key     VARCHAR(120) NOT NULL,
    evidence_type VARCHAR(50) NOT NULL,
    score_delta   NUMERIC(5,2) NOT NULL DEFAULT 0,
    evidence      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skill_evidence_user_skill ON SkillEvidenceEvents (user_id, skill_key, created_at DESC);

CREATE TABLE IF NOT EXISTS ProjectKnowledgeGaps (
    gap_id        BIGSERIAL PRIMARY KEY,
    user_id       VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    project_key   VARCHAR(160) NOT NULL,
    gap_key       VARCHAR(120) NOT NULL,
    gap_summary   TEXT NOT NULL,
    evidence      JSONB NOT NULL DEFAULT '{}'::jsonb,
    status        VARCHAR(20) NOT NULL DEFAULT 'open',
    next_check_at TIMESTAMP,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_gaps_user_status ON ProjectKnowledgeGaps (user_id, status, next_check_at ASC);

CREATE TABLE IF NOT EXISTS CoachExercises (
    exercise_id    VARCHAR(64) PRIMARY KEY,
    user_id        VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    interview_id   VARCHAR(64) REFERENCES Interviews(interview_id) ON DELETE SET NULL,
    exercise_type  VARCHAR(30) NOT NULL,
    title          VARCHAR(255) NOT NULL,
    prompt         TEXT NOT NULL,
    project_anchor VARCHAR(255),
    weakness_key   VARCHAR(80),
    status         VARCHAR(20) NOT NULL DEFAULT 'pending',
    completed_at   TIMESTAMP,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coach_exercises_user_status ON CoachExercises (user_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS GeneratedExercises (
    exercise_id     VARCHAR(64) PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    interview_id    VARCHAR(64) REFERENCES Interviews(interview_id) ON DELETE SET NULL,
    skill_key       VARCHAR(120),
    exercise_type   VARCHAR(50) NOT NULL,
    prompt          JSONB NOT NULL,
    rubric          JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_generated_exercises_user_status ON GeneratedExercises (user_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS ExerciseAttempts (
    attempt_id      VARCHAR(64) PRIMARY KEY,
    exercise_id     VARCHAR(64) REFERENCES GeneratedExercises(exercise_id) ON DELETE CASCADE,
    user_id         VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    submitted_answer TEXT,
    submitted_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    score           NUMERIC(5,2),
    feedback        JSONB NOT NULL DEFAULT '{}'::jsonb,
    mastery_passed  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exercise_attempts_user ON ExerciseAttempts (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS TechnicalInterviewRounds (
    round_id       VARCHAR(64) PRIMARY KEY,
    interview_id   VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    round_type     VARCHAR(30) NOT NULL,
    language       VARCHAR(20),
    prompt         TEXT NOT NULL,
    starter_code   TEXT,
    whiteboard_json JSONB,
    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    status         VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_technical_rounds_interview ON TechnicalInterviewRounds (interview_id, round_type);

CREATE TABLE IF NOT EXISTS TechnicalRunEvents (
    run_id         VARCHAR(64) PRIMARY KEY,
    round_id       VARCHAR(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
    user_id        VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    language       VARCHAR(20) NOT NULL,
    source_chars   INTEGER NOT NULL DEFAULT 0,
    source_excerpt TEXT,
    code_hash      VARCHAR(64),
    stdout         TEXT,
    stderr         TEXT,
    exit_code      INTEGER,
    error_signature VARCHAR(160),
    runtime_ms     INTEGER,
    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    hidden_validation_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_technical_run_events_round ON TechnicalRunEvents (round_id, created_at DESC);

CREATE TABLE IF NOT EXISTS TechnicalMistakeClusters (
    cluster_id       BIGSERIAL PRIMARY KEY,
    user_id          VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    round_id         VARCHAR(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
    mistake_type     VARCHAR(50) NOT NULL,
    mistake_key      VARCHAR(120) NOT NULL,
    examples         JSONB NOT NULL DEFAULT '[]'::jsonb,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    last_seen_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, mistake_key)
);

CREATE INDEX IF NOT EXISTS idx_technical_mistakes_user ON TechnicalMistakeClusters (user_id, occurrence_count DESC, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS ClientBodyLanguageMetrics (
    metric_id      BIGSERIAL PRIMARY KEY,
    interview_id   VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    payload        JSONB NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_body_language_interview ON ClientBodyLanguageMetrics (interview_id, created_at DESC);

CREATE TABLE IF NOT EXISTS AntiCheatEvents (
    event_id       BIGSERIAL PRIMARY KEY,
    interview_id   VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    event_type     VARCHAR(50) NOT NULL,
    payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_anti_cheat_interview ON AntiCheatEvents (interview_id, created_at DESC);

CREATE TABLE IF NOT EXISTS MalpracticeEvents (
    event_id      BIGSERIAL PRIMARY KEY,
    interview_id  VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id       VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    event_type    VARCHAR(50) NOT NULL,
    severity      VARCHAR(20) NOT NULL DEFAULT 'warning',
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_malpractice_interview ON MalpracticeEvents (interview_id, created_at DESC);

CREATE TABLE IF NOT EXISTS InterviewMediaAssets (
    asset_id         VARCHAR(64) PRIMARY KEY,
    interview_id     VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id          VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    media_kind       VARCHAR(20) NOT NULL,
    storage_provider VARCHAR(30) NOT NULL DEFAULT 'local_manifest',
    object_key       TEXT NOT NULL,
    content_type     VARCHAR(120),
    byte_size        BIGINT NOT NULL DEFAULT 0,
    chunk_index      INTEGER,
    chunk_count      INTEGER,
    checksum         VARCHAR(128),
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status           VARCHAR(20) NOT NULL DEFAULT 'pending',
    retention_status VARCHAR(30) NOT NULL DEFAULT 'retained',
    delete_after     TIMESTAMP,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at     TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_media_assets_interview ON InterviewMediaAssets (interview_id, media_kind, created_at DESC);

CREATE TABLE IF NOT EXISTS AnalysisJobs (
    job_id         VARCHAR(64) PRIMARY KEY,
    interview_id   VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    status         VARCHAR(30) NOT NULL DEFAULT 'queued',
    trigger_reason VARCHAR(80),
    current_stage  VARCHAR(80),
    progress       INTEGER NOT NULL DEFAULT 0,
    error_message  TEXT,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at     TIMESTAMP,
    updated_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analysis_jobs_interview ON AnalysisJobs (interview_id, created_at DESC);

CREATE TABLE IF NOT EXISTS AnalysisStageOutputs (
    output_id     VARCHAR(64) PRIMARY KEY,
    job_id        VARCHAR(64) NOT NULL REFERENCES AnalysisJobs(job_id) ON DELETE CASCADE,
    interview_id  VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    stage_name    VARCHAR(80) NOT NULL,
    status        VARCHAR(30) NOT NULL DEFAULT 'queued',
    output_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    started_at    TIMESTAMP,
    completed_at  TIMESTAMP,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analysis_stage_outputs_job ON AnalysisStageOutputs (job_id, stage_name);

CREATE TABLE IF NOT EXISTS ReportArtifacts (
    artifact_id  VARCHAR(64) PRIMARY KEY,
    interview_id VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id      VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    report_type  VARCHAR(30) NOT NULL,
    audience     VARCHAR(30) NOT NULL DEFAULT 'candidate',
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_report_artifacts_interview ON ReportArtifacts (interview_id, audience);

CREATE TABLE IF NOT EXISTS TechnicalCodeSnapshots (
    snapshot_id    VARCHAR(64) PRIMARY KEY,
    round_id       VARCHAR(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
    interview_id   VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    language       VARCHAR(20),
    source_chars   INTEGER NOT NULL DEFAULT 0,
    code_hash      VARCHAR(64),
    source_excerpt TEXT,
    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_code_snapshots_round ON TechnicalCodeSnapshots (round_id, created_at DESC);

CREATE TABLE IF NOT EXISTS TechnicalSubmissions (
    submission_id  VARCHAR(64) PRIMARY KEY,
    round_id       VARCHAR(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
    interview_id   VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    language       VARCHAR(20) NOT NULL,
    code_hash      VARCHAR(64),
    source_excerpt TEXT,
    submit_number  INTEGER NOT NULL,
    visible_passed INTEGER NOT NULL DEFAULT 0,
    visible_total  INTEGER NOT NULL DEFAULT 0,
    hidden_passed  INTEGER NOT NULL DEFAULT 0,
    hidden_total   INTEGER NOT NULL DEFAULT 0,
    runtime_ms     INTEGER,
    memory_kb      INTEGER,
    status         VARCHAR(30) NOT NULL DEFAULT 'submitted',
    result_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_technical_submissions_round ON TechnicalSubmissions (round_id, created_at DESC);

CREATE TABLE IF NOT EXISTS TechnicalTelemetryEvents (
    event_id     BIGSERIAL PRIMARY KEY,
    interview_id VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    round_id     VARCHAR(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
    user_id      VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    event_type   VARCHAR(50) NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_technical_telemetry_interview ON TechnicalTelemetryEvents (interview_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ProctoringFlags (
    flag_id      BIGSERIAL PRIMARY KEY,
    interview_id VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id      VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    flag_type    VARCHAR(60) NOT NULL,
    severity     VARCHAR(20) NOT NULL DEFAULT 'medium',
    evidence     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proctoring_flags_interview ON ProctoringFlags (interview_id, severity, created_at DESC);

CREATE TABLE IF NOT EXISTS Subscriptions (
    subscription_id VARCHAR(64)  PRIMARY KEY,
    user_id         VARCHAR(64)  NOT NULL REFERENCES UserInfo(user_id),
    plan_type       VARCHAR(50)  NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'active',
    start_date      TIMESTAMP    NOT NULL,
    end_date        TIMESTAMP    NOT NULL,
    auto_renew      BOOLEAN      NOT NULL DEFAULT TRUE,
    is_unlimited    BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sub_user ON Subscriptions (user_id);
CREATE INDEX IF NOT EXISTS idx_sub_status ON Subscriptions (status);

CREATE TABLE IF NOT EXISTS Transactions (
    transaction_id  VARCHAR(64)  PRIMARY KEY,
    user_id         VARCHAR(64)  NOT NULL REFERENCES UserInfo(user_id),
    subscription_id VARCHAR(64)  REFERENCES Subscriptions(subscription_id),
    amount          NUMERIC(10,2) NOT NULL,
    credits_purchased INTEGER,
    currency        VARCHAR(10)  NOT NULL DEFAULT 'USD',
    payment_method  VARCHAR(50),
    payment_provider VARCHAR(50),
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    expires_at      TIMESTAMP,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_txn_user ON Transactions (user_id);

CREATE TABLE IF NOT EXISTS ResumeUploadLogs (
    id          SERIAL      PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id),
    uploaded_at TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rul_user_time ON ResumeUploadLogs (user_id, uploaded_at DESC);

CREATE TABLE IF NOT EXISTS SupportSubmissions (
    submission_id BIGSERIAL PRIMARY KEY,
    user_id       VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    interview_id  VARCHAR(64) REFERENCES Interviews(interview_id) ON DELETE SET NULL,
    kind          VARCHAR(20) NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'open',
    title         VARCHAR(255),
    message       TEXT        NOT NULL,
    steps         TEXT,
    rating        SMALLINT,
    page_url      TEXT,
    admin_notes   TEXT,
    created_at    TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_support_user_created ON SupportSubmissions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_support_status_created ON SupportSubmissions (status, created_at DESC);

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

-- Auto-update updated_at on UserInfo row changes
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_updated_at ON UserInfo;
CREATE TRIGGER set_updated_at
    BEFORE UPDATE ON UserInfo
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_column();
