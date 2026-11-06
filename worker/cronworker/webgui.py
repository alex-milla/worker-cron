"""GUI local de monitorización y gestión del worker (Flask).

Pantallas:
    /login     — Pantsalla de acceso (sesión por cookie + CSRF)
    /          — Dashboard: jobs, próximas ejecuciones, últimas corridas
    /jobs/new  — Crear tarea (validación cron; se marca pending_sync para el hosting)
    /jobs/<id> — Editar / eliminar / activar-pausar
    /password  — Perfil y contraseña (usuario + contraseña)

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
from pathlib import Path

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
from markupsafe import Markup

from . import store, updater
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
    /* ===== tokens extra del shell (claro / oscuro) ===== */
    .app-shell { --surface-2:#f1f5f9; --input-bg:#ffffff; --input-border:#d1d5db;
        --brand-border:#fed7aa; --brand-soft:#fff7ed;
        --nav-active-bg:#fff7ed; --nav-active-text:#c2410c; --row-hover:#fff7ed; }
    [data-theme="dark"] .app-shell { --surface-2:#1e293b; --input-bg:#1e293b;
        --input-border:#4b5563; --brand-border:#7c2d12; --brand-soft:#431407;
        --brand-hover:#fdba74; --nav-active-bg:#431407; --nav-active-text:#fdba74;
        --row-hover:rgba(249,115,22,.12); }

    /* ===== shell: sidebar vertical 256px + topbar 64px + footer ===== */
    .app-shell { display:flex; min-height:100vh; }
    .shell-overlay { display:none; }
    .app-sidebar { width:256px; flex-shrink:0; position:sticky; top:0; height:100vh;
        display:flex; flex-direction:column; background:var(--surface);
        border-right:1px solid var(--border); z-index:30; }
    .sidebar-brand { display:flex; align-items:center; gap:.75rem; flex-shrink:0;
        height:64px; padding:0 1.25rem; border-bottom:1px solid var(--border);
        font-weight:700; font-size:1.08rem; }
    .sidebar-logo { display:inline-flex; align-items:center; justify-content:center;
        width:2rem; height:2rem; border-radius:.5rem; background:var(--brand);
        color:#fff; font-size:1.1rem; flex-shrink:0; }
    .sidebar-nav { flex:1 1 auto; overflow-y:auto; padding:.75rem; }
    .sidebar-group-label { font-size:.7rem; font-weight:600; text-transform:uppercase;
        letter-spacing:.06em; color:var(--muted); padding:1rem .75rem .3rem; }
    .sidebar-group-label:first-child { padding-top:.25rem; }
    .sidebar-link { display:flex; align-items:center; gap:.75rem; margin-bottom:2px;
        padding:.5rem .75rem; border-radius:.5rem; font-size:.9rem; font-weight:500;
        color:var(--muted); }
    .sidebar-link svg { flex-shrink:0; }
    .sidebar-link:hover { background:var(--surface-2); color:var(--text); }
    .sidebar-link.active { background:var(--nav-active-bg); color:var(--nav-active-text); }
    .sidebar-foot { flex-shrink:0; padding:.7rem 1.25rem; border-top:1px solid var(--border);
        font-size:.75rem; color:var(--muted-soft); }
    .app-main { flex:1 1 auto; min-width:0; display:flex; flex-direction:column; min-height:100vh; }
    .app-header { position:sticky; top:0; z-index:25; display:flex; align-items:center;
        justify-content:space-between; gap:1rem; height:64px; flex-shrink:0;
        padding:0 1.5rem; background:var(--surface); border-bottom:1px solid var(--border); }
    .h-left { display:flex; align-items:center; gap:.55rem; min-width:0; }
    .page-title { margin:0; font-size:1.15rem; font-weight:600; white-space:nowrap;
        overflow:hidden; text-overflow:ellipsis; }
    .h-actions { display:flex; align-items:center; gap:.25rem; flex-shrink:0; }
    .icon-btn { display:inline-flex; align-items:center; justify-content:center;
        width:2.5rem; height:2.5rem; border:none; border-radius:.5rem;
        background:transparent; color:var(--muted); cursor:pointer; }
    .icon-btn:hover { background:var(--surface-2); color:var(--text); }
    .shell-menu { display:none; }
    .user-menu { position:relative; }
    .user-btn { display:inline-flex; align-items:center; gap:.5rem; padding:.4rem .7rem;
        border:none; border-radius:.5rem; background:transparent; color:var(--text);
        font-size:.9rem; font-weight:500; cursor:pointer; }
    .user-btn:hover { background:var(--surface-2); }
    .user-role { font-size:.7rem; font-weight:600; color:var(--brand-hover);
        background:var(--brand-soft); border:1px solid var(--brand-border);
        border-radius:999px; padding:1px .5rem; }
    .user-panel { display:none; position:absolute; right:0; top:100%; min-width:230px;
        margin:.4rem 0 0; padding:.35rem 0; list-style:none; z-index:120;
        background:var(--surface); border:1px solid var(--border); border-radius:.75rem;
        box-shadow:0 12px 32px rgba(0,0,0,.18); }
    .user-menu.open .user-panel { display:block; }
    .user-panel li a, .user-panel li button { display:flex; align-items:center; gap:.7rem;
        width:100%; padding:.6rem 1rem; border:none; background:transparent;
        color:var(--text); font-size:.9rem; cursor:pointer; text-align:left; }
    .user-panel li a:hover, .user-panel li button:hover { background:var(--surface-2); }
    .user-panel li.sep { border-top:1px solid var(--border); margin:.35rem 0; }
    .page-container { width:100%; max-width:1440px; margin:0 auto; padding:1.5rem 1rem 3rem; }
    .page-footer { border-top:1px solid var(--border); background:var(--surface); }
    .page-footer .inner { max-width:1440px; margin:0 auto; display:flex; gap:1rem;
        align-items:center; justify-content:space-between; padding:1.1rem 1rem;
        font-size:.85rem; color:var(--muted); }
    [data-theme="light"] .icon-sun { display:none; }
    [data-theme="dark"] .icon-moon { display:none; }

    /* ===== componentes (contrato de clases según ESPECIFICACION-UI) ===== */
    .card { background:var(--surface); border:1px solid var(--border);
        border-radius:.75rem; padding:1.5rem; margin-bottom:1rem; }
    h2 { margin:0 0 .75rem; font-size:1.05rem; display:flex; align-items:center; gap:.5rem; }
    .toolbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; }
    .warn-banner { background:#fef3c7; border:1px solid #fde68a; color:#92400e;
        padding:.6rem .9rem; border-radius:.5rem; font-size:.875rem; margin-bottom:1rem; }
    [data-theme="dark"] .warn-banner { background:rgba(120,53,15,.3);
        border-color:rgba(120,53,15,.5); color:#fcd34d; }
    .warn-banner a { text-decoration:underline; color:inherit; }
    .alert-ok { background:#dcfce7; border:1px solid #bbf7d0; color:#15803d;
        padding:.6rem .9rem; border-radius:.5rem; font-size:.875rem; margin-bottom:1rem; }
    .alert-err { background:#fee2e2; border:1px solid #fca5a5; color:#b91c1c;
        padding:.6rem .9rem; border-radius:.5rem; font-size:.875rem; margin-bottom:1rem; }
    [data-theme="dark"] .alert-ok { background:rgba(20,83,45,.3);
        border-color:rgba(20,83,45,.5); color:#86efac; }
    [data-theme="dark"] .alert-err { background:rgba(127,29,29,.3);
        border-color:rgba(127,29,29,.5); color:#fca5a5; }
    table { width:100%; border-collapse:collapse; font-size:.9rem; }
    th, td { text-align:left; padding:.55rem .7rem; border-bottom:1px solid var(--border);
        vertical-align:middle; }
    th { font-size:.72rem; font-weight:600; text-transform:uppercase;
        letter-spacing:.05em; color:var(--muted); }
    tbody tr:hover td { background:var(--row-hover); }
    .pill { display:inline-block; padding:2px 10px; border-radius:999px;
        font-size:.75rem; font-weight:600; border:1px solid; white-space:nowrap; }
    .pill.ok { color:var(--ok); border-color:#bbf7d0; background:#dcfce7; }
    .pill.bad { color:var(--bad); border-color:#fca5a5; background:#fee2e2; }
    .pill.warn { color:var(--warn); border-color:#fde68a; background:#fef3c7; }
    .pill.off { color:var(--muted); border-color:var(--border); background:var(--surface-2); }
    .pill.brand { color:var(--brand-hover); border-color:var(--brand-border);
        background:var(--brand-soft); }
    [data-theme="dark"] .pill.ok { background:rgba(20,83,45,.3); border-color:rgba(20,83,45,.5); }
    [data-theme="dark"] .pill.bad { background:rgba(127,29,29,.3); border-color:rgba(127,29,29,.5); }
    [data-theme="dark"] .pill.warn { background:rgba(120,53,15,.3); border-color:rgba(120,53,15,.5); }
    .muted { color:var(--muted); font-size:.85rem; }
    .mono { font-family:ui-monospace,"JetBrains Mono",monospace; font-size:.82rem; }
    .row-actions { display:flex; gap:.4rem; white-space:nowrap; }
    .row-actions button, .row-actions a { padding:.3rem .6rem; font-size:.78rem;
        border:1px solid var(--border); background:var(--surface);
        border-radius:.4rem; cursor:pointer; color:var(--text); }
    .row-actions button:hover, .row-actions a:hover { background:var(--surface-2); }
    .row-actions .danger { color:#b91c1c; border-color:#fca5a5; }
    .row-actions .danger:hover { background:#fee2e2; }
    [data-theme="dark"] .row-actions .danger { color:#fca5a5; }
    .field { margin-bottom:.9rem; }
    .field label { display:block; font-size:.78rem; font-weight:500;
        color:var(--muted); margin-bottom:.3rem; }
    .field input, .field textarea { width:100%; padding:.55rem .75rem;
        border-radius:.5rem; border:1px solid var(--input-border);
        background:var(--input-bg); color:var(--text); font-size:.92rem; outline:none; }
    .field input:focus, .field textarea:focus { box-shadow:0 0 0 2px var(--focus);
        border-color:transparent; }
    .grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:1rem; }
    textarea { font-family:ui-monospace,monospace; min-height:96px; resize:vertical; }
    .helper { font-size:.75rem; color:var(--muted); margin-top:.25rem; }
    .form-actions { display:flex; gap:.6rem; justify-content:flex-end;
        margin-top:1.2rem; padding-top:1rem; border-top:1px solid var(--border); }
    .form-actions .btn { width:auto; padding:.55rem 1.2rem; }
    .form-actions .cancel { background:var(--surface); color:var(--muted);
        border:1px solid var(--border); }
    .btn { padding:.55rem 1.2rem; background:var(--brand); color:#fff; border:none;
        border-radius:.5rem; font-weight:500; font-size:.92rem; cursor:pointer;
        transition:background .15s; text-decoration:none; display:inline-flex;
        align-items:center; gap:.5rem; }
    .btn:hover { background:var(--brand-hover); }
    details summary { cursor:pointer; }
    .card input[type="checkbox"] { width:auto; }

    /* ===== responsive: sidebar como drawer < lg (1024px) ===== */
    @media (max-width:1023px) {
        .shell-menu { display:inline-flex; }
        .shell-overlay { position:fixed; inset:0; background:rgba(0,0,0,.5); z-index:40; }
        .app-shell.drawer-open .shell-overlay { display:block; }
        .app-sidebar { position:fixed; inset:0 auto 0 0; transform:translateX(-100%);
            transition:transform .2s ease; box-shadow:0 0 40px rgba(0,0,0,.3); }
        .app-shell.drawer-open .app-sidebar { transform:none; }
        .grid-2 { grid-template-columns:1fr; }
    }
"""

