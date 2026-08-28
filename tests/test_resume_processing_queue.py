from pathlib import Path

import database


ROOT = Path(__file__).resolve().parents[1]


def test_resume_queue_is_part_of_the_local_encrypted_sqlite_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERAI_DATA_DIR", str(tmp_path))
    database.close_connection_pool()
    try:
        result = database.ensure_local_schema()
        connection = database.get_db_connection()
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(ResumeProcessingJobs)").fetchall()
        }
        database.return_db_connection(connection)
    finally:
        database.close_connection_pool()

    assert result["revision"] == database.LOCAL_SCHEMA_REVISION
    assert {"payload_encrypted", "result_encrypted", "lease_owner", "lease_expires_at"} <= columns
    assert (tmp_path / "prepmate.sqlite3").is_file()
    assert "ResumeProcessingJobs" in database.REQUIRED_SCHEMA_TABLES


def test_resume_upload_enqueues_and_status_is_owner_scoped_without_api_parser_call():
    pre_interview = (ROOT / "pre_interview.py").read_text()
    worker = (ROOT / "local_worker.py").read_text()
    processor = (ROOT / "resume_processing.py").read_text()

    upload_start = pre_interview.index('@router.post("/upload-resume")')
    upload_end = pre_interview.index('@router.get("/resume-jobs/{job_id}")', upload_start)
    upload_source = pre_interview[upload_start:upload_end]
    assert "enqueue_resume_parse_job" in upload_source
    assert "status_code=status.HTTP_202_ACCEPTED" in upload_source
    assert "parse_resume_structured" not in upload_source
    assert "WHERE job_id = ? AND user_id = ?" in processor
    assert "resume_processing_worker_loop" in worker
    assert "resume_processing_worker_loop" in worker


def test_profile_enrichment_has_no_process_local_asyncio_task():
    source = (ROOT / "pre_interview.py").read_text()
    assert "asyncio.create_task" not in source
    assert "enqueue_resume_parse_job" in source
