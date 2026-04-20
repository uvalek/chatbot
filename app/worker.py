"""Worker que recoge huérfanos del buffer (cuando el web reinicia mid-flush)."""

from __future__ import annotations

import asyncio
import logging

import structlog

from app import buffer
from app.config import get_settings
from app.graph import dispatch

settings = get_settings()
logging.basicConfig(level=settings.log_level)
log = structlog.get_logger(__name__)


async def main() -> None:
    log.info("worker_start", interval=settings.buffer_window_seconds)
    while True:
        try:
            n = await buffer.reap_orphans(dispatch)
            if n:
                log.info("worker_reaped", count=n)
        except Exception as e:  # noqa: BLE001
            log.exception("worker_loop_error", error=str(e))
        await asyncio.sleep(max(5, settings.buffer_window_seconds // 2))


if __name__ == "__main__":
    asyncio.run(main())
