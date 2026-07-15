#!/usr/bin/env python3
"""Run one storage-disabled, token- and cost-capped OpenAI release canary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings


def main() -> int:
    if not settings.OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY is required for the live canary")
    model = os.getenv("OPENAI_CANARY_MODEL", settings.OPENAI_EVALUATION_MODEL)
    maximum_cost = float(os.getenv("OPENAI_CANARY_MAX_COST_USD", "0.01"))
    started = time.perf_counter()
    request = {
        "model": model,
        "instructions": "Return only the exact requested sentinel and no other text.",
        "input": "Return exactly: INTERAI_CANARY_OK",
        "max_output_tokens": 128,
        "store": False,
    }
    if model.startswith("gpt-5"):
        request["reasoning"] = {"effort": "minimal"}
    response = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=20, max_retries=0).responses.create(
        **request,
    )
    usage = response.usage
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    estimated_cost = (
        input_tokens * settings.MODEL_EVALUATION_INPUT_COST_PER_M_TOKENS
        + output_tokens * settings.MODEL_EVALUATION_OUTPUT_COST_PER_M_TOKENS
    ) / 1_000_000
    output = str(response.output_text or "").strip()
    result = {
        "ok": output == "INTERAI_CANARY_OK" and estimated_cost <= maximum_cost,
        "response_id": response.id,
        "model": response.model,
        "store": bool(getattr(response, "store", False)),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(estimated_cost, 8),
        "maximum_cost_usd": maximum_cost,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] and result["store"] is False else 1


if __name__ == "__main__":
    raise SystemExit(main())
