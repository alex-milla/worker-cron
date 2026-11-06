"""Carga de configuración del worker (config.yaml).

Reads worker/config.yaml and merges with safe defaults so the app can run
even without all keys present.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "hosting": {
        "base_url": "",
        "api_token": "",
        "poll_interval_min": 1,
        "backoff_max_min": 30,
        "timeout_sec": 30,
    },
    "worker": {
        "name": "lxc-cron-worker",
        "db_path": "data/worker.sqlite",
        "log_dir": "logs",
    },
    "webgui": {
        "enabled": False,
        "listen_host": "0.0.0.0",
        "listen_port": 8080,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(config_path: str | Path | None = None) -> dict:
    """Load config.yaml (YAML) and merge over DEFAULTS.

    `config_path` defaults to `worker/config.yaml` in the project root.
    A missing file yields the defaults so the GUI can still render.
    """
    path = Path(config_path) if config_path else Path(__file__).resolve().parent.parent / "config.yaml"
    if path.is_file():
        try:
            import yaml  # type: ignore import-not-found

            with path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except Exception as exc:  # noqa: BLE001 - config is optional at this stage
            raise RuntimeError(f"No se pudo leer {path}: {exc}") from exc
        return _merge(DEFAULTS, data)
    return deepcopy(DEFAULTS)


def resolve_db_path(cfg: dict) -> Path:
    """Resolve worker.db_path to an absolute path relative to the project root."""
    raw = str(cfg.get("worker", {}).get("db_path", "data/worker.sqlite"))
    p = Path(raw)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / raw
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
