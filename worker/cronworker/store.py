"""Espejo local SQLite del estado de jobs.

TODO: guardar jobs sincronizados (id, name, cron_expr, command, timeout_sec,
    enabled), la revisión (revision) y la cola de resultados pendientes de enviar
    (job_runs no reportados aún por error de red en el push).
"""

from __future__ import annotations
