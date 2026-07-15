"""Durable evidence, immutable interview context, and leased analysis jobs.

Revision ID: 005_evidence_pipeline
Revises: 004_dynamic_performance_pathways
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op


revision: str = "005_evidence_pipeline"
down_revision: Union[str, None] = "004_dynamic_performance_pathways"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS resume_id VARCHAR(64)")
    op.execute("ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS job_profile_id INTEGER")
    op.execute(
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS llm_cost_usd "
        "NUMERIC(10,6) NOT NULL DEFAULT 0"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_interviews_llm_cost_nonnegative'
            ) THEN
                ALTER TABLE Interviews
                    ADD CONSTRAINT ck_interviews_llm_cost_nonnegative
                    CHECK (llm_cost_usd >= 0);
            END IF;
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ResumeVersions (
            resume_id VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL CHECK (version_number > 0),
            resume_text_encrypted BYTEA,
            resume_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            content_hash VARCHAR(128) NOT NULL,
            parser_version VARCHAR(40),
            source_filename TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_resume_versions_user_version UNIQUE (user_id, version_number),
            CONSTRAINT uq_resume_versions_user_hash UNIQUE (user_id, content_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_resume_versions_user "
        "ON ResumeVersions (user_id, created_at DESC)"
    )

    op.execute("ALTER TABLE JobProfiles ADD COLUMN IF NOT EXISTS job_description_encrypted BYTEA")
    op.execute("ALTER TABLE JobProfiles ADD COLUMN IF NOT EXISTS job_description_hash VARCHAR(128)")
    op.execute(
        "ALTER TABLE JobProfiles ADD COLUMN IF NOT EXISTS normalized_requirements "
        "JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute("ALTER TABLE JobProfiles ADD COLUMN IF NOT EXISTS normalization_version VARCHAR(40)")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_interviews_resume_version'
            ) THEN
                ALTER TABLE Interviews
                    ADD CONSTRAINT fk_interviews_resume_version
                    FOREIGN KEY (resume_id) REFERENCES ResumeVersions(resume_id) ON DELETE RESTRICT;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_interviews_job_profile'
            ) THEN
                ALTER TABLE Interviews
                    ADD CONSTRAINT fk_interviews_job_profile
                    FOREIGN KEY (job_profile_id) REFERENCES JobProfiles(profile_id) ON DELETE RESTRICT;
            END IF;
        END $$
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_interviews_resume ON Interviews (resume_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_interviews_job_profile ON Interviews (job_profile_id)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_interview_context_immutability()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.resume_id IS NOT NULL AND NEW.resume_id IS DISTINCT FROM OLD.resume_id THEN
                RAISE EXCEPTION 'interview resume_id is immutable once assigned';
            END IF;
            IF OLD.job_profile_id IS NOT NULL
               AND NEW.job_profile_id IS DISTINCT FROM OLD.job_profile_id THEN
                RAISE EXCEPTION 'interview job_profile_id is immutable once assigned';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_interview_context_immutable ON Interviews")
    op.execute(
        "CREATE TRIGGER trg_interview_context_immutable "
        "BEFORE UPDATE OF resume_id, job_profile_id ON Interviews "
        "FOR EACH ROW EXECUTE FUNCTION enforce_interview_context_immutability()"
    )

    for statement in (
        "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS taxonomy_keys JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS expected_points JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS rubric_json JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS selection_reason TEXT",
        "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS blueprint_section_id VARCHAR(80)",
        "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS provenance JSONB NOT NULL DEFAULT '{}'::jsonb",
    ):
        op.execute(statement)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_iq_blueprint_section "
        "ON InterviewQuestions (interview_id, blueprint_section_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_iq_taxonomy_keys "
        "ON InterviewQuestions USING GIN (taxonomy_keys)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ResponseAssessments (
            assessment_id VARCHAR(64) PRIMARY KEY,
            response_id VARCHAR(64) NOT NULL
                REFERENCES InterviewResponses(response_id) ON DELETE CASCADE,
            interview_id VARCHAR(64) NOT NULL
                REFERENCES Interviews(interview_id) ON DELETE CASCADE,
            evaluator_version VARCHAR(80) NOT NULL,
            evidence_hash VARCHAR(128) NOT NULL,
            overall_score NUMERIC(5,2),
            assessment_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_response_assessment_evidence
                UNIQUE (response_id, evaluator_version, evidence_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_response_assessments_interview "
        "ON ResponseAssessments (interview_id, created_at DESC)"
    )

    for statement in (
        "ALTER TABLE AnalysisJobs ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE AnalysisJobs ADD COLUMN IF NOT EXISTS lease_owner VARCHAR(128)",
        "ALTER TABLE AnalysisJobs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP",
        "ALTER TABLE AnalysisJobs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP",
        "ALTER TABLE AnalysisJobs ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMP",
    ):
        op.execute(statement)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_analysis_jobs_claimable "
        "ON AnalysisJobs (status, next_attempt_at, lease_expires_at, created_at)"
    )

    op.execute("ALTER TABLE AnalysisStageOutputs ADD COLUMN IF NOT EXISTS stage_version VARCHAR(40)")
    op.execute(
        """
        WITH ranked AS (
            SELECT output_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY job_id, stage_name
                       ORDER BY created_at DESC, output_id DESC
                   ) AS version_rank
            FROM AnalysisStageOutputs
        )
        UPDATE AnalysisStageOutputs AS target
        SET stage_version = CASE
            WHEN ranked.version_rank = 1 THEN 'v1'
            ELSE 'legacy-' || SUBSTRING(MD5(target.output_id), 1, 20)
        END
        FROM ranked
        WHERE target.output_id = ranked.output_id
          AND target.stage_version IS NULL
        """
    )
    op.execute("ALTER TABLE AnalysisStageOutputs ALTER COLUMN stage_version SET DEFAULT 'v1'")
    op.execute("ALTER TABLE AnalysisStageOutputs ALTER COLUMN stage_version SET NOT NULL")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_stage_outputs_version "
        "ON AnalysisStageOutputs (job_id, stage_name, stage_version)"
    )

    for statement in (
        "ALTER TABLE SkillEvidenceEvents ADD COLUMN IF NOT EXISTS source_type VARCHAR(50)",
        "ALTER TABLE SkillEvidenceEvents ADD COLUMN IF NOT EXISTS source_id VARCHAR(160)",
        "ALTER TABLE SkillEvidenceEvents ADD COLUMN IF NOT EXISTS evaluator_version VARCHAR(80)",
        "ALTER TABLE SkillEvidenceEvents ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR(128)",
    ):
        op.execute(statement)
    op.execute(
        """
        UPDATE SkillEvidenceEvents
        SET source_type = COALESCE(
                source_type,
                CASE WHEN evidence_type = 'interview_turn'
                     THEN 'interview_response'
                     ELSE evidence_type END
            ),
            evaluator_version = COALESCE(evaluator_version, 'learning-evidence-v1'),
            evidence_hash = COALESCE(
                evidence_hash,
                MD5(CONCAT_WS('|', score_delta::text, evidence::text))
            )
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT evidence_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id, skill_key, source_type, response_id
                       ORDER BY created_at ASC, evidence_id ASC
                   ) AS source_rank
            FROM SkillEvidenceEvents
        )
        UPDATE SkillEvidenceEvents AS target
        SET source_id = CASE
            WHEN target.response_id IS NOT NULL AND ranked.source_rank = 1
                THEN target.response_id
            ELSE 'legacy:' || target.evidence_id::text
        END
        FROM ranked
        WHERE target.evidence_id = ranked.evidence_id
          AND target.source_id IS NULL
        """
    )
    for column in ("source_type", "source_id", "evaluator_version", "evidence_hash"):
        op.execute(f"ALTER TABLE SkillEvidenceEvents ALTER COLUMN {column} SET NOT NULL")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_evidence_source "
        "ON SkillEvidenceEvents (user_id, skill_key, source_type, source_id, evaluator_version)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS AIUsageReservations (
            reservation_id VARCHAR(64) PRIMARY KEY,
            interview_id VARCHAR(64) NOT NULL
                REFERENCES Interviews(interview_id) ON DELETE CASCADE,
            user_id VARCHAR(64) NOT NULL
                REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            event_type VARCHAR(80) NOT NULL,
            estimated_cost NUMERIC(10,6) NOT NULL,
            actual_cost NUMERIC(10,6),
            status VARCHAR(20) NOT NULL DEFAULT 'reserved',
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            settled_at TIMESTAMP,
            CONSTRAINT ck_ai_usage_estimated_cost_nonnegative CHECK (estimated_cost >= 0),
            CONSTRAINT ck_ai_usage_actual_cost_nonnegative
                CHECK (actual_cost IS NULL OR actual_cost >= 0),
            CONSTRAINT ck_ai_usage_reservation_status
                CHECK (status IN ('reserved', 'settled', 'released'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_usage_reservations_interview "
        "ON AIUsageReservations (interview_id, status, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_usage_reservations_user "
        "ON AIUsageReservations (user_id, created_at DESC)"
    )

    # Resume versions keep immutable encrypted source payloads while derived,
    # non-sensitive taxonomy remains queryable.
    for statement in (
        "ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS resume_payload_encrypted BYTEA",
        "ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS facts_encrypted BYTEA",
        "ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS derived_taxonomy JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS confirmation_status VARCHAR(30) NOT NULL DEFAULT 'needs_review'",
        "ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS encryption_status VARCHAR(30) NOT NULL DEFAULT 'encrypted'",
        "ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW()",
        "ALTER TABLE UserInfo ADD COLUMN IF NOT EXISTS active_resume_id VARCHAR(64)",
        "ALTER TABLE JobProfiles ADD COLUMN IF NOT EXISTS experience_level VARCHAR(40)",
        "ALTER TABLE JobProfiles ADD COLUMN IF NOT EXISTS parser_version VARCHAR(40)",
    ):
        op.execute(statement)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_resume_versions_one_active "
        "ON ResumeVersions (user_id) WHERE is_active"
    )
    op.execute(
        """
        INSERT INTO ResumeVersions (
            resume_id, user_id, version_number, resume_text_encrypted,
            resume_json, content_hash, parser_version, source_filename,
            is_active, confirmation_status, encryption_status, created_at, updated_at
        )
        SELECT 'legacy-' || SUBSTRING(MD5(ui.user_id), 1, 40),
               ui.user_id,
               1,
               ui.resume_text_encrypted,
               COALESCE(ui.resume_json, '{}'::jsonb),
               MD5(
                   COALESCE(ui.resume_json::text, '') || ':' ||
                   COALESCE(ENCODE(ui.resume_text_encrypted, 'hex'), '')
               ),
               'legacy-v1',
               'Imported resume',
               TRUE,
               'confirmed',
               'legacy_pending',
               COALESCE(ui.resume_uploaded_at, ui.date_created, NOW()),
               COALESCE(ui.updated_at, NOW())
        FROM UserInfo ui
        WHERE ui.resume_json IS NOT NULL OR ui.resume_text_encrypted IS NOT NULL
        ON CONFLICT (user_id, version_number) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE UserInfo ui
        SET active_resume_id = rv.resume_id
        FROM ResumeVersions rv
        WHERE rv.user_id = ui.user_id
          AND rv.is_active
          AND ui.active_resume_id IS NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_userinfo_active_resume'
            ) THEN
                ALTER TABLE UserInfo
                    ADD CONSTRAINT fk_userinfo_active_resume
                    FOREIGN KEY (active_resume_id)
                    REFERENCES ResumeVersions(resume_id) ON DELETE SET NULL;
            END IF;
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS InterviewBlueprints (
            blueprint_id VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL
                REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            resume_id VARCHAR(64)
                REFERENCES ResumeVersions(resume_id) ON DELETE RESTRICT,
            job_profile_id INTEGER
                REFERENCES JobProfiles(profile_id) ON DELETE RESTRICT,
            interview_mode VARCHAR(20) NOT NULL,
            interview_type VARCHAR(50) NOT NULL,
            experience_level VARCHAR(40),
            difficulty_level VARCHAR(20) NOT NULL DEFAULT 'adaptive',
            duration_minutes INTEGER NOT NULL CHECK (duration_minutes BETWEEN 10 AND 120),
            focus JSONB NOT NULL DEFAULT '["mixed"]'::jsonb,
            round_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            blueprint_json JSONB NOT NULL,
            settings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            blueprint_hash VARCHAR(128) NOT NULL,
            compiler_version VARCHAR(80) NOT NULL,
            request_idempotency_key VARCHAR(120),
            status VARCHAR(20) NOT NULL DEFAULT 'ready'
                CHECK (status IN ('draft', 'ready', 'consumed', 'expired')),
            expires_at TIMESTAMP,
            consumed_at TIMESTAMP,
            consumed_by_interview_id VARCHAR(64)
                REFERENCES Interviews(interview_id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_blueprint_owner_hash UNIQUE (user_id, blueprint_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_blueprints_user_status "
        "ON InterviewBlueprints (user_id, status, created_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_blueprints_request_idempotency "
        "ON InterviewBlueprints (user_id, request_idempotency_key) "
        "WHERE request_idempotency_key IS NOT NULL"
    )
    for statement in (
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS blueprint_id VARCHAR(64)",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS start_idempotency_key VARCHAR(120)",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS deadline_at TIMESTAMP",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS report_json_encrypted BYTEA",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS transcript_encrypted BYTEA",
    ):
        op.execute(statement)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_interviews_blueprint'
            ) THEN
                ALTER TABLE Interviews
                    ADD CONSTRAINT fk_interviews_blueprint
                    FOREIGN KEY (blueprint_id)
                    REFERENCES InterviewBlueprints(blueprint_id) ON DELETE RESTRICT;
            END IF;
        END $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_interviews_blueprint ON Interviews (blueprint_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_interview_start_idempotency "
        "ON Interviews (user_id, start_idempotency_key) "
        "WHERE start_idempotency_key IS NOT NULL"
    )
    op.execute(
        """
        INSERT INTO InterviewBlueprints (
            blueprint_id, user_id, resume_id, job_profile_id,
            interview_mode, interview_type, difficulty_level,
            duration_minutes, focus, round_config, blueprint_json,
            settings_json, blueprint_hash, compiler_version, status,
            consumed_at, consumed_by_interview_id, created_at
        )
        SELECT 'legacy-' || i.interview_id,
               i.user_id,
               i.resume_id,
               i.job_profile_id,
               i.interview_mode,
               i.interview_type,
               COALESCE(i.settings ->> 'difficulty_level', 'adaptive'),
               GREATEST(
                   10,
                   LEAST(
                       120,
                       COALESCE(
                           NULLIF(i.settings #>> '{duration,max_minutes}', '')::INTEGER,
                           NULLIF(i.settings ->> 'duration_minutes', '')::INTEGER,
                           30
                       )
                   )
               ),
               COALESCE(i.settings -> 'focus', '["mixed"]'::jsonb),
               COALESCE(i.settings -> 'technical', '{}'::jsonb),
               JSONB_BUILD_OBJECT(
                   'schema_version', 'legacy_snapshot_v1',
                   'battlegrounds', COALESCE(i.questions_data -> 'battlegrounds', '[]'::jsonb),
                   'legacy_questions_data', COALESCE(i.questions_data, '{}'::jsonb)
               ),
               COALESCE(i.settings, '{}'::jsonb),
               MD5(
                   COALESCE(i.questions_data::text, '{}') || ':' ||
                   COALESCE(i.settings::text, '{}')
               ),
               'legacy-snapshot-v1',
               'consumed',
               COALESCE(i.completed_at, i.created_at),
               i.interview_id,
               i.created_at
        FROM Interviews i
        WHERE i.blueprint_id IS NULL
        ON CONFLICT (blueprint_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE Interviews
        SET blueprint_id = 'legacy-' || interview_id,
            started_at = COALESCE(started_at, created_at)
        WHERE blueprint_id IS NULL
        """
    )

    for statement in (
        "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS question_spec_id VARCHAR(80)",
        "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS max_followups INTEGER NOT NULL DEFAULT 2",
        "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS time_budget_seconds INTEGER",
        "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS claim_ids JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE InterviewQuestions ADD COLUMN IF NOT EXISTS expected_point_ids JSONB NOT NULL DEFAULT '[]'::jsonb",
    ):
        op.execute(statement)
    op.execute(
        """
        UPDATE InterviewQuestions
        SET question_spec_id = COALESCE(question_spec_id, question_id),
            blueprint_section_id = COALESCE(
                blueprint_section_id,
                'legacy-' || question_order::text
            ),
            expected_point_ids = CASE
                WHEN expected_point_ids = '[]'::jsonb
                    THEN COALESCE(expected_points, '[]'::jsonb)
                ELSE expected_point_ids
            END
        WHERE question_spec_id IS NULL
           OR blueprint_section_id IS NULL
           OR expected_point_ids = '[]'::jsonb
        """
    )
    op.execute(
        "ALTER TABLE InterviewQuestions ALTER COLUMN question_spec_id SET NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_question_spec_interview "
        "ON InterviewQuestions (interview_id, question_spec_id)"
    )

    for statement in (
        "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120)",
        "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR(128)",
        "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS answer_text_encrypted BYTEA",
        "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS transcript_encrypted BYTEA",
        "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS raw_answer_hash VARCHAR(128)",
        "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS input_mode VARCHAR(20) NOT NULL DEFAULT 'text'",
        "ALTER TABLE InterviewResponses ADD COLUMN IF NOT EXISTS timing_json JSONB NOT NULL DEFAULT '{}'::jsonb",
    ):
        op.execute(statement)
    op.execute(
        """
        UPDATE InterviewResponses
        SET idempotency_key = COALESCE(idempotency_key, 'legacy:' || response_id),
            evidence_hash = COALESCE(
                evidence_hash,
                MD5(
                    COALESCE(question_id, '') || ':' ||
                    COALESCE(user_response, '') || ':' ||
                    COALESCE(response_time_seconds::text, '')
                )
            ),
            raw_answer_hash = COALESCE(raw_answer_hash, MD5(COALESCE(user_response, '')))
        """
    )
    op.execute(
        "ALTER TABLE InterviewResponses ALTER COLUMN idempotency_key SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE InterviewResponses ALTER COLUMN evidence_hash SET NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_interview_response_idempotency "
        "ON InterviewResponses (interview_id, idempotency_key)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_interview_response_evidence()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.interview_id IS DISTINCT FROM OLD.interview_id
               OR NEW.question_id IS DISTINCT FROM OLD.question_id
               OR NEW.user_response IS DISTINCT FROM OLD.user_response
               OR NEW.response_time_seconds IS DISTINCT FROM OLD.response_time_seconds
               OR NEW.nonverbal_metrics IS DISTINCT FROM OLD.nonverbal_metrics
               OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
               OR NEW.answer_text_encrypted IS DISTINCT FROM OLD.answer_text_encrypted
               OR NEW.transcript_encrypted IS DISTINCT FROM OLD.transcript_encrypted
               OR NEW.raw_answer_hash IS DISTINCT FROM OLD.raw_answer_hash
               OR NEW.input_mode IS DISTINCT FROM OLD.input_mode
               OR NEW.timing_json IS DISTINCT FROM OLD.timing_json
            THEN
                RAISE EXCEPTION 'raw interview response evidence is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_interview_response_immutable ON InterviewResponses")
    op.execute(
        "CREATE TRIGGER trg_interview_response_immutable "
        "BEFORE UPDATE ON InterviewResponses "
        "FOR EACH ROW EXECUTE FUNCTION protect_interview_response_evidence()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_response_assessment_updates()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'response assessments are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_response_assessment_append_only ON ResponseAssessments")
    op.execute(
        "CREATE TRIGGER trg_response_assessment_append_only "
        "BEFORE UPDATE ON ResponseAssessments "
        "FOR EACH ROW EXECUTE FUNCTION protect_response_assessment_updates()"
    )
    op.execute(
        """
        INSERT INTO ResponseAssessments (
            assessment_id, response_id, interview_id, evaluator_version,
            evidence_hash, overall_score, assessment_json, created_at
        )
        SELECT 'legacy-' || ir.response_id,
               ir.response_id,
               ir.interview_id,
               'legacy-response-v1',
               ir.evidence_hash,
               ir.score,
               JSONB_BUILD_OBJECT(
                   'legacy', TRUE,
                   'authoritative', FALSE,
                   'evaluation', COALESCE(ir.evaluation_json, '{}'::jsonb)
               ),
               ir.created_at
        FROM InterviewResponses ir
        WHERE ir.evaluation_json IS NOT NULL
        ON CONFLICT (response_id, evaluator_version, evidence_hash) DO NOTHING
        """
    )

    for statement in (
        "ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS evaluator_version VARCHAR(80) NOT NULL DEFAULT 'session-performance-v1'",
        "ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS taxonomy_version VARCHAR(40) NOT NULL DEFAULT 'taxonomy-v1'",
        "ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS rubric_version VARCHAR(40) NOT NULL DEFAULT 'rubric-v1'",
        "ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS duration_seconds INTEGER",
        "ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS evidence_status VARCHAR(30) NOT NULL DEFAULT 'sufficient'",
    ):
        op.execute(statement)
    op.execute(
        """
        INSERT INTO SessionPerformanceAnalyses (
            analysis_id, user_id, interview_id, mode, schema_version,
            evidence_hash, status, analysis_json, evidence_index_json,
            overall_score, evaluator_version, taxonomy_version,
            rubric_version, duration_seconds, evidence_status,
            created_at, updated_at
        )
        SELECT 'legacy-' || i.interview_id,
               i.user_id,
               i.interview_id,
               CASE
                   WHEN LOWER(COALESCE(i.interview_type, '')) LIKE '%technical%'
                       THEN 'technical'
                   ELSE 'mock'
               END,
               'legacy-report-v1',
               MD5(COALESCE(i.report_json::text, '{}')),
               'ready',
               i.report_json,
               '{}'::jsonb,
               i.overall_score,
               'legacy-report-v1',
               'legacy',
               'legacy',
               i.duration_seconds,
               CASE WHEN i.overall_score IS NULL THEN 'insufficient_evidence' ELSE 'legacy' END,
               COALESCE(i.completed_at, i.created_at),
               COALESCE(i.completed_at, i.created_at)
        FROM Interviews i
        WHERE i.report_json IS NOT NULL
        ON CONFLICT (interview_id, mode, schema_version) DO NOTHING
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS WeaknessStates (
            weakness_state_id VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL
                REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            skill_key VARCHAR(160) NOT NULL,
            taxonomy_version VARCHAR(40) NOT NULL,
            rubric_version VARCHAR(40) NOT NULL,
            lifecycle_state VARCHAR(30) NOT NULL
                CHECK (lifecycle_state IN (
                    'new', 'occasional', 'repeated', 'improving',
                    'worsening', 'resolved'
                )),
            observation_count INTEGER NOT NULL DEFAULT 0,
            session_count INTEGER NOT NULL DEFAULT 0,
            baseline_score NUMERIC(5,2),
            latest_score NUMERIC(5,2),
            confidence NUMERIC(5,3) NOT NULL DEFAULT 0,
            root_cause_hypothesis TEXT,
            root_cause_confidence VARCHAR(20),
            evidence_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            first_observed_at TIMESTAMP NOT NULL DEFAULT NOW(),
            last_observed_at TIMESTAMP NOT NULL DEFAULT NOW(),
            resolved_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_weakness_state_version
                UNIQUE (user_id, skill_key, taxonomy_version, rubric_version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS WeaknessEvidenceLinks (
            link_id VARCHAR(64) PRIMARY KEY,
            weakness_state_id VARCHAR(64) NOT NULL
                REFERENCES WeaknessStates(weakness_state_id) ON DELETE CASCADE,
            analysis_id VARCHAR(64) NOT NULL
                REFERENCES SessionPerformanceAnalyses(analysis_id) ON DELETE CASCADE,
            response_id VARCHAR(64)
                REFERENCES InterviewResponses(response_id) ON DELETE SET NULL,
            round_id VARCHAR(64)
                REFERENCES TechnicalInterviewRounds(round_id) ON DELETE SET NULL,
            score NUMERIC(5,2),
            confidence NUMERIC(5,3) NOT NULL,
            evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_weakness_evidence_source
                UNIQUE (weakness_state_id, analysis_id, response_id, round_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_weakness_states_user_lifecycle "
        "ON WeaknessStates (user_id, lifecycle_state, last_observed_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS TechnicalProblemBank (
            problem_id VARCHAR(64) PRIMARY KEY,
            version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
            status VARCHAR(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'validating', 'active', 'retired', 'rejected')),
            round_type VARCHAR(40) NOT NULL,
            taxonomy_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
            prerequisite_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
            difficulty VARCHAR(20) NOT NULL,
            title VARCHAR(255) NOT NULL,
            problem_statement TEXT NOT NULL,
            license_source TEXT NOT NULL,
            spec_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            visible_tests JSONB NOT NULL DEFAULT '[]'::jsonb,
            hidden_tests_encrypted BYTEA,
            reference_solution_encrypted BYTEA,
            expected_time_complexity VARCHAR(80),
            expected_space_complexity VARCHAR(80),
            supported_languages JSONB NOT NULL DEFAULT '[]'::jsonb,
            validator_version VARCHAR(80) NOT NULL,
            validation_result JSONB NOT NULL DEFAULT '{}'::jsonb,
            activated_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_problem_bank_version UNIQUE (problem_id, version)
        )
        """
    )
    for statement in (
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS round_spec_id VARCHAR(80)",
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS problem_id VARCHAR(64)",
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS round_number INTEGER",
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS round_spec JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS duration_seconds INTEGER NOT NULL DEFAULT 3600",
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS deadline_at TIMESTAMP",
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS mode VARCHAR(20) NOT NULL DEFAULT 'mock'",
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS max_submissions INTEGER NOT NULL DEFAULT 1",
    ):
        op.execute(statement)
    op.execute(
        """
        WITH ranked AS (
            SELECT round_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY interview_id
                       ORDER BY created_at, round_id
                   ) AS round_number
            FROM TechnicalInterviewRounds
        )
        UPDATE TechnicalInterviewRounds target
        SET round_number = ranked.round_number,
            round_spec_id = COALESCE(target.round_spec_id, target.round_id),
            deadline_at = COALESCE(
                target.deadline_at,
                target.created_at + (target.duration_seconds * INTERVAL '1 second')
            )
        FROM ranked
        WHERE target.round_id = ranked.round_id
          AND (
              target.round_number IS NULL
              OR target.round_spec_id IS NULL
              OR target.deadline_at IS NULL
          )
        """
    )
    op.execute(
        "ALTER TABLE TechnicalInterviewRounds ALTER COLUMN round_number SET NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_technical_round_number "
        "ON TechnicalInterviewRounds (interview_id, round_number)"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_technical_round_problem'
            ) THEN
                ALTER TABLE TechnicalInterviewRounds
                    ADD CONSTRAINT fk_technical_round_problem
                    FOREIGN KEY (problem_id)
                    REFERENCES TechnicalProblemBank(problem_id) ON DELETE RESTRICT;
            END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS TechnicalExecutionJobs (
            job_id VARCHAR(64) PRIMARY KEY,
            idempotency_key VARCHAR(120) NOT NULL,
            user_id VARCHAR(64) NOT NULL
                REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            interview_id VARCHAR(64) NOT NULL
                REFERENCES Interviews(interview_id) ON DELETE CASCADE,
            round_id VARCHAR(64) NOT NULL
                REFERENCES TechnicalInterviewRounds(round_id) ON DELETE CASCADE,
            action VARCHAR(30) NOT NULL
                CHECK (action IN ('run', 'test', 'submit', 'validate_problem')),
            suite VARCHAR(30) NOT NULL DEFAULT 'visible',
            language VARCHAR(30) NOT NULL,
            source_code TEXT,
            source_code_encrypted BYTEA,
            source_hash VARCHAR(128) NOT NULL,
            cases_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            cases_encrypted BYTEA,
            status VARCHAR(20) NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'leased', 'running', 'completed', 'failed')),
            retry_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMP,
            lease_owner VARCHAR(128),
            lease_expires_at TIMESTAMP,
            heartbeat_at TIMESTAMP,
            result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_message TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMP,
            CONSTRAINT uq_technical_execution_idempotency
                UNIQUE (user_id, idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_technical_execution_claimable "
        "ON TechnicalExecutionJobs "
        "(status, next_attempt_at, lease_expires_at, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_technical_execution_round "
        "ON TechnicalExecutionJobs (round_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS WorkerHeartbeats (
            worker_id VARCHAR(128) PRIMARY KEY,
            worker_type VARCHAR(40) NOT NULL,
            version VARCHAR(80),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            started_at TIMESTAMP NOT NULL DEFAULT NOW(),
            heartbeat_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_type "
        "ON WorkerHeartbeats (worker_type, heartbeat_at DESC)"
    )

    for statement in (
        "ALTER TABLE AnalysisJobs ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(160)",
        "ALTER TABLE AnalysisJobs ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR(128)",
        "ALTER TABLE AnalysisStageOutputs ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR(128)",
    ):
        op.execute(statement)
    op.execute(
        """
        UPDATE AnalysisJobs
        SET idempotency_key = COALESCE(
                idempotency_key,
                'legacy:' || job_id
            ),
            evidence_hash = COALESCE(evidence_hash, MD5(interview_id))
        """
    )
    op.execute(
        """
        UPDATE AnalysisStageOutputs
        SET evidence_hash = COALESCE(evidence_hash, MD5(output_json::text))
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_job_idempotency "
        "ON AnalysisJobs (user_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )

    for statement in (
        "ALTER TABLE AIUsageReservations ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(160)",
        "ALTER TABLE AIUsageReservations ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP",
        "ALTER TABLE ImprovementMissions ADD COLUMN IF NOT EXISTS held_out_checkpoint_id VARCHAR(64)",
        "ALTER TABLE ImprovementMissions ADD COLUMN IF NOT EXISTS validation_analysis_id VARCHAR(64)",
        "ALTER TABLE ImprovementMissions ADD COLUMN IF NOT EXISTS later_interview_id VARCHAR(64)",
        "ALTER TABLE ReportArtifacts ADD COLUMN IF NOT EXISTS payload_encrypted BYTEA",
        "ALTER TABLE TechnicalRunEvents ADD COLUMN IF NOT EXISTS source_code_encrypted BYTEA",
        "ALTER TABLE TechnicalCodeSnapshots ADD COLUMN IF NOT EXISTS source_code_encrypted BYTEA",
        "ALTER TABLE TechnicalSubmissions ADD COLUMN IF NOT EXISTS source_code_encrypted BYTEA",
    ):
        op.execute(statement)
    op.execute(
        """
        UPDATE AIUsageReservations
        SET idempotency_key = COALESCE(idempotency_key, reservation_id),
            expires_at = COALESCE(expires_at, created_at + INTERVAL '10 minutes')
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_usage_reservation_idempotency "
        "ON AIUsageReservations (interview_id, idempotency_key)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS MissionValidationEvidence (
            validation_id VARCHAR(64) PRIMARY KEY,
            mission_id VARCHAR(64) NOT NULL
                REFERENCES ImprovementMissions(mission_id) ON DELETE CASCADE,
            user_id VARCHAR(64) NOT NULL
                REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            analysis_id VARCHAR(64)
                REFERENCES SessionPerformanceAnalyses(analysis_id) ON DELETE SET NULL,
            interview_id VARCHAR(64)
                REFERENCES Interviews(interview_id) ON DELETE SET NULL,
            roadmap_node_id VARCHAR(64)
                REFERENCES ImprovementRoadmapNodes(roadmap_node_id) ON DELETE SET NULL,
            evidence_type VARCHAR(40) NOT NULL
                CHECK (evidence_type IN (
                    'checkpoint', 'held_out_variation', 'later_interview'
                )),
            passed BOOLEAN NOT NULL,
            score NUMERIC(5,2),
            confidence NUMERIC(5,3),
            evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_mission_validation_source
                UNIQUE (mission_id, evidence_type, analysis_id, interview_id, roadmap_node_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mission_validation_mission "
        "ON MissionValidationEvidence (mission_id, created_at DESC)"
    )

    op.execute(
        "INSERT INTO SchemaMigrations (migration_id) "
        "VALUES ('005_evidence_pipeline') ON CONFLICT (migration_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM SchemaMigrations WHERE migration_id = '005_evidence_pipeline'")
    op.execute("DROP TABLE IF EXISTS AIUsageReservations")

    op.execute("DROP INDEX IF EXISTS uq_skill_evidence_source")
    for column in ("evidence_hash", "evaluator_version", "source_id", "source_type"):
        op.execute(f"ALTER TABLE SkillEvidenceEvents DROP COLUMN IF EXISTS {column}")

    op.execute("DROP INDEX IF EXISTS uq_analysis_stage_outputs_version")
    op.execute("ALTER TABLE AnalysisStageOutputs DROP COLUMN IF EXISTS stage_version")

    op.execute("DROP INDEX IF EXISTS idx_analysis_jobs_claimable")
    for column in ("next_attempt_at", "heartbeat_at", "lease_expires_at", "lease_owner"):
        op.execute(f"ALTER TABLE AnalysisJobs DROP COLUMN IF EXISTS {column}")

    op.execute("DROP TABLE IF EXISTS ResponseAssessments")
    op.execute("DROP INDEX IF EXISTS idx_iq_taxonomy_keys")
    op.execute("DROP INDEX IF EXISTS idx_iq_blueprint_section")
    for column in (
        "provenance",
        "blueprint_section_id",
        "selection_reason",
        "rubric_json",
        "expected_points",
        "taxonomy_keys",
    ):
        op.execute(f"ALTER TABLE InterviewQuestions DROP COLUMN IF EXISTS {column}")

    op.execute("ALTER TABLE Interviews DROP CONSTRAINT IF EXISTS fk_interviews_job_profile")
    op.execute("ALTER TABLE Interviews DROP CONSTRAINT IF EXISTS fk_interviews_resume_version")
    op.execute("DROP TRIGGER IF EXISTS trg_interview_context_immutable ON Interviews")
    op.execute("DROP FUNCTION IF EXISTS enforce_interview_context_immutability()")
    op.execute("DROP INDEX IF EXISTS idx_interviews_job_profile")
    op.execute("DROP INDEX IF EXISTS idx_interviews_resume")
    op.execute("ALTER TABLE Interviews DROP COLUMN IF EXISTS job_profile_id")
    op.execute("ALTER TABLE Interviews DROP COLUMN IF EXISTS resume_id")

    for column in (
        "normalization_version",
        "normalized_requirements",
        "job_description_hash",
        "job_description_encrypted",
    ):
        op.execute(f"ALTER TABLE JobProfiles DROP COLUMN IF EXISTS {column}")
    op.execute("DROP TABLE IF EXISTS ResumeVersions")
