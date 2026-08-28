CREATE TABLE LocalSchemaVersion (
    version     INTEGER PRIMARY KEY,
    revision    TEXT NOT NULL UNIQUE,
    applied_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE AnalysisJobs (
    job_id         TEXT(64) PRIMARY KEY,
    interview_id   TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    status         TEXT(30) NOT NULL DEFAULT 'queued',
    trigger_reason TEXT(80),
    current_stage  TEXT(80),
    progress       INTEGER NOT NULL DEFAULT 0,
    retry_count    INTEGER NOT NULL DEFAULT 0,
    manual_retry_count INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT(160),
    evidence_hash  TEXT(128),
    lease_owner    TEXT(128),
    lease_expires_at TEXT,
    heartbeat_at   TEXT,
    next_attempt_at TEXT,
    error_message  TEXT,
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at     TEXT,
    updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at   TEXT
, manifest_id TEXT(64) REFERENCES EvidenceManifests(manifest_id) ON DELETE RESTRICT, producer_version TEXT(80) NOT NULL DEFAULT 'evidence-v4');

CREATE TABLE AnalysisStageOutputs (
    output_id     TEXT(64) PRIMARY KEY,
    job_id        TEXT(64) NOT NULL REFERENCES AnalysisJobs(job_id) ON DELETE CASCADE,
    interview_id  TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    stage_name    TEXT(80) NOT NULL,
    stage_version TEXT(40) NOT NULL DEFAULT 'v1',
    evidence_hash TEXT(128),
    input_hash    TEXT(128),
    model         TEXT(160),
    prompt_version TEXT(120),
    provenance_json TEXT NOT NULL DEFAULT '{}',
    status        TEXT(30) NOT NULL DEFAULT 'queued',
    output_json   TEXT NOT NULL DEFAULT '{}',
    error_message TEXT,
    started_at    TEXT,
    completed_at  TEXT,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE SelfReviewEvents (
    event_id       INTEGER PRIMARY KEY,
    interview_id   TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    event_type     TEXT(50) NOT NULL,
    payload        TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE AttemptContextSnapshots (
            snapshot_id TEXT(64) PRIMARY KEY,
            interview_id TEXT(64) NOT NULL UNIQUE REFERENCES Interviews(interview_id) ON DELETE CASCADE,
            user_id TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            resume_id TEXT(64) NOT NULL REFERENCES ResumeVersions(resume_id) ON DELETE RESTRICT,
            job_profile_id INTEGER REFERENCES JobProfiles(profile_id) ON DELETE RESTRICT,
            blueprint_id TEXT(64) NOT NULL REFERENCES InterviewBlueprints(blueprint_id) ON DELETE RESTRICT,
            profile_type TEXT(32) NOT NULL,
            profile_config_version TEXT(40) NOT NULL,
            role TEXT(255) NOT NULL,
            company_hash TEXT(128) NOT NULL,
            context_hash TEXT(128) NOT NULL,
            resume_payload_encrypted BLOB NOT NULL,
            job_context_encrypted BLOB NOT NULL,
            blueprint_context_encrypted BLOB NOT NULL,
            evaluator_version TEXT(80) NOT NULL,
            taxonomy_version TEXT(40) NOT NULL,
            rubric_version TEXT(40) NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE AttemptIntegrityEvents (
            event_id TEXT(64) PRIMARY KEY,
            interview_id TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
            user_id TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            client_session_id TEXT(64) NOT NULL,
            sequence INTEGER NOT NULL,
            event_type TEXT(80) NOT NULL,
            severity TEXT(20) NOT NULL DEFAULT 'info',
            source TEXT(30) NOT NULL DEFAULT 'browser',
            observed_at TEXT NOT NULL,
            received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            payload_encrypted BLOB,
            payload_hash TEXT(128) NOT NULL,
            idempotency_key TEXT(120),
            UNIQUE(interview_id, client_session_id, sequence)
        );

CREATE TABLE AttemptPreflightChecks (
            preflight_id TEXT(64) PRIMARY KEY,
            user_id TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            blueprint_id TEXT(64) NOT NULL REFERENCES InterviewBlueprints(blueprint_id) ON DELETE CASCADE,
            flow TEXT(20) NOT NULL CHECK (flow IN ('interview', 'technical')),
            input_mode TEXT(20) NOT NULL DEFAULT 'text' CHECK (input_mode IN ('voice', 'text')),
            camera_ready INTEGER NOT NULL,
            microphone_ready INTEGER NOT NULL,
            microphone_level_detected INTEGER NOT NULL,
            screen_share_ready INTEGER NOT NULL,
            network_ready INTEGER NOT NULL,
            backend_ready INTEGER NOT NULL,
            provider_ready INTEGER NOT NULL,
            sandbox_ready INTEGER NOT NULL DEFAULT FALSE,
            worker_ready INTEGER NOT NULL,
            error_codes TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            consumed_by_interview_id TEXT(64) REFERENCES Interviews(interview_id) ON DELETE SET NULL
        );

CREATE TABLE ClientBodyLanguageMetrics (
    metric_id      INTEGER PRIMARY KEY,
    interview_id   TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    payload        TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE CoachExercises (
    exercise_id    TEXT(64) PRIMARY KEY,
    user_id        TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    interview_id   TEXT(64) REFERENCES Interviews(interview_id) ON DELETE SET NULL,
    exercise_type  TEXT(30) NOT NULL,
    title          TEXT(255) NOT NULL,
    prompt         TEXT NOT NULL,
    project_anchor TEXT(255),
    weakness_key   TEXT(80),
    status         TEXT(20) NOT NULL DEFAULT 'pending',
    completed_at   TEXT,
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE EvidenceCorrections (
    correction_id TEXT(64) PRIMARY KEY,
    manifest_id TEXT(64) NOT NULL REFERENCES EvidenceManifests(manifest_id) ON DELETE CASCADE,
    interview_id TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    supersedes_evidence_type TEXT(80) NOT NULL,
    supersedes_evidence_id TEXT(160) NOT NULL,
    reason TEXT NOT NULL,
    correction_hash TEXT(128) NOT NULL,
    payload_encrypted BLOB NOT NULL,
    actor_id TEXT(64),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE EvidenceManifests (
    manifest_id TEXT(64) PRIMARY KEY,
    interview_id TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    schema_version TEXT(40) NOT NULL,
    evidence_hash TEXT(128) NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    manifest_json TEXT NOT NULL DEFAULT '{}',
    manifest_encrypted BLOB NOT NULL,
    revision_no INTEGER NOT NULL DEFAULT 1,
    is_current INTEGER NOT NULL DEFAULT TRUE,
    supersedes_manifest_id TEXT(64) REFERENCES EvidenceManifests(manifest_id) ON DELETE SET NULL,
    producer_version TEXT(80) NOT NULL DEFAULT 'evidence-v4',
    sealed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ExerciseAttempts (
    attempt_id      TEXT(64) PRIMARY KEY,
    exercise_id     TEXT(64) REFERENCES GeneratedExercises(exercise_id) ON DELETE CASCADE,
    user_id         TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    submitted_answer TEXT,
    submitted_payload TEXT NOT NULL DEFAULT '{}',
    score           REAL(5,2),
    feedback        TEXT NOT NULL DEFAULT '{}',
    mastery_passed  INTEGER NOT NULL DEFAULT FALSE,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
, attempt_session_id TEXT(64), idempotency_key TEXT(120), mission_id TEXT(64), mission_skill_id TEXT(64), roadmap_node_id TEXT(64), activity_type TEXT(60), is_checkpoint INTEGER NOT NULL DEFAULT FALSE, condition_results TEXT NOT NULL DEFAULT '[]', passed_conditions TEXT NOT NULL DEFAULT '[]', failed_conditions TEXT NOT NULL DEFAULT '[]', score_components TEXT NOT NULL DEFAULT '{}');

CREATE TABLE GeneratedExercises (
    exercise_id     TEXT(64) PRIMARY KEY,
    user_id         TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    interview_id    TEXT(64) REFERENCES Interviews(interview_id) ON DELETE SET NULL,
    skill_key       TEXT(120),
    exercise_type   TEXT(50) NOT NULL,
    prompt          TEXT NOT NULL,
    rubric          TEXT NOT NULL DEFAULT '{}',
    source_evidence TEXT NOT NULL DEFAULT '[]',
    status          TEXT(20) NOT NULL DEFAULT 'queued',
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at    TEXT
, exercise_mode TEXT(50), input_type TEXT(40), timer_seconds INTEGER, source_response_id TEXT(64), priority_score REAL(5,2) NOT NULL DEFAULT 0, mission_id TEXT(64), mission_skill_id TEXT(64), roadmap_node_id TEXT(64), activity_type TEXT(60), variation_group TEXT(80), is_checkpoint INTEGER NOT NULL DEFAULT FALSE, activity_metadata TEXT NOT NULL DEFAULT '{}');

CREATE TABLE ImprovementAttemptSessions (
    attempt_session_id TEXT(64) PRIMARY KEY,
    user_id            TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    mission_id         TEXT(64) NOT NULL REFERENCES ImprovementMissions(mission_id) ON DELETE CASCADE,
    roadmap_node_id    TEXT(64) NOT NULL REFERENCES ImprovementRoadmapNodes(roadmap_node_id) ON DELETE CASCADE,
    exercise_id        TEXT(64) NOT NULL REFERENCES GeneratedExercises(exercise_id) ON DELETE CASCADE,
    status             TEXT(30) NOT NULL DEFAULT 'draft',
    draft_payload      TEXT NOT NULL DEFAULT '{}',
    idempotency_key    TEXT(120) NOT NULL,
    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deadline_at        TEXT,
    remaining_seconds  INTEGER,
    expires_at         TEXT,
    UNIQUE(user_id, exercise_id, idempotency_key)
);

CREATE TABLE ImprovementMissionEvents (
    event_id        INTEGER PRIMARY KEY,
    user_id         TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    mission_id      TEXT(64) REFERENCES ImprovementMissions(mission_id) ON DELETE CASCADE,
    roadmap_node_id TEXT(64),
    exercise_id     TEXT(64),
    attempt_id      TEXT(64),
    event_type      TEXT(80) NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ImprovementMissionSkills (
    mission_skill_id       TEXT(64) PRIMARY KEY,
    mission_id             TEXT(64) NOT NULL REFERENCES ImprovementMissions(mission_id) ON DELETE CASCADE,
    user_id                TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    skill_key              TEXT(120) NOT NULL,
    label                  TEXT(180) NOT NULL,
    category               TEXT(50) NOT NULL,
    baseline_score         REAL(5,2) NOT NULL DEFAULT 0,
    latest_score           REAL(5,2) NOT NULL DEFAULT 0,
    target_score           REAL(5,2) NOT NULL DEFAULT 75,
    role_weight            REAL(5,2) NOT NULL DEFAULT 1,
    mastery_status         TEXT(40) NOT NULL DEFAULT 'untrained',
    evidence_summary       TEXT,
    criteria_json          TEXT NOT NULL DEFAULT '{}',
    created_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    verified_at            TEXT,
    needs_reinforcement_at TEXT
);

CREATE TABLE ImprovementMissions (
    mission_id         TEXT(64) PRIMARY KEY,
    user_id            TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    source_interview_id TEXT(64) REFERENCES Interviews(interview_id) ON DELETE SET NULL,
    mode               TEXT(20) NOT NULL DEFAULT 'mock',
    source_analysis_id TEXT(64),
    weakness_key       TEXT(160),
    weakness_type      TEXT(80),
    mission_type       TEXT(80) NOT NULL,
    title              TEXT(180) NOT NULL,
    assignment_reason  TEXT NOT NULL,
    diagnosis_json     TEXT NOT NULL DEFAULT '{}',
    priority_score     REAL(5,2) NOT NULL DEFAULT 0,
    priority_factors   TEXT NOT NULL DEFAULT '{}',
    baseline_readiness REAL(5,2) NOT NULL DEFAULT 0,
    current_readiness  REAL(5,2) NOT NULL DEFAULT 0,
    target_readiness   REAL(5,2) NOT NULL DEFAULT 75,
    progress_percent   REAL(5,2) NOT NULL DEFAULT 0,
    status             TEXT(30) NOT NULL DEFAULT 'active',
    prediction_json    TEXT NOT NULL DEFAULT '{}',
    validation_status  TEXT(40) NOT NULL DEFAULT 'active',
    validated_by_interview_id TEXT(64),
    held_out_checkpoint_id TEXT(64),
    validation_analysis_id TEXT(64),
    later_interview_id TEXT(64),
    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at       TEXT
);

CREATE TABLE ImprovementRoadmapNodes (
    roadmap_node_id     TEXT(64) PRIMARY KEY,
    mission_id          TEXT(64) NOT NULL REFERENCES ImprovementMissions(mission_id) ON DELETE CASCADE,
    user_id             TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    mission_skill_id    TEXT(64) REFERENCES ImprovementMissionSkills(mission_skill_id) ON DELETE CASCADE,
    exercise_id         TEXT(64) REFERENCES GeneratedExercises(exercise_id) ON DELETE SET NULL,
    recovery_of_node_id TEXT(64),
    order_index         INTEGER NOT NULL DEFAULT 0,
    title               TEXT(180) NOT NULL,
    description         TEXT,
    activity_type       TEXT(60) NOT NULL,
    availability_status TEXT(30) NOT NULL DEFAULT 'locked',
    attempt_status      TEXT(30) NOT NULL DEFAULT 'draft',
    result_status       TEXT(30) NOT NULL DEFAULT 'not_attempted',
    mastery_status      TEXT(40) NOT NULL DEFAULT 'untrained',
    estimated_minutes   INTEGER NOT NULL DEFAULT 4,
    expected_result     TEXT,
    evidence_json       TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at        TEXT
);

CREATE TABLE InterviewBlueprints (
            blueprint_id TEXT(64) PRIMARY KEY,
            user_id TEXT(64) NOT NULL
                REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            resume_id TEXT(64)
                REFERENCES ResumeVersions(resume_id) ON DELETE RESTRICT,
            job_profile_id INTEGER
                REFERENCES JobProfiles(profile_id) ON DELETE RESTRICT,
            interview_mode TEXT(20) NOT NULL,
            interview_type TEXT(50) NOT NULL,
            experience_level TEXT(40),
            difficulty_level TEXT(20) NOT NULL DEFAULT 'adaptive',
            duration_minutes INTEGER NOT NULL CHECK (duration_minutes BETWEEN 10 AND 120),
            focus TEXT NOT NULL DEFAULT '["mixed"]',
            round_config TEXT NOT NULL DEFAULT '{}',
            blueprint_json TEXT NOT NULL,
            settings_json TEXT NOT NULL DEFAULT '{}',
            blueprint_hash TEXT(128) NOT NULL,
            compiler_version TEXT(80) NOT NULL,
            request_idempotency_key TEXT(120),
            status TEXT(20) NOT NULL DEFAULT 'ready'
                CHECK (status IN ('draft', 'ready', 'consumed', 'expired')),
            expires_at TEXT,
            consumed_at TEXT,
            consumed_by_interview_id TEXT(64)
                REFERENCES Interviews(interview_id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_blueprint_owner_hash UNIQUE (user_id, blueprint_hash)
        );

CREATE TABLE InterviewMediaAssets (
    asset_id         TEXT(64) PRIMARY KEY,
    interview_id     TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id          TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    media_kind       TEXT(20) NOT NULL,
    storage_provider TEXT(30) NOT NULL DEFAULT 'local_manifest',
    object_key       TEXT NOT NULL,
    content_type     TEXT(120),
    byte_size        INTEGER NOT NULL DEFAULT 0,
    chunk_index      INTEGER,
    chunk_count      INTEGER,
    checksum         TEXT(128),
    metadata         TEXT NOT NULL DEFAULT '{}',
    status           TEXT(20) NOT NULL DEFAULT 'pending',
    retention_status TEXT(30) NOT NULL DEFAULT 'retained',
    delete_after     TEXT,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at     TEXT
);

CREATE TABLE InterviewQuestions (
    question_id        TEXT(64)  PRIMARY KEY,
    interview_id       TEXT(64)  NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    question_text      TEXT         NOT NULL,
    question_order     INTEGER      NOT NULL,
    question_type      TEXT(50)  NOT NULL DEFAULT 'main',
    topic_label        TEXT(255),
    profile_type       TEXT(32),
    rubric_version     TEXT(40),
    source             TEXT(40),
    expected_signal    TEXT,
    taxonomy_keys      TEXT NOT NULL DEFAULT '[]',
    expected_points    TEXT NOT NULL DEFAULT '[]',
    rubric_json        TEXT NOT NULL DEFAULT '{}',
    selection_reason   TEXT,
    blueprint_section_id TEXT(80),
    provenance         TEXT NOT NULL DEFAULT '{}',
    quality_score      REAL(5,2),
    validation_failures TEXT DEFAULT '[]',
    generation_metadata TEXT NOT NULL DEFAULT '{}',
    difficulty_level   TEXT(20)  NOT NULL DEFAULT 'medium',
    is_followup        INTEGER      NOT NULL DEFAULT FALSE,
    parent_question_id TEXT(64)  REFERENCES InterviewQuestions(question_id),
    created_at         TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE InterviewResponses (
    response_id           TEXT(64) PRIMARY KEY,
    interview_id          TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    question_id           TEXT(64) NOT NULL REFERENCES InterviewQuestions(question_id) ON DELETE CASCADE,
    user_response         TEXT,
    response_time_seconds INTEGER,
    ai_feedback           TEXT,
    score                 REAL(5,2),
    evaluation_json       TEXT,
    technical_accuracy    REAL(5,2),
    communication         REAL(5,2),
    problem_solving       REAL(5,2),
    confidence            REAL(5,2),
    relevance             REAL(5,2),
    answer_quality_flags  TEXT DEFAULT '[]',
    evidence_quotes       TEXT DEFAULT '[]',
    retry_state           TEXT,
    stt_confidence        REAL(5,2),
    nonverbal_metrics     TEXT,
    coaching_hint         TEXT,
    created_at            TEXT   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Interviews (
    interview_id     TEXT(64)  PRIMARY KEY,
    user_id          TEXT(64)  NOT NULL REFERENCES UserInfo(user_id),
    interview_mode   TEXT(20)  NOT NULL,
    interview_type   TEXT(50)  NOT NULL,
    job_title        TEXT(255),
    strictness_level TEXT(20)  NOT NULL DEFAULT 'medium',
    status           TEXT(20)  NOT NULL DEFAULT 'in_progress',
    session_id       TEXT(64),
    persona_data     TEXT,
    questions_data   TEXT,
    settings         TEXT,
    overall_score    REAL(5,2),
    feedback_summary TEXT,
    report_json      TEXT,
    duration_seconds INTEGER,
    full_transcript  TEXT,
    resume_id        TEXT(64),
    job_profile_id   INTEGER,
    llm_cost_usd     REAL(10,6) NOT NULL DEFAULT 0 CHECK (llm_cost_usd >= 0),
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at     TEXT
, evidence_hash TEXT(128), evidence_sealed_at TEXT, attempt_status TEXT(30) NOT NULL DEFAULT 'active', analysis_status TEXT(30) NOT NULL DEFAULT 'not_requested');

CREATE TABLE JobProfiles (
    profile_id  INTEGER      PRIMARY KEY,
    user_id     TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    role        TEXT(255) NOT NULL,
    company     TEXT(255),
    tech_stack  TEXT       NOT NULL DEFAULT '[]',
    job_description_encrypted BLOB,
    job_description_hash TEXT(128),
    normalized_requirements TEXT NOT NULL DEFAULT '{}',
    normalized_requirements_encrypted BLOB,
    normalization_version TEXT(40),
    is_selected INTEGER     NOT NULL DEFAULT FALSE,
    created_at  TEXT   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Jobs (
    job_id           INTEGER       PRIMARY KEY,
    title            TEXT(255) NOT NULL,
    description      TEXT,
    company          TEXT(255),
    location         TEXT(255),
    salary_range     TEXT(100),
    experience_level TEXT(50),
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE LearnerSkillStates (
    state_id         INTEGER PRIMARY KEY,
    user_id          TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    skill_key        TEXT(120) NOT NULL,
    skill_category   TEXT(40) NOT NULL,
    mastery_score    REAL(5,2) NOT NULL DEFAULT 0,
    confidence_score REAL(5,2) NOT NULL DEFAULT 0,
    evidence_count   INTEGER NOT NULL DEFAULT 0,
    last_evidence_at TEXT,
    next_review_at   TEXT,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, skill_key)
);

CREATE TABLE SessionReviewEvents (
    event_id      INTEGER PRIMARY KEY,
    interview_id  TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id       TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    event_type    TEXT(50) NOT NULL,
    severity      TEXT(20) NOT NULL DEFAULT 'warning',
    payload       TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE MissionValidationEvidence (
            validation_id TEXT(64) PRIMARY KEY,
            mission_id TEXT(64) NOT NULL
                REFERENCES ImprovementMissions(mission_id) ON DELETE CASCADE,
            user_id TEXT(64) NOT NULL
                REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            analysis_id TEXT(64)
                REFERENCES SessionPerformanceAnalyses(analysis_id) ON DELETE SET NULL,
            interview_id TEXT(64)
                REFERENCES Interviews(interview_id) ON DELETE SET NULL,
            roadmap_node_id TEXT(64)
                REFERENCES ImprovementRoadmapNodes(roadmap_node_id) ON DELETE SET NULL,
            evidence_type TEXT(40) NOT NULL
                CHECK (evidence_type IN (
                    'checkpoint', 'held_out_variation', 'later_interview'
                )),
            passed INTEGER NOT NULL,
            score REAL(5,2),
            confidence REAL(5,3),
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_mission_validation_source
                UNIQUE (mission_id, evidence_type, analysis_id, interview_id, roadmap_node_id)
        );

CREATE TABLE MediaCoachingSignals (
    flag_id      INTEGER PRIMARY KEY,
    interview_id TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id      TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    flag_type    TEXT(60) NOT NULL,
    severity     TEXT(20) NOT NULL DEFAULT 'medium',
    evidence     TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ProjectKnowledgeGaps (
    gap_id        INTEGER PRIMARY KEY,
    user_id       TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    project_key   TEXT(160) NOT NULL,
    gap_key       TEXT(120) NOT NULL,
    gap_summary   TEXT NOT NULL,
    evidence      TEXT NOT NULL DEFAULT '{}',
    status        TEXT(20) NOT NULL DEFAULT 'open',
    next_check_at TEXT,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ReportArtifacts (
    artifact_id  TEXT(64) PRIMARY KEY,
    interview_id TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id      TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    analysis_id  TEXT(64) REFERENCES SessionPerformanceAnalyses(analysis_id) ON DELETE SET NULL,
    publication_key TEXT(180) NOT NULL,
    report_type  TEXT(30) NOT NULL,
    audience     TEXT(30) NOT NULL DEFAULT 'candidate',
    payload      TEXT NOT NULL DEFAULT '{}',
    payload_encrypted BLOB,
    evidence_hash TEXT(128),
    status       TEXT(30) NOT NULL DEFAULT 'ready',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TEXT
);

CREATE TABLE ReportSideEffectOutbox (
    event_id TEXT(64) PRIMARY KEY,
    idempotency_key TEXT(180) NOT NULL UNIQUE,
    publication_key TEXT(180) NOT NULL,
    event_type TEXT(60) NOT NULL DEFAULT 'improve_sync',
    analysis_id TEXT(64) NOT NULL REFERENCES SessionPerformanceAnalyses(analysis_id) ON DELETE CASCADE,
    interview_id TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT(30) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'completed', 'dead_letter')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 8 CHECK (max_attempts > 0),
    available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_owner TEXT(120),
    lease_expires_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    dead_letter_at TEXT
);

CREATE TABLE ResponseAssessments (
    assessment_id    TEXT(64) PRIMARY KEY,
    response_id      TEXT(64) NOT NULL REFERENCES InterviewResponses(response_id) ON DELETE CASCADE,
    interview_id     TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    evaluator_version TEXT(80) NOT NULL,
    evidence_hash    TEXT(128) NOT NULL,
    overall_score    REAL(5,2),
    assessment_json  TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(response_id, evaluator_version, evidence_hash)
);

CREATE TABLE ResumeProcessingJobs (
    job_id             TEXT(64) PRIMARY KEY,
    user_id            TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    job_kind           TEXT(24) NOT NULL CHECK (job_kind IN ('parse', 'enrichment')),
    content_hash       TEXT(128) NOT NULL,
    source_filename    TEXT,
    source_extension   TEXT(8),
    payload_encrypted  BLOB NOT NULL,
    result_encrypted   BLOB,
    status             TEXT(30) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'completed', 'dead_letter')),
    attempt_count      INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts       INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    available_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_owner        TEXT(120),
    lease_expires_at   TEXT,
    last_error_code    TEXT(80),
    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at       TEXT,
    dead_letter_at     TEXT,
    UNIQUE (user_id, job_kind, content_hash)
);

CREATE TABLE ResumeUploadLogs (
    id          INTEGER      PRIMARY KEY,
    user_id     TEXT(64) NOT NULL REFERENCES UserInfo(user_id),
    uploaded_at TEXT   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ResumeVersions (
    resume_id             TEXT(64) PRIMARY KEY,
    user_id               TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    version_number        INTEGER NOT NULL CHECK (version_number > 0),
    resume_text_encrypted BLOB,
    resume_json           TEXT NOT NULL DEFAULT '{}',
    content_hash          TEXT(128) NOT NULL,
    parser_version        TEXT(40),
    source_filename       TEXT,
    created_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, version_number),
    UNIQUE(user_id, content_hash)
);

CREATE TABLE SessionPerformanceAnalyses (
    analysis_id         TEXT(64) PRIMARY KEY,
    user_id             TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    interview_id        TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    mode                TEXT(20) NOT NULL,
    schema_version      TEXT(40) NOT NULL,
    evidence_hash       TEXT(128) NOT NULL,
    status              TEXT(30) NOT NULL DEFAULT 'ready',
    model               TEXT(80),
    analysis_json       TEXT NOT NULL DEFAULT '{}',
    evidence_index_json TEXT NOT NULL DEFAULT '{}',
    overall_score       REAL(5,2),
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    cached_tokens       INTEGER NOT NULL DEFAULT 0,
    estimated_cost      REAL(10,6) NOT NULL DEFAULT 0,
    latency_ms          INTEGER NOT NULL DEFAULT 0,
    evaluator_version   TEXT(80) NOT NULL DEFAULT 'session-performance-v1',
    taxonomy_version    TEXT(40) NOT NULL DEFAULT 'taxonomy-v1',
    rubric_version      TEXT(40) NOT NULL DEFAULT 'rubric-v1',
    duration_seconds    INTEGER,
    evidence_status     TEXT(30) NOT NULL DEFAULT 'sufficient',
    revision_no         INTEGER NOT NULL DEFAULT 1,
    is_current          INTEGER NOT NULL DEFAULT TRUE,
    supersedes_analysis_id TEXT(64) REFERENCES SessionPerformanceAnalyses(analysis_id) ON DELETE SET NULL,
    producer_version    TEXT(80) NOT NULL DEFAULT 'evidence-v4',
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE SkillEvidenceEvents (
    evidence_id   INTEGER PRIMARY KEY,
    user_id       TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    interview_id  TEXT(64) REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    response_id   TEXT(64) REFERENCES InterviewResponses(response_id) ON DELETE SET NULL,
    skill_key     TEXT(120) NOT NULL,
    evidence_type TEXT(50) NOT NULL,
    source_type   TEXT(50) NOT NULL,
    source_id     TEXT(160) NOT NULL,
    evaluator_version TEXT(80) NOT NULL,
    evidence_hash TEXT(128) NOT NULL,
    score_delta   REAL(5,2) NOT NULL DEFAULT 0,
    evidence      TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE TechnicalAttemptAggregates (
    interview_id TEXT(64) PRIMARY KEY REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    lifecycle_state TEXT(24) NOT NULL DEFAULT 'preparing'
        CHECK (lifecycle_state IN ('preparing', 'active', 'completed', 'expired', 'cancelled')),
    lifecycle_revision INTEGER NOT NULL DEFAULT 1,
    round_count INTEGER NOT NULL DEFAULT 0,
    open_round_count INTEGER NOT NULL DEFAULT 0,
    submitted_round_count INTEGER NOT NULL DEFAULT 0,
    round_states TEXT NOT NULL DEFAULT '[]',
    state_hash TEXT(64) NOT NULL,
    started_at TEXT,
    deadline_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (interview_id, user_id)
);

CREATE TABLE TechnicalCodeSnapshots (
    snapshot_id    TEXT(64) PRIMARY KEY,
    round_id       TEXT(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
    interview_id   TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    language       TEXT(20),
    source_chars   INTEGER NOT NULL DEFAULT 0,
    code_hash      TEXT(64),
    source_excerpt TEXT,
    source_code    TEXT,
    metadata       TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE TechnicalExecutionJobs (
            job_id TEXT(64) PRIMARY KEY,
            idempotency_key TEXT(120) NOT NULL,
            user_id TEXT(64) NOT NULL
                REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            interview_id TEXT(64) NOT NULL
                REFERENCES Interviews(interview_id) ON DELETE CASCADE,
            round_id TEXT(64) NOT NULL
                REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
            action TEXT(30) NOT NULL
                CHECK (action IN ('run', 'test', 'submit', 'validate_problem')),
            suite TEXT(30) NOT NULL DEFAULT 'visible',
            language TEXT(30) NOT NULL,
            source_code TEXT,
            source_code_encrypted BLOB,
            source_hash TEXT(128) NOT NULL,
            cases_json TEXT NOT NULL DEFAULT '[]',
            cases_encrypted BLOB,
            status TEXT(20) NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'leased', 'running', 'completed', 'failed')),
            retry_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT,
            lease_owner TEXT(128),
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            result_json TEXT NOT NULL DEFAULT '{}',
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            CONSTRAINT uq_technical_execution_idempotency
                UNIQUE (user_id, idempotency_key)
        );

CREATE TABLE TechnicalInterviewRounds (
    round_id       TEXT(64) PRIMARY KEY,
    interview_id   TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    round_type     TEXT(30) NOT NULL,
    language       TEXT(20),
    prompt         TEXT NOT NULL,
    starter_code   TEXT,
    whiteboard_json TEXT,
    metadata       TEXT NOT NULL DEFAULT '{}',
    status         TEXT(20) NOT NULL DEFAULT 'active',
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at   TEXT
);

CREATE TABLE TechnicalMistakeClusters (
    cluster_id       INTEGER PRIMARY KEY,
    user_id          TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    round_id         TEXT(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
    mistake_type     TEXT(50) NOT NULL,
    mistake_key      TEXT(120) NOT NULL,
    examples         TEXT NOT NULL DEFAULT '[]',
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    last_seen_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, mistake_key)
);

CREATE TABLE TechnicalProblemBank (
            problem_id TEXT(64) PRIMARY KEY,
            version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
            status TEXT(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'validating', 'active', 'retired', 'rejected')),
            round_type TEXT(40) NOT NULL,
            taxonomy_keys TEXT NOT NULL DEFAULT '[]',
            prerequisite_keys TEXT NOT NULL DEFAULT '[]',
            difficulty TEXT(20) NOT NULL,
            title TEXT(255) NOT NULL,
            problem_statement TEXT NOT NULL,
            license_source TEXT NOT NULL,
            spec_json TEXT NOT NULL DEFAULT '{}',
            visible_tests TEXT NOT NULL DEFAULT '[]',
            hidden_tests_encrypted BLOB,
            reference_solution_encrypted BLOB,
            expected_time_complexity TEXT(80),
            expected_space_complexity TEXT(80),
            supported_languages TEXT NOT NULL DEFAULT '[]',
            validator_version TEXT(80) NOT NULL,
            validation_result TEXT NOT NULL DEFAULT '{}',
            activated_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_problem_bank_version UNIQUE (problem_id, version)
        );

CREATE TABLE TechnicalReasoningEvidence (
    evidence_id   INTEGER PRIMARY KEY,
    user_id       TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    interview_id  TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    round_id      TEXT(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
    evidence_type TEXT(50) NOT NULL,
    content       TEXT,
    payload       TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE TechnicalRunEvents (
    run_id         TEXT(64) PRIMARY KEY,
    round_id       TEXT(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
    user_id        TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    language       TEXT(20) NOT NULL,
    source_chars   INTEGER NOT NULL DEFAULT 0,
    source_excerpt TEXT,
    source_code    TEXT,
    code_hash      TEXT(64),
    stdout         TEXT,
    stderr         TEXT,
    exit_code      INTEGER,
    error_signature TEXT(160),
    runtime_ms     INTEGER,
    metadata       TEXT NOT NULL DEFAULT '{}',
    hidden_validation_result TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE TechnicalSubmissions (
    submission_id  TEXT(64) PRIMARY KEY,
    round_id       TEXT(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
    interview_id   TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    user_id        TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    language       TEXT(20) NOT NULL,
    code_hash      TEXT(64),
    source_excerpt TEXT,
    source_code    TEXT,
    submit_number  INTEGER NOT NULL,
    visible_passed INTEGER NOT NULL DEFAULT 0,
    visible_total  INTEGER NOT NULL DEFAULT 0,
    hidden_passed  INTEGER NOT NULL DEFAULT 0,
    hidden_total   INTEGER NOT NULL DEFAULT 0,
    runtime_ms     INTEGER,
    memory_kb      INTEGER,
    status         TEXT(30) NOT NULL DEFAULT 'submitted',
    result_json    TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE TechnicalTelemetryEvents (
    event_id     INTEGER PRIMARY KEY,
    interview_id TEXT(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
    round_id     TEXT(64) REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
    user_id      TEXT(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
    event_type   TEXT(50) NOT NULL,
    payload      TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE UserInfo (
    user_id                  TEXT(64) PRIMARY KEY,
    full_name                TEXT(255),
    job_id                   INTEGER REFERENCES Jobs(job_id) ON DELETE SET NULL,
    resume_json              TEXT,
    profile_json             TEXT,
    profile_completed        INTEGER     NOT NULL DEFAULT FALSE,
    mock_interview_count     INTEGER     NOT NULL DEFAULT 0,
    practice_interview_count INTEGER     NOT NULL DEFAULT 0,
    interview_profile_type   TEXT(32) NOT NULL DEFAULT 'mid_tier',
    resume_uploaded_at       TEXT,
    updated_at               TEXT   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_created             TEXT   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE WeaknessEvidenceLinks (
            link_id TEXT(64) PRIMARY KEY,
            weakness_state_id TEXT(64) NOT NULL
                REFERENCES WeaknessStates(weakness_state_id) ON DELETE CASCADE,
            analysis_id TEXT(64) NOT NULL
                REFERENCES SessionPerformanceAnalyses(analysis_id) ON DELETE CASCADE,
            response_id TEXT(64)
                REFERENCES InterviewResponses(response_id) ON DELETE SET NULL,
            round_id TEXT(64)
                REFERENCES TechnicalInterviewRounds(round_id) ON DELETE SET NULL,
            score REAL(5,2),
            confidence REAL(5,3) NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_weakness_evidence_source
                UNIQUE (weakness_state_id, analysis_id, response_id, round_id)
        );

CREATE TABLE WeaknessStates (
            weakness_state_id TEXT(64) PRIMARY KEY,
            user_id TEXT(64) NOT NULL
                REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            skill_key TEXT(160) NOT NULL,
            taxonomy_version TEXT(40) NOT NULL,
            rubric_version TEXT(40) NOT NULL,
            lifecycle_state TEXT(30) NOT NULL
                CHECK (lifecycle_state IN (
                    'new', 'occasional', 'repeated', 'improving',
                    'worsening', 'resolved'
                )),
            observation_count INTEGER NOT NULL DEFAULT 0,
            session_count INTEGER NOT NULL DEFAULT 0,
            baseline_score REAL(5,2),
            latest_score REAL(5,2),
            confidence REAL(5,3) NOT NULL DEFAULT 0,
            root_cause_hypothesis TEXT,
            root_cause_confidence TEXT(20),
            evidence_summary TEXT NOT NULL DEFAULT '{}',
            first_observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_weakness_state_version
                UNIQUE (user_id, skill_key, taxonomy_version, rubric_version)
        );

CREATE TABLE WorkerHeartbeats (
            worker_id TEXT(128) PRIMARY KEY,
            worker_type TEXT(40) NOT NULL,
            version TEXT(80),
            metadata TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            heartbeat_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

CREATE INDEX idx_analysis_jobs_claimable
    ON AnalysisJobs (status, next_attempt_at, lease_expires_at, created_at);

CREATE INDEX idx_analysis_jobs_interview ON AnalysisJobs (interview_id, created_at DESC);

CREATE INDEX idx_analysis_stage_outputs_job ON AnalysisStageOutputs (job_id, stage_name);

CREATE INDEX idx_self_review_events_interview ON SelfReviewEvents (interview_id, created_at DESC);

CREATE INDEX idx_client_body_language_interview ON ClientBodyLanguageMetrics (interview_id, created_at DESC);

CREATE INDEX idx_coach_exercises_user_status ON CoachExercises (user_id, status, created_at DESC);

CREATE INDEX idx_code_snapshots_round ON TechnicalCodeSnapshots (round_id, created_at DESC);

CREATE INDEX idx_exercise_attempts_mission ON ExerciseAttempts (mission_id, roadmap_node_id, created_at);

CREATE INDEX idx_exercise_attempts_user ON ExerciseAttempts (user_id, created_at DESC);

CREATE INDEX idx_generated_exercises_mission ON GeneratedExercises (mission_id, roadmap_node_id);

CREATE INDEX idx_generated_exercises_user_status ON GeneratedExercises (user_id, status, created_at DESC);

CREATE INDEX idx_improve_attempt_sessions_deadline ON ImprovementAttemptSessions (user_id, status, expires_at, deadline_at);

CREATE INDEX idx_improvement_attempt_sessions_user ON ImprovementAttemptSessions (user_id, status, updated_at);

CREATE INDEX idx_improvement_events_mission_created ON ImprovementMissionEvents (mission_id, created_at);

CREATE INDEX idx_improvement_events_user_created ON ImprovementMissionEvents (user_id, created_at);

CREATE UNIQUE INDEX idx_improvement_missions_one_active_per_mode ON ImprovementMissions (user_id, mode) WHERE status = 'active';

CREATE INDEX idx_improvement_missions_user_mode_status ON ImprovementMissions (user_id, mode, status, created_at);

CREATE INDEX idx_improvement_missions_user_status ON ImprovementMissions (user_id, status, created_at);

CREATE INDEX idx_improvement_nodes_mission_order ON ImprovementRoadmapNodes (mission_id, order_index);

CREATE INDEX idx_improvement_nodes_user_availability ON ImprovementRoadmapNodes (user_id, availability_status, updated_at);

CREATE INDEX idx_improvement_skills_mission ON ImprovementMissionSkills (mission_id, skill_key);

CREATE INDEX idx_improvement_skills_user_status ON ImprovementMissionSkills (user_id, mastery_status, updated_at);

CREATE INDEX idx_interviews_created ON Interviews (created_at DESC);

CREATE INDEX idx_interviews_job_profile ON Interviews (job_profile_id);

CREATE INDEX idx_interviews_resume ON Interviews (resume_id);

CREATE INDEX idx_interviews_status ON Interviews (status);

CREATE INDEX idx_interviews_user ON Interviews (user_id);

CREATE INDEX idx_iq_blueprint_section ON InterviewQuestions (interview_id, blueprint_section_id);

CREATE INDEX idx_iq_interview ON InterviewQuestions (interview_id);

CREATE INDEX idx_iq_taxonomy_keys ON InterviewQuestions (taxonomy_keys);

CREATE INDEX idx_ir_interview ON InterviewResponses (interview_id);

CREATE UNIQUE INDEX uq_interview_response_idempotency
    ON InterviewResponses (interview_id, idempotency_key);

CREATE INDEX idx_job_profiles_user ON JobProfiles (user_id, created_at DESC);

CREATE INDEX idx_learner_skill_states_user ON LearnerSkillStates (user_id, mastery_score ASC, next_review_at ASC);

CREATE INDEX idx_session_review_events_interview ON SessionReviewEvents (interview_id, created_at DESC);

CREATE INDEX idx_media_assets_interview ON InterviewMediaAssets (interview_id, media_kind, created_at DESC);

CREATE INDEX idx_media_coaching_signals_interview ON MediaCoachingSignals (interview_id, severity, created_at DESC);

CREATE INDEX idx_project_gaps_user_status ON ProjectKnowledgeGaps (user_id, status, next_check_at ASC);

CREATE INDEX idx_report_artifact_analysis ON ReportArtifacts (analysis_id, status);

CREATE INDEX idx_report_artifacts_interview ON ReportArtifacts (interview_id, audience);

CREATE INDEX idx_report_side_effect_outbox_analysis
    ON ReportSideEffectOutbox (analysis_id, event_type);

CREATE INDEX idx_report_side_effect_outbox_claim
    ON ReportSideEffectOutbox (status, available_at, created_at);

CREATE INDEX idx_response_assessments_interview ON ResponseAssessments (interview_id, created_at DESC);

CREATE INDEX idx_resume_processing_jobs_claim
    ON ResumeProcessingJobs (status, available_at, created_at);

CREATE INDEX idx_resume_processing_jobs_user
    ON ResumeProcessingJobs (user_id, created_at DESC);

CREATE INDEX idx_resume_versions_user ON ResumeVersions (user_id, created_at DESC);

CREATE INDEX idx_rul_user_time ON ResumeUploadLogs (user_id, uploaded_at DESC);

CREATE INDEX idx_session_perf_user_mode ON SessionPerformanceAnalyses (user_id, mode, created_at);

CREATE INDEX idx_skill_evidence_user_skill ON SkillEvidenceEvents (user_id, skill_key, created_at DESC);

CREATE INDEX idx_technical_attempt_owner_state
    ON TechnicalAttemptAggregates (user_id, lifecycle_state, updated_at DESC);

CREATE INDEX idx_technical_mistakes_user ON TechnicalMistakeClusters (user_id, occurrence_count DESC, last_seen_at DESC);

CREATE INDEX idx_technical_reasoning_round ON TechnicalReasoningEvidence (round_id, created_at);

CREATE INDEX idx_technical_reasoning_user ON TechnicalReasoningEvidence (user_id, created_at);

CREATE INDEX idx_technical_rounds_interview ON TechnicalInterviewRounds (interview_id, round_type);

CREATE INDEX idx_technical_run_events_round ON TechnicalRunEvents (round_id, created_at DESC);

CREATE INDEX idx_technical_submissions_round ON TechnicalSubmissions (round_id, created_at DESC);

CREATE INDEX idx_technical_telemetry_interview ON TechnicalTelemetryEvents (interview_id, created_at DESC);

CREATE INDEX idx_userinfo_job ON UserInfo (job_id);

CREATE UNIQUE INDEX uq_analysis_job_idempotency ON AnalysisJobs (user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX uq_analysis_stage_outputs_evidence
    ON AnalysisStageOutputs (job_id, stage_name, stage_version, evidence_hash);

CREATE UNIQUE INDEX uq_evidence_manifest_current ON EvidenceManifests (interview_id) WHERE is_current;

CREATE UNIQUE INDEX uq_evidence_manifest_hash_producer
    ON EvidenceManifests (interview_id, evidence_hash, producer_version);

CREATE UNIQUE INDEX uq_evidence_manifest_revision ON EvidenceManifests (interview_id, revision_no);

CREATE UNIQUE INDEX uq_exercise_attempts_idempotency ON ExerciseAttempts (user_id, exercise_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX uq_improvement_nodes_one_current_per_mission ON ImprovementRoadmapNodes (mission_id) WHERE availability_status = 'current';

CREATE UNIQUE INDEX uq_report_artifact_publication_key ON ReportArtifacts (publication_key);

CREATE UNIQUE INDEX uq_session_performance_current
    ON SessionPerformanceAnalyses (interview_id, mode, schema_version) WHERE is_current;

CREATE UNIQUE INDEX uq_session_performance_revision
    ON SessionPerformanceAnalyses (interview_id, mode, schema_version, revision_no);

CREATE UNIQUE INDEX uq_session_performance_staged_identity
    ON SessionPerformanceAnalyses (
        interview_id, mode, schema_version, evidence_hash, producer_version
    ) WHERE status = 'staged';

CREATE UNIQUE INDEX uq_skill_evidence_source
    ON SkillEvidenceEvents (user_id, skill_key, source_type, source_id, evaluator_version);

ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS resume_payload_encrypted BLOB;
ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS facts_encrypted BLOB;
ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS derived_taxonomy TEXT NOT NULL DEFAULT '{}';
ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS is_active INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS confirmation_status TEXT NOT NULL DEFAULT 'needs_review';
ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS encryption_status TEXT NOT NULL DEFAULT 'local';
ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS updated_at TEXT;
ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS parent_resume_id TEXT;
ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS superseded_at TEXT;
ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS immutable_at TEXT;

ALTER TABLE UserInfo ADD COLUMN IF NOT EXISTS active_resume_id TEXT;

ALTER TABLE JobProfiles ADD COLUMN IF NOT EXISTS experience_level TEXT;
ALTER TABLE JobProfiles ADD COLUMN IF NOT EXISTS parser_version TEXT;

ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS questions_data_encrypted BLOB;
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS blueprint_id TEXT;
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS start_idempotency_key TEXT;
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS started_at TEXT;
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS deadline_at TEXT;
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS report_json_encrypted BLOB;
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS transcript_encrypted BLOB;
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS analysis_job_id TEXT;
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS integrity_status TEXT NOT NULL DEFAULT 'clean';
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS lifecycle_revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS recovery_deadline_at TEXT;
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS completion_kind TEXT;
ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS context_snapshot_id TEXT;

ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS question_spec_id TEXT;
ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS max_followups INTEGER NOT NULL DEFAULT 2;
ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS time_budget_seconds INTEGER;
ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS claim_ids TEXT NOT NULL DEFAULT '[]';
ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS expected_point_ids TEXT NOT NULL DEFAULT '[]';

ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS evidence_hash TEXT;
ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS answer_text_encrypted BLOB;
ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS transcript_encrypted BLOB;
ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS raw_answer_hash TEXT;
ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS input_mode TEXT NOT NULL DEFAULT 'text';
ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS timing_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS round_spec_id TEXT;
ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS problem_id TEXT;
ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS round_number INTEGER;
ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS round_spec TEXT NOT NULL DEFAULT '{}';
ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS duration_seconds INTEGER NOT NULL DEFAULT 3600;
ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS deadline_at TEXT;
ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'mock';
ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS max_submissions INTEGER NOT NULL DEFAULT 1;
ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS problem_version INTEGER;
ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS workflow_state TEXT NOT NULL DEFAULT '{}';
ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS started_at TEXT;
ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS whiteboard_encrypted BLOB;

ALTER TABLE TechnicalRunEvents ADD COLUMN IF NOT EXISTS source_code_encrypted BLOB;
ALTER TABLE TechnicalCodeSnapshots ADD COLUMN IF NOT EXISTS source_code_encrypted BLOB;
ALTER TABLE TechnicalSubmissions ADD COLUMN IF NOT EXISTS source_code_encrypted BLOB;
ALTER TABLE TechnicalSubmissions ADD COLUMN IF NOT EXISTS execution_job_id TEXT;
ALTER TABLE TechnicalProblemBank ADD COLUMN IF NOT EXISTS problem_family_id TEXT;
ALTER TABLE TechnicalReasoningEvidence ADD COLUMN IF NOT EXISTS content_encrypted BLOB;
ALTER TABLE TechnicalReasoningEvidence ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE TechnicalReasoningEvidence ADD COLUMN IF NOT EXISTS evidence_hash TEXT;
ALTER TABLE TechnicalTelemetryEvents ADD COLUMN IF NOT EXISTS payload_encrypted BLOB;
ALTER TABLE TechnicalTelemetryEvents ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

ALTER TABLE AnalysisStageOutputs ADD COLUMN IF NOT EXISTS output_encrypted BLOB;
ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS analysis_json_encrypted BLOB;
ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS evidence_index_encrypted BLOB;
ALTER TABLE ResponseAssessments ADD COLUMN IF NOT EXISTS assessment_json_encrypted BLOB;
ALTER TABLE ReportSideEffectOutbox ADD COLUMN IF NOT EXISTS payload_encrypted BLOB;
ALTER TABLE MissionValidationEvidence ADD COLUMN IF NOT EXISTS source_key TEXT;
ALTER TABLE MissionValidationEvidence ADD COLUMN IF NOT EXISTS evidence_hash TEXT;
ALTER TABLE InterviewBlueprints ADD COLUMN IF NOT EXISTS blueprint_json_encrypted BLOB;
ALTER TABLE ImprovementAttemptSessions ADD COLUMN IF NOT EXISTS draft_payload_encrypted BLOB;
ALTER TABLE ExerciseAttempts ADD COLUMN IF NOT EXISTS submitted_answer_encrypted BLOB;
ALTER TABLE ExerciseAttempts ADD COLUMN IF NOT EXISTS submitted_payload_encrypted BLOB;
ALTER TABLE ExerciseAttempts ADD COLUMN IF NOT EXISTS feedback_encrypted BLOB;
