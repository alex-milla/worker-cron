"""Smoke test de la GUI del worker: login, CSRF, CRUD de jobs y /health."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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

# 13. nombre de usuario duplicado/corto rechazado
page_html = c5.get("/password").data.decode("utf-8")
new_csrf = _re.search(r'name="csrf" value="([^"]*)"', page_html).group(1)
r = c5.post("/password", data={"username": "x", "csrf": new_csrf})  # corto
assert b"al menos 3" in r.data
print("13. validacion usuario: OK")

# 14. pantalla Actualizaciones (regresion del 500 por falta de Path import)
r = c5.get("/updates")
assert r.status_code == 200, r.data[:300]
page_html = r.data.decode("utf-8")
assert "GitHub" in page_html and "Backups" in page_html
assert 'name="csrf" value=""' not in page_html, "csrf vacio en /updates"
print("14. /updates: OK")

# 15. los iconos SVG del sidebar NO se ven escapados (regresion del menu roto)
dash = c5.get("/").data.decode("utf-8")
assert "<svg" in dash and "&lt;svg" not in dash, "iconos HTML escapados en el shell"
assert "sidebar-link" in dash and "app-sidebar" in dash
print("15. iconos svg sin escapar: OK")

# 16. 'icons.update' colisionaba con dict.update -> built-in method pintado
assert "built-in method" not in dash, "colision icons.update con dict.update"
assert (len(_re.findall(r'stroke-linejoin="round"', dash)) >= 9), "faltan iconos"
print("16. colision dict.update: OK")

# 17. token de GitHub: guardar (en BD local), enmascarado, y eliminar
page_html = c5.get("/updates").data.decode("utf-8")
tok = _re.search(r'name="csrf" value="([^"]*)"', page_html).group(1)
r = c5.post("/updates", data={"action": "save_token", "github_token": "ghp_SECRETO-123",
                              "csrf": tok})
assert r.status_code == 302
page_html = c5.get("/updates").data.decode("utf-8")
assert "ghp_SECRETO-123" not in page_html, "el token se pinta en el HTML!"
assert "ya configurado" in page_html
artifact = page_html
print("17a. token guardado y enmascarado: OK")

r = c5.post("/updates", data={"action": "save_token", "github_token": "", "csrf": tok})
page_html = c5.get("/updates").data.decode("utf-8")
assert "ya configurado" not in page_html and "Sin token" in page_html
print("17b. token eliminado: OK")

# 18. GET /jobs/<id>/edit responde 200 (regresion del 500 UnboundLocalError:
#     la suite solo hacia POST y no veia la pantalla de edicion)
r = c5.post("/jobs/new", data={"name": "Editable", "cron_expr": "0 5 * * *",
                               "command": "echo ok", "timeout_sec": "30",
                               "enabled": "on", "csrf": tok})
assert r.status_code == 302
conn = sqlite3.connect(tmp)
jid = conn.execute("SELECT id FROM jobs ORDER BY id DESC LIMIT 1").fetchone()[0]
conn.close()
r = c5.get(f"/jobs/{jid}/edit")
assert r.status_code == 200, r.status_code
assert b"Editar t" in r.data and b"Editable" in r.data
print("18. GET /jobs/<id>/edit -> 200: OK")

# 19. id inexistente -> 404, no 500 ni "actualizada"
assert c5.get("/jobs/999999/edit").status_code == 404
r = c5.post("/jobs/999999/edit", data={"name": "X", "cron_expr": "* * * * *",
                                       "command": "x", "timeout_sec": "1",
                                       "enabled": "on", "csrf": tok})
assert r.status_code == 404, r.status_code
conn = sqlite3.connect(tmp)
assert conn.execute("SELECT COUNT(*) FROM jobs WHERE id=999999").fetchone()[0] == 0
conn.close()
print("19. id inexistente -> 404: OK")

# 20. open redirect en ?next= (absoluta y protocolo-relativa)
for hostile in ("https://evil.example.com", "//evil.example.com", "/\\evil.example.com"):
    c6 = app.test_client()
    c6.get("/login")
    with c6.session_transaction() as s:
        cs6 = s["csrf"]
    r = c6.post(f"/login?next={hostile}",
                data={"username": "gestor", "password": "nueva-clave-1", "csrf": cs6})
    loc = r.headers.get("Location") or ""
    assert r.status_code == 302 and loc == "/", (hostile, loc)
print("20. ?next= solo rutas internas: OK")

# 21. el nombre del job no se interpola en JS (XSS almacenado del confirm)
payload = "x')||alert(document.domain)||confirm('"
c5.post("/jobs/new", data={"name": payload, "cron_expr": "* * * * *",
                           "command": "echo", "timeout_sec": "1",
                           "enabled": "on", "csrf": tok})
dash = c5.get("/").data.decode("utf-8")
assert "onsubmit=" not in dash, "el confirm vuelve a interpolar datos en JS"
assert "data-confirm=" in dash and "addEventListener('submit'" in dash
print("21. nombre sin interpolar en JS (data-confirm): OK")

# 22. flash() se renderiza de verdad
r = c5.post("/jobs/new", data={"name": "ConAviso", "cron_expr": "* * * * *",
                               "command": "echo", "timeout_sec": "1",
                               "enabled": "on", "csrf": tok},
            follow_redirects=True)
assert b"ConAviso" in r.data and "creada".encode() in r.data, r.data[:300]
print("22. flash 'Tarea creada' visible: OK")

# 23. aviso de contrasena por defecto (BD nueva -> admin/admin)
tmp2 = Path(tempfile.mkdtemp()) / "fresh.sqlite"
cfg2 = tmp2.parent / "config.yaml"
cfg2.write_text('worker:\n  name: fresh\n  db_path: "%s"\n' % tmp2.as_posix(),
                encoding="utf-8")
app2 = create_app(cfg2)
f = app2.test_client()
f.get("/login")
with f.session_transaction() as s:
    cs7 = s["csrf"]
f.post("/login", data={"username": "admin", "password": "admin", "csrf": cs7})
assert "contraseña por defecto".encode() in f.get("/").data
print("23. aviso de contrasena por defecto: OK")

# 24. /api/jobs publico NO expone el comando
body = app.test_client().get("/api/jobs").get_data(as_text=True)
assert '"command"' not in body and "echo" not in body, body[:200]
print("24. /api/jobs sin comandos: OK")

# 25. el CSS no se autoescapa dentro de <style>
dash = c5.get("/").data.decode("utf-8")
css = _re.search(r"<style>(.*?)</style>", dash, _re.S).group(1)
assert "&#39;" not in css and "Segoe UI" in css, "el CSS se esta escapando dentro de <style>"
print("25. CSS sin escapar: OK")

# 26. tarjeta de estado de sincronización en el dashboard
dash = c5.get("/").data.decode("utf-8")
assert "Estado del worker" in dash, "falta la tarjeta de estado"
assert "Resultados pendientes" in dash
assert "todavía no se ha sincronizado" in dash, "una BD nueva no debería tener sync"
print("26. tarjeta de estado del worker: OK")

print("\nTODOS LOS TESTS OK")
