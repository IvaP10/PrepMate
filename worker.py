"""Combined durable-job worker process.

The API only commits analysis and technical execution jobs.  This process owns
their leases and heartbeats, so an API restart cannot lose or double-execute
committed work.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
import uuid
from collections.abc import Awaitable, Callable
from typing import Optional

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "key.env"))

from database import (  # noqa: E402
    close_connection_pool,
    init_connection_pool,
    verify_schema_migrations,
)
from observability import init_observability  # noqa: E402
from redis_client import close_redis, init_redis_client  # noqa: E402


logger = logging.getLogger("interai.worker")

AnalysisLoop = Callable[..., Awaitable[None]]
TechnicalLoop = Callable[..., Awaitable[None]]


def _process_identity(role: str, configured: Optional[str] = None) -> str:
    chosen = str(configured or "").strip()
    if chosen:
        return chosen[:128]
    return f"{role}:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"[:128]


async def supervise_workers(
    *,
    stop_event: asyncio.Event,
    analysis_worker_id: str,
    technical_worker_id: str,
    analysis_loop: Optional[AnalysisLoop] = None,
    technical_loop: Optional[TechnicalLoop] = None,
) -> None:
    """Run both durable consumers; fail the process if either exits unexpectedly."""
    if analysis_loop is None:
        from analysis_pipeline import analysis_worker_loop

        analysis_loop = analysis_worker_loop
    if technical_loop is None:
        from technical_worker import serve

        technical_loop = serve

    tasks = {
        "analysis": asyncio.create_task(
            analysis_loop(analysis_worker_id, stop_event=stop_event, idle_seconds=0.5),
            name="analysis-worker",
        ),
        "technical": asyncio.create_task(
            technical_loop(technical_worker_id, poll_seconds=0.25),
            name="technical-worker",
        ),
    }
    stop_task = asyncio.create_task(stop_event.wait(), name="worker-stop-signal")
    try:
        done, _ = await asyncio.wait(
            [*tasks.values(), stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_task not in done and not stop_event.is_set():
            role, task = next((name, item) for name, item in tasks.items() if item in done)
            exception = task.exception()
            if exception is not None:
                raise RuntimeError(f"{role}_worker_crashed") from exception
            raise RuntimeError(f"{role}_worker_stopped_unexpectedly")
    finally:
        stop_event.set()
        for task in [*tasks.values(), stop_task]:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks.values(), stop_task, return_exceptions=True)


async def run_worker_process(
    *,
    analysis_worker_id: Optional[str] = None,
    technical_worker_id: Optional[str] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    init_observability()
    init_connection_pool()
    try:
        # Workers are verification-only. Schema ownership belongs to the
        # one-shot migration service, even in local compose environments.
        verify_schema_migrations()
        init_redis_client()
        await supervise_workers(
            stop_event=stop_event or asyncio.Event(),
            analysis_worker_id=_process_identity(
                "analysis", analysis_worker_id or os.getenv("ANALYSIS_WORKER_ID")
            ),
            technical_worker_id=_process_identity(
                "technical", technical_worker_id or os.getenv("TECHNICAL_WORKER_ID")
            ),
        )
    finally:
        close_redis()
        close_connection_pool()


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except (NotImplementedError, RuntimeError):
            # add_signal_handler is unavailable on a few event-loop platforms.
            signal.signal(signum, lambda *_args: stop_event.set())


async def _async_main(args: argparse.Namespace) -> None:
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    await run_worker_process(
        analysis_worker_id=args.analysis_worker_id,
        technical_worker_id=args.technical_worker_id,
        stop_event=stop_event,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run InterAI durable analysis and technical workers")
    parser.add_argument("--analysis-worker-id")
    parser.add_argument("--technical-worker-id")
    args = parser.parse_args()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
