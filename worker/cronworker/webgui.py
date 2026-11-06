"""GUI local de monitorización y gestión del worker (Flask).

Pantallas:
    /login     — Pantsalla de acceso (sesión por cookie + CSRF)
    /          — Dashboard: jobs, próximas ejecuciones, últimas corridas
    /jobs/new  — Crear tarea (validación cron; se marca pending_sync para el hosting)
    /jobs/<id> — Editar / eliminar / activar-pausar
    /password  — Cambiar contraseña

Endpoints públicos (para monitorización sin sesión):
    /health    — JSON de vida
    /api/jobs  — JSON del espejo local

En producción se arranca con gunicorn y Apache hace de reverse proxy
(worker/deploy/cron-gui.service + worker/deploy/apache-cron-gui.conf).
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime

from croniter import croniter
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)

from . import store
from .config import load_config, resolve_db_path

log = logging.getLogger(__name__)

APP_NAME = "Worker Cron"
APP_SUBTITLE = "Programador de tareas del worker"

# --------------------------------------------------------------- cron utils --


def cron_check(cron_expr: str) -> tuple[bool, str]:
    """Valida una expresión cron de 5 campos. Devuelve (ok, mensaje)."""
    try:
        base = datetime.now()
        cron = croniter(cron_expr, base)
        nxt = cron.get_next(datetime)
        return True, f"próxima: {nxt.strftime('%d/%m/%Y %H:%M')}"
    except Exception as exc:  # noqa: BLE001 - mensaje directo al usuario
        return False, f"expresión cron inválida: {exc}"


# ------------------------------------------------------------------ styles --

BASE_CSS = """
    :root { --bg:#f9fafb; --surface:#fff; --surface-2:#f1f5f9; --text:#111827;
            --muted:#6b7280; --muted-soft:#9ca3af; --border:#e5e7eb;
            --input-border:#d1d5db; --input-bg:#fff;
            --brand:#f97316; --brand-hover:#ea580c; --brand-soft:#fff7ed;
            --brand-border:#fed7aa; --focus:#f97316;
            --ok:#15803d; --bad:#dc2626; --warn:#b45309; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
           background:var(--bg); color:var(--text); }
    a { color:inherit; text-decoration:none; }
    code { font-family:ui-monospace,'JetBrains Mono',monospace; }
