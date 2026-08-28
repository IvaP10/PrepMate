"""Local background worker for report, technical execution, and resume jobs."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import uuid

from database import close_connection_pool, init_connection_pool, verify_local_schema

logger = logging.getLogger("prepmate.local_worker")


def _worker_id(role: str) -> str:
    return f"local-{role}:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


async def _technical_loop(stop_event: asyncio.Event, worker_id: str) -> None:
    from technical_worker import run_once

    while not stop_event.is_set():
        worked = await run_once(worker_id)
        if not worked:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=0.25)
            except asyncio.TimeoutError:
                pass


async def run_local_workers(stop_event: asyncio.Event | None = None) -> None:
    from analysis_pipeline import analysis_worker_loop
    from local_maintenance import maintenance_loop
    from resume_processing import resume_processing_worker_loop

    stop = stop_event or asyncio.Event()
    await asyncio.gather(
        analysis_worker_loop(_worker_id("analysis"), stop_event=stop, idle_seconds=0.5),
        _technical_loop(stop, _worker_id("technical")),
        resume_processing_worker_loop(_worker_id("resume"), stop_event=stop, idle_seconds=0.5),
        maintenance_loop(stop),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PrepMate's local background workers")
    parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    init_connection_pool()
    verify_local_schema()
    try:
        try:
            asyncio.run(run_local_workers())
        except KeyboardInterrupt:
            pass
    finally:
        close_connection_pool()


if __name__ == "__main__":
    main()
