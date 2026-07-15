"""Encrypt legacy candidate content and enforce cache/media retention.

Revision ID: 010_privacy_retention_backfill
Revises: 009_technical_runtime_integrity
Create Date: 2026-07-12
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

from security_utils import decrypt_json, encrypt_data


revision: str = "010_privacy_retention_backfill"
down_revision: Union[str, None] = "009_technical_runtime_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_text(value: Any) -> str:
    return json.dumps(value if value is not None else {}, separators=(",", ":"), ensure_ascii=False, default=str)


def _encrypted_bytes(value: Any) -> bytes:
    return encrypt_data(_json_text(value)).encode("utf-8")


def _decoded_json(value: Any) -> Any:
    decoded = decrypt_json(value)
    return decoded if decoded is not None else {}


def _backfill_user_profiles(bind: Any) -> None:
    rows = bind.execute(sa.text(
        "SELECT user_id, resume_json, profile_json FROM UserInfo "
        "WHERE resume_json IS NOT NULL OR profile_json IS NOT NULL"
    )).mappings()
    for row in rows:
        updates: dict[str, Any] = {"user_id": row["user_id"]}
        assignments: list[str] = []
        for column in ("resume_json", "profile_json"):
            value = row[column]
            if value is None or isinstance(value, str):
                continue
            updates[column] = json.dumps(encrypt_data(_json_text(value)))
            assignments.append(f"{column} = CAST(:{column} AS JSONB)")
        if assignments:
            bind.execute(
                sa.text("UPDATE UserInfo SET " + ", ".join(assignments) + " WHERE user_id = :user_id"),
                updates,
            )


def _backfill_resume_versions(bind: Any) -> None:
    rows = bind.execute(sa.text(
        """
        SELECT resume_id, resume_json
        FROM ResumeVersions
        WHERE resume_payload_encrypted IS NULL
           OR facts_encrypted IS NULL
           OR encryption_status <> 'encrypted'
        """
    )).mappings()
    for row in rows:
        payload = _decoded_json(row["resume_json"])
        bind.execute(
            sa.text(
                """
                UPDATE ResumeVersions
                SET resume_json = CAST(:marker AS JSONB),
                    resume_payload_encrypted = COALESCE(resume_payload_encrypted, :payload),
                    facts_encrypted = COALESCE(facts_encrypted, :facts),
                    encryption_status = 'encrypted',
                    updated_at = NOW()
                WHERE resume_id = :resume_id
                """
            ),
            {
                "resume_id": row["resume_id"],
                "payload": _encrypted_bytes(payload),
                "facts": _encrypted_bytes(payload),
                "marker": _json_text({"encrypted": True}),
            },
        )


def _backfill_responses(bind: Any) -> None:
    rows = bind.execute(sa.text(
        """
        SELECT response_id, user_response, input_mode,
               answer_text_encrypted, transcript_encrypted
        FROM InterviewResponses
        WHERE user_response IS NOT NULL
          AND user_response <> ''
          AND user_response <> '[encrypted]'
        """
    )).mappings()
    bind.execute(sa.text("ALTER TABLE InterviewResponses DISABLE TRIGGER trg_interview_response_immutable"))
    try:
        for row in rows:
            encrypted = encrypt_data(str(row["user_response"])).encode("utf-8")
            bind.execute(
                sa.text(
                    """
                    UPDATE InterviewResponses
                    SET user_response = '[encrypted]',
                        answer_text_encrypted = COALESCE(answer_text_encrypted, :encrypted),
                        transcript_encrypted = CASE
                            WHEN COALESCE(input_mode, 'text') <> 'text'
                            THEN COALESCE(transcript_encrypted, :encrypted)
                            ELSE transcript_encrypted
                        END
                    WHERE response_id = :response_id
                    """
                ),
                {"response_id": row["response_id"], "encrypted": encrypted},
            )
    finally:
        bind.execute(sa.text("ALTER TABLE InterviewResponses ENABLE TRIGGER trg_interview_response_immutable"))


def _backfill_interview_reports(bind: Any) -> None:
    rows = bind.execute(sa.text(
        """
        SELECT interview_id, report_json
        FROM Interviews
        WHERE report_json_encrypted IS NULL AND report_json IS NOT NULL
        """
    )).mappings()
    for row in rows:
        report = row["report_json"] or {}
        marker = {
            "encrypted": True,
            "report_type": report.get("report_type") if isinstance(report, dict) else None,
            "schema_version": report.get("schema_version") if isinstance(report, dict) else None,
            "overall_score": report.get("overall_score") if isinstance(report, dict) else None,
        }
        bind.execute(
            sa.text(
                """
                UPDATE Interviews
                SET report_json = CAST(:marker AS JSONB),
                    report_json_encrypted = :encrypted
                WHERE interview_id = :interview_id
                """
            ),
            {
                "interview_id": row["interview_id"],
                "marker": _json_text(marker),
                "encrypted": _encrypted_bytes(report),
            },
        )


def _backfill_json_artifacts(bind: Any) -> None:
    artifact_specs = (
        ("AnalysisStageOutputs", "output_id", "output_json", "output_encrypted"),
        ("ReportArtifacts", "artifact_id", "payload", "payload_encrypted"),
    )
    for table, id_column, plain_column, encrypted_column in artifact_specs:
        rows = bind.execute(sa.text(
            f"SELECT {id_column} AS row_id, {plain_column} AS payload FROM {table} "
            f"WHERE {encrypted_column} IS NULL AND {plain_column} IS NOT NULL"
        )).mappings()
        for row in rows:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET {plain_column} = CAST(:marker AS JSONB), "
                    f"{encrypted_column} = :encrypted WHERE {id_column} = :row_id"
                ),
                {"row_id": row["row_id"], "encrypted": _encrypted_bytes(row["payload"]), "marker": _json_text({"encrypted": True})},
            )


def _backfill_blueprints(bind: Any) -> None:
    rows = bind.execute(sa.text(
        "SELECT blueprint_id, blueprint_json FROM InterviewBlueprints "
        "WHERE blueprint_json_encrypted IS NULL"
    )).mappings()
    for row in rows:
        blueprint = row["blueprint_json"] or {}
        marker = {
            "encrypted": True,
            "schema_version": blueprint.get("schema_version") if isinstance(blueprint, dict) else None,
            "profile_type": blueprint.get("profile_type") if isinstance(blueprint, dict) else None,
            "interview_type": blueprint.get("interview_type") if isinstance(blueprint, dict) else None,
        }
        bind.execute(
            sa.text(
                """
                UPDATE InterviewBlueprints
                SET blueprint_json = CAST(:marker AS JSONB),
                    blueprint_json_encrypted = :encrypted
                WHERE blueprint_id = :blueprint_id
                """
            ),
            {
                "blueprint_id": row["blueprint_id"],
                "marker": _json_text(marker),
                "encrypted": _encrypted_bytes(blueprint),
            },
        )


def _backfill_improve_answers(bind: Any) -> None:
    sessions = bind.execute(sa.text(
        "SELECT attempt_session_id, draft_payload FROM ImprovementAttemptSessions "
        "WHERE draft_payload_encrypted IS NULL AND draft_payload <> '{}'::jsonb"
    )).mappings()
    for row in sessions:
        bind.execute(
            sa.text(
                """
                UPDATE ImprovementAttemptSessions
                SET draft_payload = CAST(:marker AS JSONB),
                    draft_payload_encrypted = :encrypted
                WHERE attempt_session_id = :attempt_session_id
                """
            ),
            {
                "attempt_session_id": row["attempt_session_id"],
                "encrypted": _encrypted_bytes(row["draft_payload"]),
                "marker": _json_text({"encrypted": True, "has_draft": True}),
            },
        )

    attempts = bind.execute(sa.text(
        """
        SELECT attempt_id, submitted_answer, submitted_payload, feedback
        FROM ExerciseAttempts
        WHERE submitted_answer_encrypted IS NULL
           OR submitted_payload_encrypted IS NULL
           OR feedback_encrypted IS NULL
        """
    )).mappings()
    for row in attempts:
        answer = str(row["submitted_answer"] or "")
        payload = row["submitted_payload"] or {}
        bind.execute(
            sa.text(
                """
                UPDATE ExerciseAttempts
                SET submitted_answer = CASE WHEN submitted_answer IS NULL THEN NULL ELSE '[encrypted]' END,
                    submitted_payload = CAST(:payload_marker AS JSONB),
                    feedback = CASE WHEN feedback IS NULL THEN NULL ELSE '[encrypted]' END,
                    submitted_answer_encrypted = CASE
                        WHEN submitted_answer IS NULL OR submitted_answer = '' THEN submitted_answer_encrypted
                        ELSE COALESCE(submitted_answer_encrypted, :answer_encrypted)
                    END,
                    submitted_payload_encrypted = COALESCE(submitted_payload_encrypted, :payload_encrypted),
                    feedback_encrypted = CASE
                        WHEN feedback IS NULL OR feedback = '' THEN feedback_encrypted
                        ELSE COALESCE(feedback_encrypted, :feedback_encrypted)
                    END
                WHERE attempt_id = :attempt_id
                """
            ),
            {
                "attempt_id": row["attempt_id"],
                "answer_encrypted": encrypt_data(answer).encode("utf-8") if answer else None,
                "payload_encrypted": _encrypted_bytes(payload),
                "payload_marker": _json_text({"encrypted": True}),
                "feedback_encrypted": (
                    encrypt_data(str(row["feedback"])).encode("utf-8")
                    if row["feedback"] else None
                ),
            },
        )


def upgrade() -> None:
    for statement in (
        "ALTER TABLE InterviewBlueprints ADD COLUMN IF NOT EXISTS blueprint_json_encrypted BYTEA",
        "ALTER TABLE ImprovementAttemptSessions ADD COLUMN IF NOT EXISTS draft_payload_encrypted BYTEA",
        "ALTER TABLE ExerciseAttempts ADD COLUMN IF NOT EXISTS submitted_answer_encrypted BYTEA",
        "ALTER TABLE ExerciseAttempts ADD COLUMN IF NOT EXISTS submitted_payload_encrypted BYTEA",
        "ALTER TABLE ExerciseAttempts ADD COLUMN IF NOT EXISTS feedback_encrypted BYTEA",
    ):
        op.execute(statement)

    bind = op.get_bind()
    _backfill_user_profiles(bind)
    _backfill_resume_versions(bind)
    _backfill_responses(bind)
    _backfill_interview_reports(bind)
    _backfill_json_artifacts(bind)
    _backfill_blueprints(bind)
    _backfill_improve_answers(bind)

    op.execute("DELETE FROM LLMCache WHERE expires_at IS NULL OR expires_at <= NOW()")
    op.execute("ALTER TABLE LLMCache ALTER COLUMN expires_at SET NOT NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_cache_expiry ON LLMCache (expires_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_assets_retention "
        "ON InterviewMediaAssets (delete_after) WHERE delete_after IS NOT NULL"
    )
    op.execute(
        "INSERT INTO SchemaMigrations (migration_id) VALUES ('010_privacy_retention_backfill') "
        "ON CONFLICT (migration_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM SchemaMigrations WHERE migration_id = '010_privacy_retention_backfill'")
    op.execute("DROP INDEX IF EXISTS idx_media_assets_retention")
    op.execute("DROP INDEX IF EXISTS idx_llm_cache_expiry")
    op.execute("ALTER TABLE LLMCache ALTER COLUMN expires_at DROP NOT NULL")
    op.execute("ALTER TABLE ExerciseAttempts DROP COLUMN IF EXISTS submitted_payload_encrypted")
    op.execute("ALTER TABLE ExerciseAttempts DROP COLUMN IF EXISTS submitted_answer_encrypted")
    op.execute("ALTER TABLE ExerciseAttempts DROP COLUMN IF EXISTS feedback_encrypted")
    op.execute("ALTER TABLE ImprovementAttemptSessions DROP COLUMN IF EXISTS draft_payload_encrypted")
    op.execute("ALTER TABLE InterviewBlueprints DROP COLUMN IF EXISTS blueprint_json_encrypted")
