"""Frozen desktop entry point for the local PrepMate API."""

from __future__ import annotations

import os

import uvicorn

from app import app as application


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        application,
        host="127.0.0.1",
        port=port,
        access_log=os.getenv("PREPMATE_ACCESS_LOG", os.getenv("INTERAI_ACCESS_LOG", "false")).lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
