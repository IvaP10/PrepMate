import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import interview


ROOT = Path(__file__).resolve().parents[1]


def _completion_request(**overrides):
    return interview.MediaChunkCompleteRequest(
        asset_id="6f83a21f-1553-4c1a-aeea-98f7766fd25a",
        media_kind="video",
        object_key="interviews/user-1/interview-1/video/asset-1-0.webm",
        content_type="video/webm;codecs=vp9",
        byte_size=4096,
        chunk_index=0,
        metadata={"browser_recorded": True, "untrusted": "discard-me"},
        **overrides,
    )


def test_media_completion_requires_matching_server_issued_pending_asset():
    execute = AsyncMock(side_effect=[(1,), None])
    with patch.object(interview, "async_execute", execute), patch.object(
        interview,
        "_require_raw_media_retention",
        return_value="video",
    ):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                interview.complete_media_chunk(
                    "interview-1",
                    _completion_request(),
                    {"user_id": "user-1"},
                )
            )

    assert raised.value.status_code == 409
    update_sql = execute.await_args_list[1].args[0]
    assert "status = 'pending'" in update_sql
    assert "object_key = ?" in update_sql
    assert all("INSERT INTO InterviewMediaAssets" not in call.args[0] for call in execute.await_args_list)


def test_media_completion_normalizes_content_type_and_discards_arbitrary_metadata():
    execute = AsyncMock(side_effect=[(1,), ("asset-1",)])
    with patch.object(interview, "async_execute", execute), patch.object(
        interview,
        "_require_raw_media_retention",
        return_value="video",
    ):
        result = asyncio.run(
            interview.complete_media_chunk(
                "interview-1",
                _completion_request(),
                {"user_id": "user-1"},
            )
        )

    params = execute.await_args_list[1].args[1]
    assert result["success"] is True
    assert params[8] == "video/webm"
    assert "untrusted" not in params[2]
