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
    interviews_remaining     INTEGER     DEFAULT 1 CHECK (interviews_remaining >= 0),
    is_unlimited             BOOLEAN     NOT NULL DEFAULT FALSE,
    is_admin                 BOOLEAN     NOT NULL DEFAULT FALSE,
    plan_type                VARCHAR(50) NOT NULL DEFAULT 'free',
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
    expected_signal    TEXT,
    difficulty_level   VARCHAR(20)  NOT NULL DEFAULT 'medium',
    is_followup        BOOLEAN      NOT NULL DEFAULT FALSE,
    parent_question_id VARCHAR(64)  REFERENCES InterviewQuestions(question_id)
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
