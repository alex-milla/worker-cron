-- Esquema SQLite del panel (hosting compartido)

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    pass_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT,
    /* sello temporal del último cambio de contraseña: invalida sesiones viejas */
    password_changed_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    /* expresión cron estándar de 5 campos */
    cron_expr TEXT NOT NULL,
    /* comando a ejecutar en el worker */
    command TEXT NOT NULL,
    /* timeout en segundos (0 = sin límite definido por el panel) */
    timeout_sec INTEGER NOT NULL DEFAULT 3600,
    /* el worker solo sincroniza jobs con enabled=1 */
    enabled INTEGER NOT NULL DEFAULT 1,
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

/* Resultados reportados por el worker */
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    /* fecha/hora de inicio de la ejecución en el worker (UTC, ISO-8601) */
    started_at TEXT NOT NULL,
    finished_at TEXT,
    /* ok | failed | timeout */
    status TEXT NOT NULL,
    exit_code INTEGER,
    output TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_runs_job ON job_runs(job_id, started_at DESC);

/* Heartbeats de workers conectados */
CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    last_heartbeat TEXT,
    last_seen_revision INTEGER
);

/* Revisión incremental del estado de jobs: se incrementa en cada cambio */
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

/* Intentos de acceso fallidos (rate limiting del login) */
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    username TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(ip, created_at);
