"""Espejo local de jobs y usuarios del worker (SQLite).

Solo se toca desde store.py para garantizar un esquema consistente.
El worker sincroniza (pull) jobs desde el hosting y registra cada run local.
Los jobs creados desde la GUI local se guardan con source='local' y
pending_sync=1 para empujarse al hosting cuando la API esté disponible.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    cron_expr TEXT NOT NULL,
    command TEXT NOT NULL,
    timeout_sec INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    comment TEXT,
    source TEXT NOT NULL DEFAULT 'local',
    pending_sync INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('ok', 'failed', 'timeout')),
    exit_code INTEGER,
    output TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    pass_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open (and initialise/migrate) the local SQLite mirror.

    WAL + busy_timeout: la GUI corre con varios workers de gunicorn y todos
    abren su propia conexión; sin esto un lector bloquea a un escritor.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Columnas añadidas tras la primera versión: ALTER TABLE idempotente."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "source" not in cols:
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN source TEXT NOT NULL DEFAULT 'local'"
        )
    if "pending_sync" not in cols:
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN pending_sync INTEGER NOT NULL DEFAULT 0"
        )
    if "comment" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN comment TEXT")
    conn.commit()


# ---------------------------------------------------------------- usuarios --


def ensure_bootstrap_user(conn: sqlite3.Connection) -> bool:
    """Crea admin/admin la primera vez. Race-safe: con gunicorn multiproceso
    varios workers pueden ejecutarlo simultáneamente contra la misma BD."""
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if n:
        return False
    cur = conn.execute(
        "INSERT OR IGNORE INTO users (username, pass_hash) VALUES (?, ?)",
        ("admin", generate_password_hash("admin")),
    )
    created = bool(cur.rowcount)
    if created:
        set_meta(conn, "default_password", "1")
    conn.commit()
    return created


def verify_user(conn: sqlite3.Connection, username: str, password: str) -> int | None:
    """Devuelve el id del usuario si las credenciales son válidas."""
    row = conn.execute(
        "SELECT id, pass_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    if row and check_password_hash(row["pass_hash"], password):
        conn.execute(
            "UPDATE users SET last_login_at = datetime('now') WHERE id = ?",
            (row["id"],),
        )
        conn.commit()
        return int(row["id"])
    return None


def change_password(
    conn: sqlite3.Connection, user_id: int, old_password: str, new_password: str
) -> bool:
    """Cambia la contraseña verificando la anterior."""
    row = conn.execute(
        "SELECT pass_hash FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not row or not check_password_hash(row["pass_hash"], old_password):
        return False
    conn.execute(
        "UPDATE users SET pass_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id),
    )
    set_meta(conn, "default_password", "0")
    conn.commit()
    return True


def change_username(conn: sqlite3.Connection, user_id: int, new_username: str) -> bool:
    """Cambia el nombre de usuario. False si ya existe (UNIQUE)."""
    try:
        cur = conn.execute(
            "UPDATE users SET username = ? WHERE id = ?", (new_username, user_id)
        )
        conn.commit()
        return cur.rowcount == 1
    except sqlite3.IntegrityError:
        conn.rollback()
        return False


def get_username(conn: sqlite3.Connection, user_id: int) -> str:
    row = conn.execute(
        "SELECT username FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return row["username"] if row else ""


def uses_default_password(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'default_password'"
    ).fetchone()
    return bool(row and row["value"] == "1")


# --------------------------------------------------------------- jobs CRUD --


def list_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM jobs ORDER BY enabled DESC, name COLLATE NOCASE"
    ).fetchall()


def get_job(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def save_job(conn: sqlite3.Connection, data: dict) -> int | None:
    """Inserta o actualiza un job. Devuelve su id, o None si el UPDATE no
    encontró la fila (id inexistente)."""
    if data.get("id"):
        cur = conn.execute(
            "UPDATE jobs SET name=?, cron_expr=?, command=?, timeout_sec=?,"
            " enabled=?, comment=?, source=?, pending_sync=1,"
            " synced_at=datetime('now')"
            " WHERE id=?",
            (
                data["name"], data["cron_expr"], data["command"],
                data["timeout_sec"], int(data["enabled"]), data["comment"],
                data["source"], data["id"],
            ),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return None
        job_id = int(data["id"])
    else:
        cur = conn.execute(
            "INSERT INTO jobs (name, cron_expr, command, timeout_sec, enabled,"
            " comment, source, pending_sync, synced_at)"
            " VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
            (
                data["name"], data["cron_expr"], data["command"],
                data["timeout_sec"], int(data["enabled"]), data["comment"],
                data["source"], 1,
            ),
        )
        job_id = int(cur.lastrowid or 0)
    conn.commit()
    return job_id


def delete_job(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute("DELETE FROM job_runs WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()


def set_enabled(conn: sqlite3.Connection, job_id: int, enabled: bool) -> None:
    conn.execute(
        "UPDATE jobs SET enabled=?, pending_sync=1 WHERE id=?",
        (int(enabled), job_id),
    )
    conn.commit()


# ------------------------------------------------------------------- meta --


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
