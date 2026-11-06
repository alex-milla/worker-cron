"""Scheduler principal del worker.

Bucle: sincronizar (pull) → programar jobs → ejecutar y reportar.
TODO: implementar el bucle con APScheduler/AIOHTTP y apagar en SIGTERM.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def run_forever() -> None:  # pragma: no cover - stub
    log.info("Worker iniciado (stub — implementar lógica)")
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(run_forever())
