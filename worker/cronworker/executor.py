"""Ejecución de comandos y captura de resultados.

`shell=True` a propósito: los comandos vienen definidos como líneas de shell
(igual que un crontab) y solo los crea un usuario autenticado en el panel.
"""

from __future__ import annotations

import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# El panel trunca a 64 KiB; cortamos antes de enviar.
MAX_OUTPUT = 64 * 1024


def _now() -> str:
    """ISO-8601 en UTC, sin microsegundos (formato que acepta la API)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text

    return "[...salida truncada...]\n" + text[-MAX_OUTPUT:]


def _kill(proc: subprocess.Popen) -> None:
    """Mata el proceso **y su grupo** (el shell puede haber lanzado hijos)."""
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except OSError:
        try:
            proc.terminate()
        except OSError:
            return

    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        pass


def run_job(
    command: str,
    timeout_sec: int = 0,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> dict:
    """Ejecuta un comando y devuelve el resultado listo para `job_runs`.

    Estructura: started_at, finished_at, status (ok|failed|timeout),
    exit_code y output.
    """
    started = _now()

    if not command or not command.strip():
        return {
            "started_at": started,
            "finished_at": started,
            "status": "failed",
            "exit_code": None,
            "output": "comando vacío",
        }

    timeout = int(timeout_sec or 0)
    kwargs: dict = {
        "shell": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "errors": "replace",
        "cwd": str(cwd) if cwd is not None else None,
        "env": env,
    }
    if os.name == "posix":
        # sesión propia: al matar, se lleva por delante a los hijos
        kwargs["start_new_session"] = True

    output = ""
    code: int | None = None
    status = "failed"

    try:
        proc = subprocess.Popen(command, **kwargs)
        try:
            output, _ = proc.communicate(timeout=timeout if timeout > 0 else None)
            code = proc.returncode
            status = "ok" if code == 0 else "failed"
        except subprocess.TimeoutExpired:
            _kill(proc)
            try:
                output, _ = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                output = ""
            code = None
            status = "timeout"
    except OSError as exc:
        output = f"no se pudo ejecutar: {exc}"
        status = "failed"
        code = None

    return {
        "started_at": started,
        "finished_at": _now(),
        "status": status,
        "exit_code": code,
        "output": _truncate(output or ""),
    }
