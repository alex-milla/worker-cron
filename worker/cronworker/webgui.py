"""GUI local de monitorización del worker (Flask).

Sirve de dashboard: jobs sincronizados, últimas ejecuciones y estado de sync.
En producción se arranca con gunicorn y Apache hace de reverse proxy
(worker/deploy/cron-gui.service + worker/deploy/apache-cron-gui.conf).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, render_template_string

from . import store
from .config import load_config, resolve_db_path

log = logging.getLogger(__name__)

PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Worker Cron · {% block title %}Dashboard{% endblock %}</title>
  <style>
    :root { --bg:#f9fafb; --surface:#fff; --text:#111827; --muted:#6b7280;
            --border:#e5e7eb; --ok:#15803d; --bad:#b91c1c; --warn:#b45309; }
    body { margin:0; font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
           background:var(--bg); color:var(--text); }
    header { background:var(--surface); border-bottom:1px solid var(--border);
             padding:16px 24px; display:flex; justify-content:space-between; align-items:center; }
    h1 { font-size:1.25rem; margin:0; }
    main { max-width:1100px; margin:24px auto; padding:0 16px; }
    .card { background:var(--surface); border:1px solid var(--border);
            border-radius:12px; padding:20px; margin-bottom:16px; }
    h2 { margin:0 0 12px; font-size:1.05rem; }
    table { width:100%; border-collapse:collapse; font-size:.9rem; }
    th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--border); }
    th { font-size:.72rem; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
    tr:hover td { background:#f9fafb; }
    .pill { display:inline-block; padding:2px 10px; border-radius:999px; font-size:.75rem;
            font-weight:600; border:1px solid; }
    .pill.ok   { color:var(--ok);   border-color:var(--ok);   background:#dcfce7; }
    .pill.bad  { color:var(--bad);  border-color:var(--bad);  background:#fee2e2; }
    .pill.warn { color:var(--warn); border-color:var(--warn); background:#fef3c7; }
    .pill.off  { color:var(--muted); border-color:var(--border); background:#f3f4f6; }
    .muted { color:var(--muted); font-size:.85rem; }
    code { font-family:ui-monospace,'JetBrains Mono',monospace; font-size:.82rem;
           background:#f3f4f6; padding:1px 5px; border-radius:4px; }
  </style>
</head>
<body>
<header>
  <h1>⏱ Worker Cron · {{ worker_name }}</h1>
  <div class="muted">Revision sync: <code>{{ revision or 'sin sync' }}</code></div>
</header>
<main>
  <section class="card">
    <h2>Jobs sincronizados</h2>
    {% if jobs %}
    <table>
      <thead><tr><th>#</th><th>Nombre</th><th>Cron</th><th>Estado</th><th>Comando</th></tr></thead>
      <tbody>
      {% for job in jobs %}
        <tr>
          <td>{{ job['id'] }}</td>
          <td>{{ job['name'] }}</td>
          <td><code>{{ job['cron_expr'] }}</code></td>
          <td>{% if job['enabled'] %}<span class="pill ok">activo</span>
              {% else %}<span class="pill off">pausado</span>{% endif %}</td>
          <td><code>{{ job['command'] }}</code></td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="muted">Todavía no se ha sincronizado ningún job desde el hosting.</p>
    {% endif %}
  </section>

  <section class="card">
    <h2>Últimas ejecuciones</h2>
    {% if runs %}
    <table>
      <thead><tr><th>Job</th><th>Inicio</th><th>Fin</th><th>Estado</th><th>Exit code</th></tr></thead>
      <tbody>
      {% for run in runs %}
        <tr>
          <td>{{ job_names.get(run['job_id'], '#' ~ run['job_id']) }}</td>
          <td>{{ run['started_at'] }}</td>
          <td>{{ run['finished_at'] or '—' }}</td>
          <td>
            {% if run['status'] == 'ok' %}<span class="pill ok">ok</span>
            {% elif run['status'] == 'timeout' %}<span class="pill warn">timeout</span>
            {% else %}<span class="pill bad">fallo</span>{% endif %}
          </td>
          <td>{{ run['exit_code'] if run['exit_code'] is not none else '—' }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="muted">Sin ejecuciones registradas todavía.</p>
    {% endif %}
  </section>
</main>
</body>
</html>"""


def create_app(config_path: str | Path | None = None) -> Flask:
    """App factory: build the Flask GUI with the resolved config."""
    cfg = load_config(config_path)
    db_path = resolve_db_path(cfg)
    worker_name = str(cfg.get("worker", {}).get("name", "worker"))
    app = Flask(__name__)
    app.config["WORKER_DB"] = str(db_path)
    app.config["WORKER_NAME"] = worker_name

    @app.get("/")
    def dashboard():
        conn = None
        try:
            conn = store.connect(app.config["WORKER_DB"])
            jobs = conn.execute(
                "SELECT id, name, cron_expr, command, enabled FROM jobs ORDER BY id"
            ).fetchall()
            runs = conn.execute(
                "SELECT * FROM job_runs ORDER BY started_at DESC LIMIT 25"
            ).fetchall()
            revision = conn.execute(
                "SELECT value FROM meta WHERE key = 'revision'"
            ).fetchone()
        except sqlite3.Error as exc:
            log.warning("No se pudo leer la BD local: %s", exc)
            jobs, runs, revision = [], [], None
        finally:
            if conn is not None:
                conn.close()

        html = render_template_string(
            PAGE,
            worker_name=app.config["WORKER_NAME"],
            revision=revision["value"] if revision else None,
            jobs=jobs,
            runs=runs,
            job_names={j["id"]: j["name"] for j in jobs},
        )
        return html

    @app.get("/health")
    def health():
        return jsonify(status="ok", worker=app.config["WORKER_NAME"])

    @app.get("/api/jobs")
    def api_jobs():
        conn = store.connect(app.config["WORKER_DB"])
        try:
            rows = conn.execute(
                "SELECT id, name, cron_expr, command, timeout_sec, enabled, synced_at"
                " FROM jobs ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        return jsonify(jobs=[dict(r) for r in rows])

    return app


# Instancia gunicorn-ready: gunicorn "cronworker.webgui:app"
cfg: dict = load_config()
app: Flask = create_app()

if __name__ == "__main__":
    # Solo para desarrollo: usar gunicorn + Apache en producción
    app.run(
        host=str(cfg.get("webgui", {}).get("listen_host", "127.0.0.1")),
        port=int(cfg.get("webgui", {}).get("listen_port", 8080)),
        debug=False,
    )
