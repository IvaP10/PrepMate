import asyncio
from unittest.mock import AsyncMock, patch

import interview
import pytest
from pydantic import ValidationError


def test_interview_round_rejects_text_input_but_technical_remains_typed():
    with pytest.raises(ValidationError, match="requires voice input"):
        interview.StartInterviewRequest(interview_type="Mock Interview", input_mode="text")

    technical = interview.StartInterviewRequest(interview_type="technical", input_mode="text")
    assert technical.input_mode == "text"

    technical_blueprint = interview.StartInterviewRequest(
        blueprint_id="technical-blueprint-1",
        input_mode="text",
    )
    assert technical_blueprint.blueprint_id == "technical-blueprint-1"
    assert technical_blueprint.input_mode == "text"


def test_disconnect_enters_durable_recovery_with_deadline():
    async def run():
        with patch.object(interview, "async_execute", new_callable=AsyncMock) as execute:
            execute.side_effect = [("interview-1",), None, None]

            await interview._mark_interview_recovering("interview-1", "user-1")
        return execute

    execute = asyncio.run(run())
    assert "status = 'recovering'" in execute.await_args_list[0].args[0]
    assert execute.await_args_list[0].kwargs["fetchone"] is True
    assert "AttemptIntegrityEvents" in execute.await_args_list[1].args[0]
    assert "connection_interrupted" in execute.await_args_list[2].args[0]


def test_expired_recovery_is_incomplete_not_scored():
    async def run():
        with patch.object(interview.settings, "SESSION_RECOVERY_GRACE_SECONDS", 0), patch.object(
            interview, "async_execute", new_callable=AsyncMock
        ) as execute:
            await interview._abandon_interview_after_recovery("interview-1", "user-1")
        return execute

    execute = asyncio.run(run())
    query = next(
        call.args[0]
        for call in execute.await_args_list
        if "status = 'cancelled'" in call.args[0]
    )
    assert "status = 'cancelled'" in query
    assert "overall_score = NULL" in query
    assert "status = 'recovering'" in query
    assert "UPDATE TechnicalInterviewRounds round" in query
    assert "round.status NOT IN ('submitted', 'completed', 'expired', 'cancelled')" in query
