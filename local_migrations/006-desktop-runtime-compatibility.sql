-- PrepMate local schema version 6: repair early desktop-alpha schema history.
-- Revisions 001 and 003 were regenerated during the private alpha. This
-- additive migration brings databases created before that regeneration to the
-- current runtime contract without deleting or replacing user data.

CREATE TABLE IF NOT EXISTS SelfReviewEvents (
    event_id       INTEGER PRIMARY KEY,
    interview_id   TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    event_type     TEXT(50) NOT NULL,
    payload        TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS SessionReviewEvents (
    event_id      INTEGER PRIMARY KEY,
    interview_id  TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id       TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    event_type    TEXT(50) NOT NULL,
    severity      TEXT(20) NOT NULL DEFAULT 'warning',
    payload       TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS MediaCoachingSignals (
    flag_id      INTEGER PRIMARY KEY,
    interview_id TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id      TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    flag_type    TEXT(60) NOT NULL,
    severity     TEXT(20) NOT NULL DEFAULT 'medium',
    evidence     TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE AttemptPreflightChecks
    ADD COLUMN IF NOT EXISTS input_mode TEXT NOT NULL DEFAULT 'text'
        CHECK (input_mode IN ('voice', 'text'));

ALTER TABLE AttemptPreflightChecks
    ADD COLUMN IF NOT EXISTS provider_ready INTEGER NOT NULL DEFAULT 0;

ALTER TABLE JobProfiles
    ADD COLUMN IF NOT EXISTS normalized_requirements_encrypted BLOB;

CREATE INDEX IF NOT EXISTS idx_self_review_events_interview
    ON SelfReviewEvents (interview_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_session_review_events_interview
    ON SessionReviewEvents (interview_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_media_coaching_signals_interview
    ON MediaCoachingSignals (interview_id, severity, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_interview_response_idempotency
    ON InterviewResponses (interview_id, idempotency_key);
