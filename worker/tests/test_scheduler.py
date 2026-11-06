"""Tests del scheduler: relojes cron, ejecución de lo que toca y resiliencia."""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cronworker import scheduler, store  # noqa: E402

tmp = Path(tempfile.mkdtemp()) / "worker.sqlite"
conn = store.connect(tmp)

cfg = {
    "hosting": {
        "base_url": "http://panel.local",
        "api_token": "token",
        "poll_interval_min": 1,
        "backoff_max_min": 30,
        "timeout_sec": 5,
    },
    "worker": {"name": "lxc-test", "db_path": str(tmp)},
}


class ClienteRoto:
    """Todo falla: el scheduler no debe morir."""

    def version(self):
        from cronworker import sync
        raise sync.SyncError("sin conexión")


sched = scheduler.Scheduler(cfg=cfg, client=ClienteRoto(), conn=conn)

# 1. poll con el panel caído: no lanza, aplica backoff
r = sched.poll()
assert r["error"] != "", r
assert sched._backoff == 2, sched._backoff  # 1 * 2
r = sched.poll()
assert sched._backoff == 4, sched._backoff
r = sched.poll()
assert sched._backoff == 8, sched._backoff
print("1. panel caído -> backoff exponencial: OK")

# 2. cron inválido no rompe el bucle
jid = store.save_job(conn, {
    "name": "Cron roto", "cron_expr": "99 99 * * *", "command": "echo x",
    "timeout_sec": 1, "enabled": 1, "comment": None, "source": "local",
})
assert sched.due_jobs(datetime.now()) == []
print("2. cron inválido se ignora: OK")

# 3. una tarea programada no está 'due' hasta su hora
jid = store.save_job(conn, {
    "name": "Cada minuto", "cron_expr": "* * * * *", "command": "echo ok",
    "timeout_sec": 5, "enabled": 1, "comment": None, "source": "local",
})
ahora = datetime.now()
assert sched.due_jobs(ahora) == []
nxt = sched._next_run[int(jid)]
assert nxt > ahora
print(f"3. próxima ejecución programada ({nxt:%H:%M:%S}): OK")

# 4. cuando llega la hora, se ejecuta y se guarda la corrida
sched._next_run[int(jid)] = ahora - timedelta(seconds=1)
ejecutados = sched.run_due(ahora)
assert ejecutados == 1, ejecutados
run = conn.execute("SELECT status, exit_code, output FROM job_runs ORDER BY id DESC LIMIT 1").fetchone()
assert run is not None and run["status"] == "ok" and run["exit_code"] == 0
assert "ok" in run["output"]
assert sched._next_run[int(jid)] > ahora  # reprogramada
print("4. ejecución y reprogramación: OK")

# 5. una tarea pausada no se ejecuta
store.set_enabled(conn, int(jid), False)
sched._next_run[int(jid)] = ahora - timedelta(seconds=1)
assert sched.due_jobs(ahora) == []
print("5. tarea pausada no se ejecuta: OK")

# 6. el scheduler no duplica ejecuciones en el mismo tick
store.set_enabled(conn, int(jid), True)
sched._next_run[int(jid)] = ahora - timedelta(seconds=1)
assert sched.run_due(ahora) == 1
assert sched.run_due(ahora) == 0
print("6. no se ejecuta dos veces seguidas: OK")

# 7. tick completo con el panel caído no propaga la excepción
sched.tick(datetime.now())
print("7. tick con panel caído: OK")

# 8. un fallo dentro del tick no mata el bucle (se registra)
viejo = store.list_jobs
store.list_jobs = lambda _conn: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    sched.run_due(datetime.now())
    raise AssertionError("debía propagar para que el bucle lo capture")
except RuntimeError:
    pass
finally:
    store.list_jobs = viejo
print("8. excepción de ejecución propagada al bucle: OK")

print("\nTODOS LOS TESTS DEL SCHEDULER OK")
