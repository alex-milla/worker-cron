"""Cliente de la API del hosting y lógica de sincronización (pull + reporte).

El hosting es la autoridad: el worker **hace pull** de las tareas activas y
**reporta** cada ejecución. No hay push de tareas locales al panel.

Peticiones mínimas para no saturar el hosting compartido:
    GET  /api/v1/version    -> polling barato por revisión
    GET  /api/v1/jobs       -> solo si la revisión cambió
    POST /api/v1/results    -> reporte de ejecución (reintenta si falla)
    POST /api/v1/heartbeat  -> aviso de vida
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from typing import Callable

from . import store

USER_AGENT = "cronworker/1.0"

# transport(method, url, body, headers, timeout) -> (status, text)
Transport = Callable[[str, str, bytes | None, dict[str, str], int], tuple[int, str]]


class SyncError(RuntimeError):
    """No se pudo hablar con el panel (red, token, respuesta inesperada)."""


class SyncClient:
    def __init__(
        self,
        base_url: str,
        api_token: str,
        timeout: int = 30,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_token = api_token or ""
        self.timeout = int(timeout or 30)
        self._transport = transport or _urllib_transport

    # ------------------------------------------------------------ HTTP --

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        if not self.base_url:
            raise SyncError("config.yaml: falta hosting.base_url")

        url = f"{self.base_url}{path}"
        body = None
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {self.api_token}",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        status, text = self._transport(method, url, body, headers, self.timeout)

        if status == 401:
            raise SyncError("el panel rechazó el token (401): revisa hosting.api_token")
        if status == 404:
            raise SyncError(f"endpoint no encontrado: {path} (¿panel actualizado?)")
        if status >= 400:
            detalle = text[:200].strip()
            raise SyncError(f"HTTP {status} en {path}: {detalle}")

        if not text:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SyncError(f"respuesta no JSON en {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise SyncError(f"respuesta inesperada en {path}")
        return data

    # -------------------------------------------------------- endpoints --

    def version(self) -> int:
        data = self._request("GET", "/api/v1/version")
        return int(data.get("revision", 0))

    def jobs(self) -> tuple[int, list[dict]]:
        data = self._request("GET", "/api/v1/jobs")
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            raise SyncError("respuesta de /jobs sin lista de tareas")
        return int(data.get("revision", 0)), jobs

    def post_result(self, payload: dict) -> int:
        data = self._request("POST", "/api/v1/results", payload)
        return int(data.get("id", 0))

    def heartbeat(self, name: str, revision: int, pending: int = 0) -> dict:
        return self._request(
            "POST",
            "/api/v1/heartbeat",
            {"name": name, "revision": int(revision), "pending_results": int(pending)},
        )


def _urllib_transport(
    method: str,
    url: str,
    body: bytes | None,
    headers: dict[str, str],
    timeout: int,
) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        raise SyncError(f"sin conexión con el panel: {exc.reason}") from exc


# --------------------------------------------------------------- lógica --


def pull(conn: sqlite3.Connection, client: SyncClient) -> dict:
    """Sincroniza el espejo local con el panel.

    Primero pide la revisión (barato) y solo descarga las tareas si cambió.
    """
    revision = client.version()
    if revision == store.revision(conn):
        return {"changed": False, "revision": revision, "added": 0, "updated": 0, "deleted": 0}

    remote_revision, jobs = client.jobs()
    stats = store.replace_hosting_jobs(conn, jobs)
    store.set_revision(conn, remote_revision)

    return {"changed": True, "revision": remote_revision, **stats}


def push_pending(conn: sqlite3.Connection, client: SyncClient, limit: int = 50) -> dict:
    """Reporta las ejecuciones pendientes. Si falla una, se deja para el siguiente tick."""
    sent = 0
    for run in store.pending_results(conn, limit):
        payload = {
            "job_id": int(run["source_id"]),
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "status": run["status"],
            "exit_code": run["exit_code"],
            "output": run["output"] or "",
        }
        try:
            client.post_result(payload)
        except SyncError:
            break
        store.mark_reported(conn, int(run["id"]))
        sent += 1

    return {"sent": sent, "pending": store.count_pending(conn)}


def heartbeat(conn: sqlite3.Connection, client: SyncClient, name: str) -> dict:
    """Aviso de vida con la revisión local y las ejecuciones pendientes."""
    return client.heartbeat(name, store.revision(conn), store.count_pending(conn))
