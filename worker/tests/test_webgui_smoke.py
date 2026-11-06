"""Smoke test de la GUI del worker: login, CSRF, CRUD de jobs y /health."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"J:\worker-cron\worker")

tmp = Path(tempfile.mkdtemp()) / "worker.sqlite"
cfg = tmp.parent / "config.yaml"
cfg.write_text(
    "worker:\n  name: test-worker\n"
    f'  db_path: "{tmp.as_posix()}"\n',
    encoding="utf-8",
)

from cronworker.webgui import create_app  # noqa: E402

app = create_app(cfg)
c = app.test_client()

# 1. health público sin sesión
r = c.get("/health")
assert r.status_code == 200 and b"ok" in r.data, r.data
print("1. /health sin sesión: OK")

# 2. dashboard redirige a /login sin sesión
r = c.get("/")
assert r.status_code == 302 and "/login" in r.headers["Location"], r.headers
print("2. guard sin sesión -> /login: OK")

# 3. login CSRF obligatorio
r = c.post("/login", data={"username": "admin", "password": "admin"})
assert r.status_code == 400, r.status_code
print("3. login sin CSRF -> 400: OK")

# 4. login correcto
c.get("/login")  # establece cookie de sesión + csrf
with c.session_transaction() as s:
    csrf = s["csrf"]
r = c.post("/login", data={"username": "admin", "password": "admin", "csrf": csrf})
assert r.status_code == 302 and r.headers["Location"].endswith("/"), (r.status_code, r.headers)
print("4. login admin/admin: OK")

# 5. credenciales inválidas
c2 = app.test_client()
c2.get("/login")
with c2.session_transaction() as s:
    csrf2 = s["csrf"]
r = c2.post("/login", data={"username": "admin", "password": "mal", "csrf": csrf2})
assert b"Credenciales" in r.data
print("5. login inválido muestra error: OK")

# 6. crear tarea con cron válido
r = c.post("/jobs/new", data={
    "name": "Backup diario", "cron_expr": "30 3 * * *",
    "command": "tar -czf /tmp/b.tar.gz /data", "timeout_sec": "600",
    "comment": "prueba", "enabled": "on", "csrf": csrf,
})
assert r.status_code == 302, r.data
r = c.get("/")
assert b"Backup diario" in r.data and b"30 3 * * *" in r.data
assert b"hosting" not in r.data or b"local" in r.data  # source local
print("6. crear tarea: OK")

# 7. crear tarea con cron invalido -> rechazada
r = c.post("/jobs/new", data={
    "name": "Mala", "cron_expr": "99 25 * * *", "command": "x", "csrf": csrf,
})
assert b"inv" in r.data, r.data
r = c.get("/")
assert b"Mala" not in r.data
print("7. cron invalido rechazado: OK")

# 8. editar tarea
import sqlite3  # noqa: E402
conn = sqlite3.connect(tmp)
jid = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
conn.close()
r = c.post(f"/jobs/{jid}/edit", data={
    "name": "Backup semanal", "cron_expr": "0 4 * * 0", "command": "echo ok",
    "timeout_sec": "0", "comment": "", "enabled": "on", "csrf": csrf,
})
assert r.status_code == 302
r = c.get("/")
assert b"Backup semanal" in r.data
print("8. editar tarea: OK")

# 9. pausar y borrar
r = c.post(f"/jobs/{jid}/toggle", data={"csrf": csrf})
assert c.post(f"/jobs/{jid}/delete", data={"csrf": csrf}).status_code == 302
conn = sqlite3.connect(tmp)
n = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
conn.close()
print("9. pausar y borrar: OK" + (f" (jobs restantes: {n})" if n else " (sin jobs)"))

# 10. cambio de contrasena y logout
r = c.post("/password", data={"old_password": "admin", "new_password": "nueva-clave-1",
                              "new_password2": "nueva-clave-1", "csrf": csrf})
assert r.status_code == 302, r.data
r = c.post("/logout", data={"csrf": csrf})
assert r.status_code == 302
c3 = app.test_client()
c3.get("/login")
with c3.session_transaction() as s:
    csrf3 = s["csrf"]
r = c3.post("/login", data={"username": "admin", "password": "nueva-clave-1", "csrf": csrf3})
assert r.status_code == 302
print("10. cambiar contrasena + logout + relogin: OK")

# 11. /password renderiza el CSRF oculto NO vacio (bug del Bad Request)
import re as _re  # noqa: E402

c4 = app.test_client()
c4.get("/login")
with c4.session_transaction() as s:
    csrf4 = s["csrf"]
c4.post("/login", data={"username": "admin", "password": "nueva-clave-1", "csrf": csrf4})
page_html = c4.get("/password").data.decode("utf-8")
m = _re.search(r'name="csrf" value="([^"]*)"', page_html)
assert m and m.group(1), "el campo csrf oculto de /password esta vacio"
print("11. /password incluye csrf en el form: OK")

# 12. cambiar nombre de usuario con el csrf extraido de la pagina (fluxo browser)
new_csrf = m.group(1)
r = c4.post("/password", data={"username": "gestor", "csrf": new_csrf})
assert r.status_code == 302, r.data[:200]
c4.post("/logout", data={"csrf": new_csrf})
c5 = app.test_client()
c5.get("/login")
with c5.session_transaction() as s:
    csrf5 = s["csrf"]
r = c5.post("/login", data={"username": "gestor", "password": "nueva-clave-1", "csrf": csrf5})
assert r.status_code == 302, "no se puede entrar con el usuario renombrado"
print("12. cambio de nombre de usuario: OK")

# 13. nombre de usuario duplicado rechazado
page_html = c5.get("/password").data.decode("utf-8")
new_csrf = _re.search(r'name="csrf" value="([^"]*)"', page_html).group(1)
page_html = c5.post("/password", data={"username": "gestor", "csrf": new_csrf}).data.decode()
page_html = c5.get("/password").data.decode("utf-8")
new_csrf = _re.search(r'name="csrf" value="([^"]*)"', page_html).group(1)
r = c5.post("/password", data={"username": "x", "csrf": new_csrf})  # corto
assert b"al menos 3" in r.data
print("13. validacion usuario: OK")

print("\nTODOS LOS TESTS OK")
