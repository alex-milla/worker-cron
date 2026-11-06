"""Scheduler principal del worker.

Bucle: sincronizar (pull) -> ejecutar lo que toca -> reportar y latir.

- El reloj de cada tarea se calcula con `croniter` a partir de "ahora", así un
  reinicio no dispara nada atrasado (comportamiento de cron clásico: lo que se
  pierde, se pierde).
- Si el panel no responde, backoff exponencial hasta `hosting.backoff_max_min`.
- Las ejecuciones se guardan primero en local y se reportan después; si el
  panel falla, quedan pendientes y se reintentan en el siguiente tick.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sqlite3
from datetime import datetime, timedelta

from croniter import croniter

from . import executor, store, sync
from .config import load_config, resolve_db_path

log = logging.getLogger(__name__)

TICK_SECONDS = 5


class Scheduler:
    def __init__(
        self,
        cfg: dict | None = None,
        client: sync.SyncClient | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self.cfg = cfg if cfg is not None else load_config()
        hosting = self.cfg.get("hosting", {}) if isinstance(self.cfg, dict) else {}

        self.client = client or sync.SyncClient(
            str(hosting.get("base_url", "")),
            str(hosting.get("api_token", "")),
            int(hosting.get("timeout_sec", 30)),
        )
        self.conn = conn or store.connect(resolve_db_path(self.cfg))

        self.poll_interval = max(1, int(hosting.get("poll_interval_min", 1)))
        self.backoff_max = max(self.poll_interval, int(hosting.get("backoff_max_min", 30)))
        self.worker_name = str(
            (self.cfg.get("worker", {}) if isinstance(self.cfg, dict) else {}).get(
                "name", "worker"
            )
        )

        self._next_poll: datetime | None = None
        self._backoff = self.poll_interval
        self._next_run: dict[int, datetime] = {}

    # ------------------------------------------------------------- poll --

    def poll(self) -> dict:
        """Pull + reporte de pendientes + latido. Nunca lanza `SyncError`."""
        resumen = {"changed": False, "sent": 0, "pending": 0, "error": ""}

        try:
            pulled = sync.pull(self.conn, self.client)
            resumen["changed"] = bool(pulled.get("changed"))

            pushed = sync.push_pending(self.conn, self.client)
            resumen["sent"] = int(pushed.get("sent", 0))
            resumen["pending"] = int(pushed.get("pending", 0))

            sync.heartbeat(self.conn, self.client, self.worker_name)
            self._backoff = self.poll_interval
            store.set_last_sync(self.conn, True)
        except sync.SyncError as exc:
            resumen["error"] = str(exc)
            log.warning(
                "sincronización fallida: %s (reintento en %s min)", exc, self._backoff
            )
            self._backoff = min(self._backoff * 2, self.backoff_max)
            store.set_last_sync(self.conn, False, str(exc))

        self._next_poll = datetime.now() + timedelta(minutes=self._backoff)
        return resumen

    # ------------------------------------------------------------ ejecución --

    def _next_occurrence(self, job, base: datetime) -> datetime | None:
        try:
            return croniter(str(job["cron_expr"]), base).get_next(datetime)
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("job #%s: expresión cron inválida (%s)", job["id"], exc)
            return None

    def due_jobs(self, now: datetime | None = None) -> list:
        now = now or datetime.now()
        due = []

        for job in store.list_jobs(self.conn):
            if int(job["enabled"]) != 1:
                continue

            job_id = int(job["id"])
            if job_id not in self._next_run:
                nxt = self._next_occurrence(job, now)
                if nxt is None:
                    continue
                self._next_run[job_id] = nxt
                log.info("job #%s '%s' -> próxima %s", job_id, job["name"], nxt)

            if self._next_run[job_id] <= now:
                due.append(job)

        return due

    def run_due(self, now: datetime | None = None) -> int:
        now = now or datetime.now()
        ejecutados = 0

        for job in self.due_jobs(now):
            job_id = int(job["id"])
            log.info("ejecutando #%s '%s'", job_id, job["name"])

            result = executor.run_job(
                str(job["command"]), int(job["timeout_sec"] or 0)
            )
            store.save_run(self.conn, job_id, result)
            ejecutados += 1

            nxt = self._next_occurrence(job, now)
            if nxt is None:
                self._next_run.pop(job_id, None)
            else:
                self._next_run[job_id] = nxt

            log.info(
                "job #%s -> %s (exit %s, %d bytes)",
                job_id,
                result["status"],
                result["exit_code"],
                len(result["output"]),
            )

        return ejecutados

    # --------------------------------------------------------------- bucle --

    def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now()

        if self._next_poll is None or now >= self._next_poll:
            self.poll()

        self.run_due(now)

    async def run_forever(self) -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # Windows / sin soporte
                pass

        log.info(
            "worker iniciado: %s (poll %s min, tick %ss)",
            self.worker_name,
            self.poll_interval,
            TICK_SECONDS,
        )

        while not stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - el bucle no debe morir
                log.exception("error en el tick")

            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
            except asyncio.TimeoutError:
                continue

        log.info("worker detenido")
        self.conn.close()


async def run_forever() -> None:
    await Scheduler().run_forever()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
