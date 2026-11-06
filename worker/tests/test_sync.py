"""Tests de sync: pull por revisión, espejo de jobs, cola de resultados y errores."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cronworker import store, sync  # noqa: E402

tmp = Path(tempfile.mkdtemp()) / "worker.sqlite"
conn = store.connect(tmp)


class FakeClient(sync.SyncClient):
    """Cliente con transporte en memoria (sin red)."""

    def __init__(self, revision=1, jobs=None, fail_post=False):
        super().__init__("http://panel.local", "token-de-prueba", transport=self.transport)
        self.revision = revision
        self._jobs = jobs or []
        self.fail_post = fail_post
        self.posts = []
        self.beats = []
        self.calls = []

    def transport(self, method, url, body, headers, timeout):
        self.calls.append((method, url))

        if url.endswith("/api/v1/version"):
            return 200, json.dumps({"revision": self.revision})
        if url.endswith("/api/v1/jobs"):
            return 200, json.dumps({"revision": self.revision, "jobs": self._jobs})
        if url.endswith("/api/v1/results"):
            if self.fail_post:
                return 500, '{"error":"boom"}'
            self.posts.append(json.loads(body or b"{}"))
            return 201, json.dumps({"id": len(self.posts)})
        if url.endswith("/api/v1/heartbeat"):
            self.beats.append(json.loads(body or b"{}"))
            return 200, '{"ok":true}'
        return 404, "{}"


def job(jid, name, cron="* * * * *", command="echo hola", enabled=1):
    return {
        "id": jid, "name": name, "cron_expr": cron, "command": command,
        "timeout_sec": 10, "enabled": enabled, "comment": None,
        "updated_at": "2026-11-06T00:00:00",
    }


# 1. primer pull: alta de tareas del panel
client = FakeClient(revision=5, jobs=[job(1, "Backup"), job(2, "Limpieza")])
r = sync.pull(conn, client)
assert r["changed"] is True, r
assert r["added"] == 2 and r["updated"] == 0 and r["deleted"] == 0, r
assert store.revision(conn) == 5
filas = conn.execute("SELECT name, source, source_id FROM jobs ORDER BY source_id").fetchall()
assert [(f["name"], f["source"], f["source_id"]) for f in filas] == [
    ("Backup", "hosting", 1), ("Limpieza", "hosting", 2)
]
print("1. pull inicial (alta): OK")

# 2. misma revisión: no descarga la lista
client.calls.clear()
r = sync.pull(conn, client)
assert r["changed"] is False and r["added"] == 0, r
assert [c[1].rsplit("/", 1)[-1] for c in client.calls] == ["version"], client.calls
print("2. misma revisión -> solo /version: OK")

# 3. revisión nueva: actualiza y borra lo que desaparece
client.revision = 6
client._jobs = [job(2, "Limpieza renombrada")]
r = sync.pull(conn, client)
assert r["changed"] is True, r
assert r["updated"] == 1 and r["deleted"] == 1, r
assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
assert conn.execute("SELECT name FROM jobs").fetchone()[0] == "Limpieza renombrada"
print("3. pull incremental (update + delete): OK")

# 4. los jobs locales no se tocan
store.save_job(conn, {
    "name": "Local del LXC", "cron_expr": "0 4 * * *", "command": "echo local",
    "timeout_sec": 0, "enabled": 1, "comment": None, "source": "local",
})
client.revision = 7
client._jobs = [job(3, "Nueva del panel")]
sync.pull(conn, client)
local = conn.execute("SELECT name, source, source_id FROM jobs WHERE source='local'").fetchone()
assert local is not None and local["name"] == "Local del LXC" and local["source_id"] is None
print("4. jobs locales intactos: OK")

# 5. resultados: la ejecución de un job del panel se reporta
panel_job = conn.execute("SELECT id, source_id FROM jobs WHERE source='hosting'").fetchone()
run_id = store.save_run(conn, int(panel_job["id"]), {
    "started_at": "2026-11-06T23:00:00+00:00",
    "finished_at": "2026-11-06T23:00:02+00:00",
    "status": "ok",
    "exit_code": 0,
    "output": "hecho",
})
assert store.count_pending(conn) == 1

push = sync.push_pending(conn, client)
assert push["sent"] == 1 and push["pending"] == 0, push
assert client.posts[0]["job_id"] == int(panel_job["source_id"])
assert client.posts[0]["status"] == "ok"
assert conn.execute("SELECT reported FROM job_runs WHERE id=?", (run_id,)).fetchone()[0] == 1
print("5. resultados reportados: OK")

# 6. las ejecuciones de jobs locales no se reportan (no existen en el panel)
local_job = conn.execute("SELECT id FROM jobs WHERE source='local'").fetchone()
store.save_run(conn, int(local_job["id"]), {
    "started_at": "2026-11-06T23:01:00+00:00",
    "finished_at": "2026-11-06T23:01:01+00:00",
    "status": "ok", "exit_code": 0, "output": "",
})
assert store.count_pending(conn) == 0
print("6. ejecuciones locales no se envían: OK")

# 7. si el panel falla, la ejecución queda pendiente
run_id = store.save_run(conn, int(panel_job["id"]), {
    "started_at": "2026-11-06T23:02:00+00:00",
    "finished_at": "2026-11-06T23:02:01+00:00",
    "status": "failed", "exit_code": 1, "output": "boom",
})
client.fail_post = True
push = sync.push_pending(conn, client)
assert push["sent"] == 0 and push["pending"] == 1, push
assert conn.execute("SELECT reported FROM job_runs WHERE id=?", (run_id,)).fetchone()[0] == 0
client.fail_post = False
push = sync.push_pending(conn, client)
assert push["sent"] == 1 and push["pending"] == 0, push
print("7. fallo de red -> queda pendiente y se reintenta: OK")

# 8. heartbeat
sync.heartbeat(conn, client, "lxc-test")
assert client.beats[-1]["name"] == "lxc-test"
assert client.beats[-1]["revision"] == 7
print("8. heartbeat: OK")


# 9. errores del panel se traducen a SyncError con mensaje útil
class ErrorClient(sync.SyncClient):
    def __init__(self, status, body="{}"):
        super().__init__("http://panel.local", "token", transport=self.transport)
        self.status = status
        self.body = body

    def transport(self, method, url, body, headers, timeout):
        return self.status, self.body


try:
    ErrorClient(401).version()
    raise AssertionError("debía lanzar SyncError con 401")
except sync.SyncError as exc:
    assert "token" in str(exc).lower(), exc

try:
    ErrorClient(500, '{"error":"boom"}').version()
    raise AssertionError("debía lanzar SyncError con 500")
except sync.SyncError as exc:
    assert "500" in str(exc), exc

try:
    ErrorClient(200, "no-es-json").version()
    raise AssertionError("debía lanzar SyncError con JSON inválido")
except sync.SyncError as exc:
    assert "JSON" in str(exc), exc

try:
    sync.SyncClient("", "token").version()
    raise AssertionError("debía lanzar SyncError sin base_url")
except sync.SyncError as exc:
    assert "base_url" in str(exc), exc
print("9. errores traducidos a SyncError: OK")

print("\nTODOS LOS TESTS DE SYNC OK")
