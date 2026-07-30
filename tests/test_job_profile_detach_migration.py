from pathlib import Path

from database import ALEMBIC_HEAD_REVISION


ROOT = Path(__file__).resolve().parents[1]


def test_job_profile_detach_migration_allows_only_nulling_the_historical_reference():
    migration = (ROOT / "migrations/alembic/versions/017_allow_job_profile_detach.py").read_text()
    performance_migration = (
        ROOT / "migrations/alembic/versions/018_performance_revision_pipeline.py"
    ).read_text()
    terminal_round_migration = (
        ROOT / "migrations/alembic/versions/019_terminal_rounds.py"
    ).read_text()
    resume_detach_migration = (
        ROOT / "migrations/alembic/versions/020_resume_version_detach.py"
    ).read_text()

    assert ALEMBIC_HEAD_REVISION == "020_resume_version_detach"
    assert 'down_revision: Union[str, None] = "017_allow_job_profile_detach"' in performance_migration
    assert 'down_revision: Union[str, None] = "018_performance_revisions"' in terminal_round_migration
    assert 'down_revision: Union[str, None] = "019_terminal_rounds"' in resume_detach_migration
    assert "AND NEW.job_profile_id IS NOT NULL" in migration
    assert "NEW.job_profile_id IS DISTINCT FROM OLD.job_profile_id" in migration
    assert "OLD.resume_id IS NOT NULL AND NEW.resume_id IS DISTINCT FROM OLD.resume_id" in migration


def test_resume_detach_migration_preserves_snapshots_and_allows_deleting_saved_versions():
    migration = (ROOT / "migrations/alembic/versions/020_resume_version_detach.py").read_text()

    assert "AttemptContextSnapshots ALTER COLUMN resume_id DROP NOT NULL" in migration
    assert '("Interviews", "fk_interviews_resume_version")' in migration
    assert '("InterviewBlueprints", "interviewblueprints_resume_id_fkey")' in migration
    assert '("AttemptContextSnapshots", "attemptcontextsnapshots_resume_id_fkey")' in migration
    assert '_replace_constraints("SET NULL")' in migration
    assert "AND NEW.resume_id IS NOT NULL" in migration