BASE_CSS_TAG = "<style>{}</style>"

def _svg(body, size=18, css_class=""):
    # Markup: los iconos viajan como HTML de confianza (render_template_string
    # auto-escapa por defecto y sin esto se vería el código SVG en pantalla).
    # La clase va como parámetro: Markup.replace() ESCAPA sus argumentos y
    # usar .replace('<svg ', ...) rompía los iconos de sol/luna.
    cls = f' class="{css_class}"' if css_class else ""
    return Markup(
        f'<svg{cls} width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{body}</svg>'
    )

ICONS = {
    "menu": _svg('<line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/>'
                 '<line x1="4" y1="18" x2="20" y2="18"/>', 20),
    "grid": _svg('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>'
                 '<rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>'),
    "clock": _svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    "update": _svg('<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>'),
    "person": _svg('<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6.5 8-6.5s8 2.5 8 6.5"/>'),
    "logout": _svg('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
                   '<path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>'),
    "chevron": _svg('<path d="M6 9l6 6 6-6"/>'),
    "sun": _svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4'
                'M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
                20, "icon-sun"),
    "moon": _svg('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
                 20, "icon-moon"),
}


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
<html lang="es" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} · {{ app_name }}</title>
  <style>{{ app_css }}</style>
  <script>(function(){try{var t=localStorage.getItem('cw-theme');if(t==='dark'||t==='light'){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();</script>
</head>
<body>
<div class="app-shell">

  <div class="shell-overlay" data-shell-overlay></div>

  <aside class="app-sidebar" id="app-sidebar" aria-label="Navegación principal">
    <a class="sidebar-brand" href="{{ url_for('dashboard') }}">
      <span class="sidebar-logo">⏱</span><span>{{ app_name }}</span>
    </a>
    <nav class="sidebar-nav">
      <div class="sidebar-group-label">Gestión</div>
      <a class="sidebar-link{{ ' active' if active == 'dashboard' }}" href="{{ url_for('dashboard') }}">
        {{ icons.grid }}Dashboard</a>
      <a class="sidebar-link{{ ' active' if active == 'jobs' }}" href="{{ url_for('job_new') }}">
        {{ icons.clock }}Tareas</a>
      <div class="sidebar-group-label">Sistema</div>
      <a class="sidebar-link{{ ' active' if active == 'updates' }}" href="{{ url_for('updates_page') }}">
        {{ icons.update }}Actualizaciones</a>
      <a class="sidebar-link{{ ' active' if active == 'profile' }}" href="{{ url_for('password_page') }}">
        {{ icons.person }}Perfil y contraseña</a>
    </nav>
    <div class="sidebar-foot mono">v{{ version }} · {{ worker_name }}</div>
  </aside>

  <div class="app-main">
    <header class="app-header">
      <div class="h-left">
        <button type="button" class="icon-btn shell-menu" data-shell-menu aria-label="Abrir menú">
          {{ icons.menu }}</button>
        <h1 class="page-title">{{ title }}</h1>
      </div>
      <div class="h-actions">
        <button type="button" class="icon-btn" data-theme-toggle aria-label="Cambiar tema">
          {{ icons.moon }}{{ icons.sun }}</button>
        <div class="user-menu" data-user-menu>
          <button type="button" class="user-btn" data-user-menu-toggle aria-expanded="false">
            {{ icons.person }}<span>{{ user or 'admin' }}</span>
            <span class="user-role">admin</span>{{ icons.chevron }}</button>
          <ul class="user-panel">
            <li><a href="{{ url_for('password_page') }}">{{ icons.person }}Perfil y contraseña</a></li>
            <li class="sep" role="separator"></li>
            <li><form method="post" action="{{ url_for('logout') }}">
              <input type="hidden" name="csrf" value="{{ csrf }}">
              <button type="submit">{{ icons.logout }}Salir</button></form></li>
          </ul>
        </div>
      </div>
    </header>

    <main>
      <div class="page-container">
        {{ content|safe }}
      </div>
    </main>

    <footer class="page-footer">
      <div class="inner">
        <span>{{ app_name }} — programador de crons</span>
        <span class="mono">v{{ version }} · {{ worker_name }}</span>
      </div>
    </footer>
  </div>
</div>

<script>
(function(){
  'use strict';
  var d = document.documentElement;
  function mode(){ return d.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'; }
  var tt = document.querySelector('[data-theme-toggle]');
  if (tt) tt.addEventListener('click', function(){
    var n = mode() === 'dark' ? 'light' : 'dark';
    d.setAttribute('data-theme', n);
    try { localStorage.setItem('cw-theme', n); } catch (e) {}
  });

  var shell = document.querySelector('.app-shell');
  var mbtn = document.querySelector('[data-shell-menu]');
  var ov = document.querySelector('[data-shell-overlay]');
  if (mbtn && shell) mbtn.addEventListener('click', function(){ shell.classList.toggle('drawer-open'); });
  if (ov && shell) ov.addEventListener('click', function(){ shell.classList.remove('drawer-open'); });
  document.querySelectorAll('.sidebar-link').forEach(function(a){
    a.addEventListener('click', function(){ if (shell) shell.classList.remove('drawer-open'); });
  });
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape' && shell) shell.classList.remove('drawer-open'); });

  var um = document.querySelector('[data-user-menu]');
  var ub = document.querySelector('[data-user-menu-toggle]');
  if (ub && um) {
    ub.addEventListener('click', function(e){ e.stopPropagation(); um.classList.toggle('open');
      ub.setAttribute('aria-expanded', um.classList.contains('open') ? 'true' : 'false'); });
    document.addEventListener('click', function(e){ if (!um.contains(e.target)) um.classList.remove('open'); });
    document.addEventListener('keydown', function(e){ if (e.key === 'Escape') um.classList.remove('open'); });
  }
})();
</script>
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

UPDATES_CONTENT = """<section class="card">
  <h2>Actualizaciones desde GitHub</h2>
  {% if error %}<div class="alert-err">{{ error }}</div>{% endif %}
  {% if result %}
    {% if result.updated %}
      <div class="alert-ok">Actualizado a <strong>v{{ result.remote }}</strong>
        (copiados: {{ result.copied }} · borrados: {{ result.deleted }} ·
         sin cambios: {{ result.skipped }} · errores: {{ result.errors }})
        {% if result.error_detail %}<br><small>{{ result.error_detail|join('<br>') }}</small>{% endif %}
        <br>Reinicia el worker para aplicar los cambios:
        <code>systemctl restart cron-worker cron-gui</code></div>
    {% else %}
      <div class="alert-ok">{{ result.message }}</div>
    {% endif %}
  {% endif %}
  <table>
    <thead><tr><th>Instalada</th><th>Última en GitHub</th><th>Repositorio</th></tr></thead>
    <tbody><tr>
      <td>v{{ current }}</td>
      <td>{% if remote %}v{{ remote }}{% if release_source %} <span class="pill off">({{ release_source }})</span>{% endif %}
          {% else %}<span class="muted">sin releases publicadas</span>{% endif %}</td>
      <td class="mono">{{ repo }}</td>
    </tr></tbody>
  </table>
  {% if notes %}
  <details style="margin-top:12px"><summary class="muted" style="cursor:pointer">Notas de la release</summary>
    <pre style="white-space:pre-wrap; font-size:.85rem; color:var(--text)">{{ notes }}</pre></details>
  {% endif %}
  <div class="form-actions">
    <form method="post" action="{{ url_for('updates_page') }}"
          onsubmit="return confirm('¿Instalar v{{ remote }}? Se hará backup antes.');">
      <input type="hidden" name="csrf" value="{{ csrf }}">
      <input type="hidden" name="action" value="install">
      <button type="submit" class="btn" {% if not remote %}disabled{% endif %}>Instalar última versión</button>
    </form>
    <form method="post" action="{{ url_for('updates_page') }}">
      <input type="hidden" name="csrf" value="{{ csrf }}">
      <input type="hidden" name="action" value="reinstall">
      <button type="submit" class="btn cancel">Reinstalar (forzar)</button>
    </form>
  </div>
</section>

<section class="card">
  <h2>Backups</h2>
  {% if backups %}
  <table>
    <thead><tr><th>Backup</th><th>Acción</th></tr></thead>
    <tbody>
    {% for b in backups[:10] %}
      <tr>
        <td class="mono">{{ b.name }}</td>
        <td>
          <form method="post" action="{{ url_for('updates_page') }}" style="display:inline"
                onsubmit="return confirm('¿Restaurar {{ b.name }}? Se hará backup previo del estado actual.');">
            <input type="hidden" name="csrf" value="{{ csrf }}">
            <input type="hidden" name="action" value="restore">
            <input type="hidden" name="backup" value="{{ b.name }}">
            <button type="submit">Restaurar</button>
          </form>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="muted">Sin backups todavía: se crean automáticamente antes de instalar o restaurar.</p>
  {% endif %}
</section>"""

PASSWORD_CONTENT = """<section class="card" style="max-width:480px">
  <h2>Perfil y contraseña</h2>
  {% if error %}<div class="alert-err">{{ error }}</div>{% endif %}
  <form method="post" action="{{ url_for('password_page') }}">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <div class="field"><label>Nombre de usuario</label>
      <input type="text" name="username" required minlength="3" value="{{ current_username }}"
             autocomplete="username">
      <div class="helper">Con esto entrarás la próxima vez</div></div>
    <div class="field"><label>Contraseña actual</label>
      <input type="password" name="old_password" autocomplete="current-password"></div>
    <div class="field"><label>Nueva contraseña</label>
      <input type="password" name="new_password" minlength="8"
             autocomplete="new-password"></div>
    <div class="field"><label>Repite la nueva contraseña</label>
      <input type="password" name="new_password2" minlength="8"
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
    vfile = Path(__file__).resolve().parent.parent / "VERSION"
    app.config["APP_VERSION"] = vfile.read_text(encoding="utf-8").strip() if vfile.is_file() else "0.0.0"

    def db():
        return store.connect(app.config["WORKER_DB"])

    # ---- sesión: secret persistido en la BD local (race-safe entre workers) ----
    conn = db()
    try:
        store.ensure_bootstrap_user(conn)
        secret = store.get_meta(conn, "webgui_secret")
        if not secret:
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('webgui_secret', ?)",
                (secrets.token_hex(32),),
            )
            conn.commit()
            # si perdió la carrera, usa el que ya guardó otro worker
            secret = store.get_meta(conn, "webgui_secret")
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
        path = request.path
        active = ("dashboard" if path == "/" else
                  "jobs" if path.startswith("/jobs") else
                  "updates" if path.startswith("/updates") else
                  "profile" if path.startswith("/password") else "")
        return render_template_string(
            SHELL,
            title=title,
            app_name=APP_NAME,
            worker_name=app.config["WORKER_NAME"],
            version=app.config["APP_VERSION"],
            user=session.get("username", ""),
            active=active,
            icons=ICONS,
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
        fresh_csrf()
        error = ""
        uid = current_user_id()
        if request.method == "POST":
            if not check_csrf():
                abort(400)
            old = request.form.get("old_password", "")
            new = request.form.get("new_password", "")
            new2 = request.form.get("new_password2", "")
            conn = db()
            try:
                # 1) nombre de usuario (opcional)
                current_username = store.get_username(conn, uid)
                new_username = request.form.get("username", "").strip()
                if new_username and new_username != current_username:
                    if len(new_username) < 3:
                        error = "El nombre de usuario debe tener al menos 3 caracteres"
                    elif not store.change_username(conn, uid, new_username):
                        error = "Ese nombre de usuario ya está en uso"
                    else:
                        session["username"] = new_username
                        flash("Usuario actualizado", "ok")
                # 2) contraseña (si se han rellenado los campos)
                if not error and (old or new or new2):
                    if len(new) < 8:
                        error = "La nueva contraseña debe tener al menos 8 caracteres"
                    elif new != new2:
                        error = "Las contraseñas nuevas no coinciden"
                    elif not store.change_password(conn, uid, old, new):
                        error = "La contraseña actual no es correcta"
                    else:
                        flash("Contraseña actualizada", "ok")
                if not error:
                    return redirect(url_for("dashboard"))
                current_username = store.get_username(conn, uid)
            finally:
                conn.close()
        else:
            conn = db()
            try:
                current_username = store.get_username(conn, uid)
            finally:
                conn.close()
        content = render_template_string(
            PASSWORD_CONTENT,
            error=error,
            csrf=session["csrf"],
            current_username=current_username,
        )
        return page("Perfil", content)

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

    # ---- actualizaciones desde GitHub ----

    @app.route("/updates", methods=["GET", "POST"])
    def updates_page():
        app_root = Path(__file__).resolve().parent.parent
        current = updater.installed_version(app_root)
        error = result = None
        remote = notes = release_source = None

        try:
            release = updater.get_latest_release()
            if release:
                remote = release["version"]
                notes = release["notes"]
                release_source = release["source"]
        except Exception as exc:  # noqa: BLE001 - se muestra en la pantalla
            error = f"No se pudo consultar GitHub: {exc}"

        if request.method == "POST":
            if not check_csrf():
                abort(400)
            action = request.form.get("action", "")
            try:
                if action == "install":
                    result = updater.update(app_root, force=False)
                elif action == "reinstall":
                    result = updater.update(app_root, force=True)
                elif action == "restore":
                    res = updater.restore_backup(
                        request.form.get("backup", ""), app_root)
                    flash(f"Backup restaurado ({res['restored']} ficheros)", "ok")
                    return redirect(url_for("updates_page"))
                else:
                    abort(400)
            except Exception as exc:  # noqa: BLE001 - mensaje directo
                error = str(exc)
            if result and result.get("updated"):
                current = result["remote"]
                remote = None if result.get("updated") else remote

        content = render_template_string(
            UPDATES_CONTENT,
            current=current,
            remote=remote,
            notes=notes,
            release_source=release_source,
            result=result,
            error=error,
            repo=f"{updater.REPO_OWNER}/{updater.REPO_NAME}",
            backups=updater.list_backups(app_root),
            csrf=session.get("csrf", ""),
        )
        return page("Actualizaciones", content)

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