"""

LOGIN_CSS = BASE_CSS + """
    body { display:flex; align-items:center; justify-content:center;
           min-height:100vh; padding:1rem; }
    .col { width:100%; max-width:24rem; }
    .brand { text-align:center; margin-bottom:2rem; }
    .logo { display:inline-flex; align-items:center; justify-content:center;
            width:4rem; height:4rem; border-radius:1rem; background:var(--brand);
            color:#fff; font-size:2rem; margin-bottom:1rem; }
    h1 { font-size:1.5rem; font-weight:700; margin:0; }
    .sub { color:var(--muted); font-size:.875rem; margin:.25rem 0 0; }
    form { background:var(--surface); border:1px solid var(--border);
           border-radius:.75rem; box-shadow:0 1px 2px rgba(0,0,0,.05);
           padding:1.5rem; display:flex; flex-direction:column; gap:1rem; }
    label { display:block; font-size:.875rem; font-weight:500; color:#374151;
            margin-bottom:.25rem; }
    input { width:100%; padding:.5rem .75rem; border-radius:.5rem;
            border:1px solid var(--input-border); background:var(--input-bg);
            font-size:.95rem; outline:none; }
    input:focus { box-shadow:0 0 0 2px var(--focus); border-color:transparent; }
    .error { font-size:.875rem; color:#ef4444; background:#fef2f2;
             padding:.5rem .75rem; border-radius:.5rem; }
    .hint { font-size:.8rem; color:var(--muted-soft); margin-top:.75rem;
            text-align:center; }
    .btn { width:100%; padding:.625rem 1rem; background:var(--brand);
           border:none; border-radius:.5rem; color:#fff; font-weight:500;
           font-size:.95rem; cursor:pointer; transition:background .15s; }
    .btn:hover { background:var(--brand-hover); }
"""

APP_CSS = BASE_CSS + """
    header { background:var(--surface); border-bottom:1px solid var(--border);
             padding:.75rem 1.5rem; display:flex; justify-content:space-between;
             align-items:center; gap:1rem; position:sticky; top:0; z-index:10; }
    .h-left { display:flex; align-items:center; gap:.75rem; }
    .h-logo { display:inline-flex; align-items:center; justify-content:center;
              width:2.25rem; height:2.25rem; border-radius:.5rem;
              background:var(--brand); color:#fff; font-size:1.2rem; }
    .h-title { font-weight:700; font-size:1.05rem; }
    .h-sub { font-size:.78rem; color:var(--muted); }
    .h-actions { display:flex; gap:.5rem; align-items:center; }
    .h-actions a, .h-actions button { padding:.45rem .85rem; border-radius:.5rem;
             font-size:.85rem; border:1px solid var(--border);
             background:var(--surface); cursor:pointer; font-weight:500; }
    .h-actions a { color:var(--muted); }
    .h-actions a:hover { background:var(--surface-2); }
    .h-actions .primary { background:var(--brand); border-color:var(--brand);
                          color:#fff; }
    .h-actions .primary:hover { background:var(--brand-hover); }
    .logout-btn { color:#b91c1c; }
    main { max-width:1100px; margin:1.5rem auto; padding:0 1rem; }
    .card { background:var(--surface); border:1px solid var(--border);
            border-radius:12px; padding:20px; margin-bottom:16px; }
    h2 { margin:0 0 12px; font-size:1.05rem; display:flex; align-items:center;
         gap:.5rem; }
    .toolbar { display:flex; justify-content:space-between; align-items:center;
               margin-bottom:4px; }
    .warn-banner { background:#fef3c7; border:1px solid #fde68a; color:#92400e;
                   padding:.6rem .9rem; border-radius:.5rem; font-size:.875rem;
                   margin-bottom:1rem; }
    .warn-banner a { text-decoration:underline; color:inherit; }
    table { width:100%; border-collapse:collapse; font-size:.9rem; }
    th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--border);
             vertical-align:middle; }
    th { font-size:.72rem; text-transform:uppercase; letter-spacing:.05em;
         color:var(--muted); }
    tbody tr:hover td { background:var(--brand-soft); }
    .pill { display:inline-block; padding:2px 10px; border-radius:999px;
            font-size:.75rem; font-weight:600; border:1px solid; white-space:nowrap; }
    .pill.ok   { color:var(--ok);   border-color:#bbf7d0; background:#dcfce7; }
    .pill.bad  { color:var(--bad);  border-color:#fca5a5; background:#fee2e2; }
    .pill.warn { color:var(--warn); border-color:#fde68a; background:#fef3c7; }
    .pill.off  { color:var(--muted); border-color:var(--border); background:#f3f4f6; }
    .pill.brand{ color:var(--brand-hover); border-color:var(--brand-border);
                 background:var(--brand-soft); }
    .muted { color:var(--muted); font-size:.85rem; }
    .mono { font-family:ui-monospace,'JetBrains Mono',monospace; font-size:.82rem; }
    .row-actions { display:flex; gap:.4rem; white-space:nowrap; }
    .row-actions button, .row-actions a { padding:.3rem .6rem; font-size:.78rem;
             border:1px solid var(--border); background:var(--surface);
             border-radius:.4rem; cursor:pointer; }
    .row-actions .danger { color:#b91c1c; border-color:#fca5a5; }
    .row-actions .danger:hover { background:#fee2e2; }
    .field { margin-bottom:.9rem; }
    .field label { display:block; font-size:.78rem; font-weight:500;
                   color:var(--muted); margin-bottom:.30rem; }
    .field input, .field textarea, .field select { width:100%; padding:.55rem .75rem;
             border-radius:.5rem; border:1px solid var(--input-border);
             background:var(--input-bg); font-size:.92rem; outline:none; }
    .field input:focus, .field textarea:focus { box-shadow:0 0 0 2px var(--focus);
             border-color:transparent; }
    .grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:1rem; }
    .grid-2 .field { margin-bottom:.9rem; }
    textarea { font-family:ui-monospace,monospace; min-height:96px; resize:vertical; }
    .helper { font-size:.75rem; color:var(--muted); margin-top:.25rem; }
    .alert-ok { background:#dcfce7; border:1px solid #bbf7d0; color:#15803d;
                padding:.6rem .9rem; border-radius:.5rem; font-size:.875rem;
                margin-bottom:1rem; }
    .alert-err { background:#fee2e2; border:1px solid #fca5a5; color:#b91c1c;
                 padding:.6rem .9rem; border-radius:.5rem; font-size:.875rem;
                 margin-bottom:1rem; }
    .form-actions { display:flex; gap:.6rem; justify-content:flex-end;
                    margin-top:1.2rem; padding-top:1rem;
                    border-top:1px solid var(--border); }
    .form-actions .btn { width:auto; padding:.55rem 1.2rem; }
    .form-actions .cancel { background:var(--surface); color:var(--muted);
                            border:1px solid var(--border); }
    @media (max-width:640px){ .grid-2 { grid-template-columns:1fr; } }
"""

BASE_CSS_TAG = "<style>{}</style>"


# --------------------------------------------------------------- templates --

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Iniciar sesión · {{ app_name }}</title>
  <style>{{ login_css }}</style>
</head>
<body>
  <div class="col">
    <div class="brand">
      <div class="logo">⏱</div>
      <h1>{{ app_name }}</h1>
      <p class="sub">{{ app_subtitle }}</p>
    </div>
    <form method="post" action="{{ url_for('login') }}">
      <input type="hidden" name="csrf" value="{{ csrf }}">
      <div>
        <label for="username">Usuario</label>
        <input id="username" name="username" type="text" autofocus
               autocomplete="username" value="{{ username or '' }}">
      </div>
      <div>
        <label for="password">Contraseña</label>
        <input id="password" name="password" type="password"
               autocomplete="current-password">
      </div>
      {% if error %}<div class="error">{{ error }}</div>{% endif %}
      <button type="submit" class="btn">Entrar</button>
    </form>
    <p class="hint">Acceso solo desde la red local</p>
  </div>
</body>
</html>"""

SHELL = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} · {{ app_name }}</title>
  <style>{{ app_css }}</style>
</head>
<body>
<header>
  <a class="h-left" href="{{ url_for('dashboard') }}">
    <span class="h-logo">⏱</span>
    <span>
      <span class="h-title">{{ app_name }}</span><br>
      <span class="h-sub">{{ worker_name }} · sync {{ revision or '—' }}</span>
    </span>
  </a>
  <nav class="h-actions">
    <a href="{{ url_for('job_new') }}" class="primary">+ Nueva tarea</a>
    <a href="{{ url_for('password_page') }}">Contraseña</a>
    <form method="post" action="{{ url_for('logout') }}">
      <input type="hidden" name="csrf" value="{{ csrf }}">
      <button type="submit" class="logout-btn">Salir</button>
    </form>
  </nav>
</header>
<main>
  {% if default_password %}
  <div class="warn-banner">⚠️ Estás usando la contraseña por defecto (admin/admin).
    <a href="{{ url_for('password_page') }}">Cámbiala ahora</a></div>
  {% endif %}
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="{{ 'alert-ok' if cat == 'ok' else 'alert-err' }}">{{ msg }}</div>
    {% endfor %}
  {% endwith %}
  {{ content|safe }}
</main>
</body>
</html>"""

DASHBOARD_CONTENT = """{% macro pill(status) %}
   {%- if status == 'ok' -%}<span class="pill ok">ok</span>
   {%- elif status == 'timeout' -%}<span class="pill warn">timeout</span>
   {%- else -%}<span class="pill bad">fallo</span>
   {%- endif -%}
{% endmacro %}
<section class="card">
  <div class="toolbar"><h2>Tareas programadas</h2></div>
  {% if jobs %}
  <table>
    <thead><tr>
      <th>#</th><th>Nombre</th><th>Cron</th><th>Próxima</th>
      <th>Estado</th><th>Origen</th><th>Acciones</th>
    </tr></thead>
    <tbody>
    {% for job in jobs %}
      <tr>
        <td>{{ job['id'] }}</td>
        <td>{{ job['name'] }}{% if job['comment'] %}
            <div class="muted">{{ job['comment'] }}</div>{% endif %}</td>
        <td><code class="mono">{{ job['cron_expr'] }}</code></td>
        <td class="muted">{{ next_runs.get(job['id'], '—') }}</td>
        <td>{% if job['enabled'] %}<span class="pill ok">activa</span>
            {% else %}<span class="pill off">pausada</span>{% endif %}</td>
        <td>
          {% if job['source'] == 'hosting' %}<span class="pill brand">hosting</span>
          {% else %}<span class="pill off">local</span>{% endif %}
          {% if job['pending_sync'] %}<span class="pill warn" title="pendiente de sincronizar con el hosting">⟳</span>{% endif %}
        </td>
        <td class="row-actions">
          <a href="{{ url_for('job_edit', job_id=job['id']) }}">Editar</a>
          <form method="post" style="display:inline"
                action="{{ url_for('job_toggle', job_id=job['id']) }}">
            <input type="hidden" name="csrf" value="{{ csrf }}">
            <button type="submit">{{ 'Pausar' if job['enabled'] else 'Activar' }}</button>
          </form>
          <form method="post" style="display:inline"
                action="{{ url_for('job_delete', job_id=job['id']) }}"
                onsubmit="return confirm('¿Eliminar «{{ job['name'] }}» y todas sus ejecuciones?');">
            <input type="hidden" name="csrf" value="{{ csrf }}">
            <button type="submit" class="danger">Borrar</button>
          </form>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="muted">Todavía no hay tareas. Crea la primera con «+ Nueva tarea»
    o sincroniza desde el hosting.</p>
  {% endif %}
</section>

<section class="card">
  <h2>Últimas ejecuciones</h2>
  {% if runs %}
  <table>
    <thead><tr><th>Tarea</th><th>Inicio</th><th>Fin</th><th>Estado</th><th>Exit</th></tr></thead>
    <tbody>
    {% for run in runs %}
      <tr>
        <td>{{ job_names.get(run['job_id'], '#' ~ run['job_id']) }}</td>
        <td class="muted">{{ run['started_at'] }}</td>
        <td class="muted">{{ run['finished_at'] or '—' }}</td>
        <td>{{ pill(run['status']) }}</td>
        <td>{{ run['exit_code'] if run['exit_code'] is not none else '—' }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="muted">Sin ejecuciones registradas todavía.</p>
  {% endif %}
</section>"""

JOB_FORM_CONTENT = """<section class="card" style="max-width:720px">
  <h2>{{ 'Editar tarea' if job else 'Nueva tarea' }}</h2>
  {% if error %}<div class="alert-err">{{ error }}</div>{% endif %}
  <form method="post" action="{{ action_url }}">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <div class="field">
      <label for="name">Nombre</label>
      <input id="name" name="name" required autofocus value="{{ values.get('name','') }}"
             placeholder="Backup diario de BD">
    </div>
    <div class="grid-2">
      <div class="field">
        <label for="cron_expr">Expresión cron (5 campos)</label>
        <input id="cron_expr" name="cron_expr" required
               value="{{ values.get('cron_expr','') }}" placeholder="30 3 * * *">
        <div class="helper">min · hora · día del mes · mes · día de semana</div>
      </div>
      <div class="field">
        <label for="timeout_sec">Timeout (segundos, 0 = sin límite)</label>
        <input id="timeout_sec" name="timeout_sec" type="number" min="0"
               value="{{ values.get('timeout_sec', 3600) }}">
        <div class="helper">{{ cron_hint }}</div>
      </div>
    </div>
    <div class="field">
      <label for="command">Comando</label>
      <textarea id="command" name="command" required
                placeholder="tar -czf /backups/$(date +\\%F).tar.gz /var/lib/mysql">{{ values.get('command','') }}</textarea>
    </div>
    <div class="field">
      <label for="comment">Comentario (opcional)</label>
      <input id="comment" name="comment" value="{{ values.get('comment','') }}">
    </div>
    <div class="field">
      <label style="display:flex; align-items:center; gap:.5rem; font-size:.9rem;">
        <input type="checkbox" name="enabled" style="width:auto"
               {% if values.get('enabled', 1) %}checked{% endif %}>
        Activa (el worker la ejecutará)
      </label>
    </div>
    <div class="form-actions">
      <a class="btn cancel" href="{{ url_for('dashboard') }}">Cancelar</a>
      <button type="submit" class="btn">Guardar</button>
    </div>
  </form>
</section>"""

PASSWORD_CONTENT = """<section class="card" style="max-width:480px">
  <h2>Cambiar contraseña</h2>
  {% if error %}<div class="alert-err">{{ error }}</div>{% endif %}
  <form method="post" action="{{ url_for('password_page') }}">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <div class="field"><label>Contraseña actual</label>
      <input type="password" name="old_password" required
             autocomplete="current-password"></div>
    <div class="field"><label>Nueva contraseña</label>
      <input type="password" name="new_password" required minlength="8"
             autocomplete="new-password"></div>
    <div class="field"><label>Repite la nueva contraseña</label>
      <input type="password" name="new_password2" required minlength="8"
             autocomplete="new-password"></div>
    <div class="form-actions">
      <a class="btn cancel" href="{{ url_for('dashboard') }}">Cancelar</a>
      <button type="submit" class="btn">Guardar</button>
    </div>
  </form>
</section>"""


# -------------------------------------------------------------------- app --


def create_app(config_path: str | None = None) -> Flask:
    """App factory: build the Flask GUI with the resolved config."""
    cfg = load_config(config_path)
    db_path = resolve_db_path(cfg)
    worker_name = str(cfg.get("worker", {}).get("name", "worker"))
    app = Flask(__name__)
    app.config["WORKER_DB"] = str(db_path)
    app.config["WORKER_NAME"] = worker_name

    def db():
        return store.connect(app.config["WORKER_DB"])

    # ---- sesión: secret persistido en la BD local ----
    conn = db()
    try:
        store.ensure_bootstrap_user(conn)
        secret = store.get_meta(conn, "webgui_secret")
        if not secret:
            secret = secrets.token_hex(32)
            store.set_meta(conn, "webgui_secret", secret)
            conn.commit()
    finally:
        conn.close()
    app.secret_key = secret

    # ---- helpers ----
    def current_user_id() -> int | None:
        return session.get("uid")

    def fresh_csrf() -> None:
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)

    def check_csrf() -> bool:
        sent = request.form.get("csrf", "")
        return bool(sent and secrets.compare_digest(sent, session.get("csrf", "")))

    def page(title: str, content: str):
        conn = db()
        try:
            revision = store.get_meta(conn, "revision")
            default_pw = store.uses_default_password(conn)
        finally:
            conn.close()
        fresh_csrf()
        return render_template_string(
            SHELL,
            title=title,
            app_name=APP_NAME,
            worker_name=app.config["WORKER_NAME"],
            revision=revision,
            default_password=default_pw,
            csrf=session["csrf"],
            content=content,
            app_css=APP_CSS.replace("\n", " "),
        )

    # ---- guard de sesión (login y /health públicos) ----

    @app.before_request
    def require_login():
        if request.endpoint in {"login", "health", "static", "api_jobs"}:
            return None
        if current_user_id() is None:
            return redirect(url_for("login", next=request.path))
        return None

    # ---- login ----

    @app.route("/login", methods=["GET", "POST"])
    def login():
        fresh_csrf()
        error = ""
        username = ""
        if request.method == "POST":
            if not check_csrf():
                abort(400)
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not username or not password:
                error = "Todos los campos son obligatorios"
            else:
                conn = db()
                try:
                    uid = store.verify_user(conn, username, password)
                finally:
                    conn.close()
                if uid is not None:
                    session["uid"] = uid
                    session["username"] = username
                    return redirect(request.args.get("next") or url_for("dashboard"))
                error = "Credenciales inválidas"
        return render_template_string(
            LOGIN_PAGE,
            app_name=APP_NAME,
            app_subtitle=APP_SUBTITLE,
            login_css=LOGIN_CSS.replace("\n", " "),
            error=error,
            username=username,
            csrf=session["csrf"],
        )

    @app.route("/logout", methods=["POST"])
    def logout():
        if not check_csrf():
            abort(400)
        session.clear()
        return redirect(url_for("login"))

    # ---- cambio de contraseña ----

    @app.route("/password", methods=["GET", "POST"])
    def password_page():
        error = ""
        if request.method == "POST":
            if not check_csrf():
                abort(400)
            old = request.form.get("old_password", "")
            new = request.form.get("new_password", "")
            new2 = request.form.get("new_password2", "")
            if len(new) < 8:
                error = "La nueva contraseña debe tener al menos 8 caracteres"
            elif new != new2:
                error = "Las contraseñas nuevas no coinciden"
            else:
                conn = db()
                try:
                    ok = store.change_password(conn, current_user_id(), old, new)
                    flash("Contraseña actualizada", "ok") if ok else None
                finally:
                    conn.close()
                if ok:
                    return redirect(url_for("dashboard"))
                error = "La contraseña actual no es correcta"
        return page("Contraseña", render_template_string(
            PASSWORD_CONTENT, error=error))

    # ---- dashboard ----

    @app.route("/")
    def dashboard():
        conn = db()
        try:
            jobs = store.list_jobs(conn)
            runs = conn.execute(
                "SELECT * FROM job_runs ORDER BY started_at DESC LIMIT 25"
            ).fetchall()
            revision = store.get_meta(conn, "revision")
        finally:
            conn.close()

        next_runs = {}
        for job in jobs:
            ok, msg = cron_check(str(job["cron_expr"]))
            next_runs[job["id"]] = msg.replace("próxima: ", "") if ok else "cron inválido"

        content = render_template_string(
            DASHBOARD_CONTENT,
            app_name=APP_NAME,
            worker_name=app.config["WORKER_NAME"],
            revision=revision,
            csrf=session.get("csrf", ""),
            jobs=jobs,
            runs=runs,
            next_runs=next_runs,
            job_names={j["id"]: j["name"] for j in jobs},
        )
        return page("Dashboard", content)

    # ---- CRUD de tareas ----

    def validate_form() -> tuple[dict | None, str, str]:
        """Devuelve (data, cron_hint, error)."""
        name = request.form.get("name", "").strip()
        cron_expr = request.form.get("cron_expr", "").strip()
        command = request.form.get("command", "").strip()
        comment = request.form.get("comment", "").strip()
        enabled = bool(request.form.get("enabled"))
        try:
            timeout_sec = max(0, int(request.form.get("timeout_sec") or 0))
        except ValueError:
            timeout_sec = 0

        ok, hint = cron_check(cron_expr)
        cron_hint = hint if ok else hint
        if not name or not command:
            return None, cron_hint, "Nombre y comando son obligatorios"
        if not ok:
            return None, cron_hint, f"Expresión cron inválida: {hint}"
        data = {
            "name": name, "cron_expr": cron_expr, "command": command,
            "timeout_sec": timeout_sec, "enabled": enabled,
            "comment": comment, "source": "local",
        }
        return data, cron_hint, ""

    def job_form(job, error: str = "", values: dict | None = None):
        conn = db()
        try:
            revision = store.get_meta(conn, "revision")
        finally:
            conn.close()
        if values is None:
            values = {
                "name": job["name"], "cron_expr": job["cron_expr"],
                "command": job["command"], "timeout_sec": job["timeout_sec"],
                "comment": job["comment"] or "", "enabled": job["enabled"],
            } if job else {"enabled": 1, "timeout_sec": 3600}
        fresh_csrf()
        content = render_template_string(
            JOB_FORM_CONTENT,
            job=job,
            action_url=(
                url_for("job_edit", job_id=job["id"]) if job
                else url_for("job_new")
            ),
            csrf=session["csrf"],
            error=error,
            values=values,
            cron_hint=(
                "expresión válida" if cron_check(str(values.get("cron_expr") or "* * * * *"))[0]
                else "revisa la expresión"
            ),
        )
        title = "Editar tarea" if job else "Nueva tarea"
        return page(title, content)

    @app.route("/jobs/new", methods=["GET", "POST"])
    def job_new():
        if request.method == "POST":
            if not check_csrf():
                abort(400)
            data, _, error = validate_form()
            if data is None:
                return job_form(None, error=error,
                                values={**request.form, "enabled": bool(request.form.get("enabled"))})
            conn = db()
            try:
                store.save_job(conn, data)
                flash(f"Tarea «{data['name']}» creada", "ok")
            finally:
                conn.close()
            return redirect(url_for("dashboard"))
        return job_form(None)

    @app.route("/jobs/<int:job_id>/edit", methods=["GET", "POST"])
    def job_edit(job_id: int):
        conn = db()
        try:
            job = store.get_job(conn, job_id)
            out_of_db = None
            if request.method == "POST":
                if not check_csrf():
                    abort(400)
                data, _, error = validate_form()
                if data is not None:
                    data["id"] = job_id
                    data["source"] = job["source"] if job else "local"
                    store.save_job(conn, data)
                    out_of_db = True
        finally:
            conn.close()
        if out_of_db:
            flash(f"Tarea #{job_id} actualizada", "ok")
            return redirect(url_for("dashboard"))
        if error:
            return job_form(job, error=error,
                            values={**request.form, "enabled": bool(request.form.get("enabled"))})
        if job is None:
            abort(404)
        return job_form(job)

    @app.route("/jobs/<int:job_id>/toggle", methods=["POST"])
    def job_toggle(job_id: int):
        if not check_csrf():
            abort(400)
        conn = db()
        try:
            job = store.get_job(conn, job_id)
            if job is None:
                abort(404)
            store.set_enabled(conn, job_id, not bool(job["enabled"]))
        finally:
            conn.close()
        return redirect(url_for("dashboard"))

    @app.route("/jobs/<int:job_id>/delete", methods=["POST"])
    def job_delete(job_id: int):
        if not check_csrf():
            abort(400)
        conn = db()
        try:
            job = store.get_job(conn, job_id)
            if job is None:
                abort(404)
            store.delete_job(conn, job_id)
        finally:
            conn.close()
        flash("Tarea eliminada", "ok")
        return redirect(url_for("dashboard"))

    # ---- públicos ----

    @app.get("/health")
    def health():
        from flask import jsonify

        return jsonify(status="ok", worker=app.config["WORKER_NAME"])

    @app.get("/api/jobs")
    def api_jobs():
        conn = db()
        try:
            rows = conn.execute(
                "SELECT id, name, cron_expr, command, timeout_sec, enabled,"
                " source, pending_sync, synced_at FROM jobs ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        from flask import jsonify

        return jsonify(jobs=[dict(r) for r in rows])

    return app


# Instancia gunicorn-ready: gunicorn "cronworker.webgui:app"
app: Flask = create_app()

if __name__ == "__main__":
    # Solo para desarrollo: usar gunicorn + Apache en producción
    cfg: dict = load_config()
    app.run(
        host=str(cfg.get("webgui", {}).get("listen_host", "127.0.0.1")),
        port=int(cfg.get("webgui", {}).get("listen_port", 8080)),
        debug=False,
    )
