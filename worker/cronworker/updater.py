"""Sistema de actualizaciones desde GitHub (worker).

Port del patrón de md/sistema-actualizaciones-github.md a Python:

1. Consulta la última release del repo (fallback: último tag).
2. Descarga el ZIP de la release.
3. Sincroniza por manifiesto SHA-256: copia solo nuevos/cambiados y
   borra ficheros gestionados ya desaparecidos.
4. NUNCA toca estado del usuario (config.yaml, data/, logs/, venv/).
5. Backup del código antes de cada operación y restauración desde la GUI.

Funciones puras (sin Flask): tejibles desde tests y desde la GUI.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

REPO_OWNER = "alex-milla"
REPO_NAME = "worker-cron"
API_BASE = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"

# Estado del usuario: nunca se copia ni se borra en las actualizaciones
SENSITIVE_FILES = {"config.yaml"}
SENSITIVE_PREFIXES = ("data/", "logs/", "venv/", "__pycache__/")
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "data", "logs", "tools"}

MANIFEST_PATH = Path("data") / ".manifest.json"
BACKUP_PREFIX = "backup_"


# ------------------------------------------------------------------- HTTP --


def _http_get(url: str, token: str | None = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "cron-worker-updater")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_latest_release(token: str | None = None) -> dict | None:
    """Última release publicada; fallback al último tag. None si no hay nada."""
    # fallback: releases/latest -> tags (igual que el patrón PHP)
    try:
        data = json.loads(_http_get(f"{API_BASE}/releases/latest", token))
        return {
            "version": str(data["tag_name"]).lstrip("v"),
            "zip_url": data["zipball_url"],
            "notes": data.get("body") or "",
            "published_at": data.get("published_at"),
            "source": "release",
        }
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    tag = _latest_tag(token)
    if tag is None:
        return None
    return {
        "version": tag.lstrip("v"),
        "zip_url": f"{API_BASE}/zipball/{tag}",
        "notes": "",
        "published_at": None,
        "source": "tag",
    }


def _latest_tag(token: str | None) -> str | None:
    try:
        data = json.loads(_http_get(f"{API_BASE}/tags?per_page=1", token))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return data[0]["name"] if data else None


def download_file(url: str, dest: Path, token: str | None = None,
                  timeout: int = 120) -> Path:
    data = _http_get(url, token, timeout)
    if len(data) < 1024:
        raise RuntimeError("ZIP con tamaño sospechoso (< 1 KiB): descarga corrupta")
    dest.write_bytes(data)
    return dest


# -------------------------------------------------------------- manifiesto --


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


TMP_SUFFIX = ".tmp-upd"


def _atomic_write(path: Path, text: str) -> None:
    """Escribe con temporal + os.replace.

    `os.replace` es un rename(2): solo necesita permiso de escritura en el
    DIRECTORIO, no en el fichero destino. Así una actualización funciona
    aunque los ficheros instalados sean de root (p. ej. tras un `git pull`
    hecho como root) y el servicio corra como `cronworker`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + TMP_SUFFIX)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_copy(src: Path, dst: Path) -> None:
    """Igual que _atomic_write pero binario, preservando metadatos."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + TMP_SUFFIX)
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def current_user() -> str:
    """Usuario efectivo del proceso (para mensajes de error accionables)."""
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - solo es cosmético
        return "?"


def check_writable(app_root: Path) -> None:
    """Comprueba de verdad que el proceso puede escribir en el árbol.

    Un error claro ANTES de descargar evita el `EACCES` críptico a mitad de
    actualización (caso típico: `git pull` como root deja los ficheros de
    root y el servicio corre como otro usuario).
    """
    targets = [app_root]
    data = app_root / "data"
    if data.is_dir():
        targets.append(data)
    for target in targets:
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / TMP_SUFFIX
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            user = current_user()
            raise RuntimeError(
                f"No puedo escribir en {target} ({exc.strerror or exc}). "
                f"El servicio corre como '{user}' y los ficheros son de otro "
                f"usuario. Ejecuta:\n"
                f"  sudo chown -R {user}:{user} {app_root}\n"
                f"y haz los 'git pull' como '{user}' (no como root)."
            ) from exc


def is_sensitive(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    return rel in SENSITIVE_FILES or rel.startswith(SENSITIVE_PREFIXES)


def build_manifest(root: Path) -> dict[str, str]:
    """Mapa ruta relativa -> sha256, excluyendo sensibles y directorios de skip."""
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.endswith(TMP_SUFFIX):
            continue
        if rel in SENSITIVE_FILES or is_sensitive(rel):
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        manifest[rel] = sha256_file(path)
    return manifest


def load_manifest(path: Path) -> dict[str, str]:
    """Acepta wrapper {version, files: {...}} o el mapa pelado."""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("files"), dict):
        return data["files"]
    return data


def save_manifest(path: Path, version: str, files: dict[str, str]) -> None:
    payload = {
        "version": version,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "files": files,
    }
    _atomic_write(path, json.dumps(payload, indent=2, ensure_ascii=False))


# ------------------------------------------------------------------- sync --


def sync_from_source(src: Path, app_root: Path, version: str) -> dict:
    """Núcleo: sincroniza src (copia del ZIP) sobre app_root.

    - copia nuevos/cambiados (por sha256)
    - borra los gestionados que ya no existen en la source
    - NUNCA toca ficheros/directorios sensibles ni no gestionados
    """
    new_manifest = build_manifest(src)
    old_manifest = load_manifest(app_root / MANIFEST_PATH)

    copied = skipped = deleted = errors = 0
    errors_detail: list[str] = []

    for rel, sha in sorted(new_manifest.items()):
        dst = app_root / rel
        try:
            if dst.is_file() and sha256_file(dst) == sha:
                skipped += 1
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            # escritura atómica: nunca se deja un .py a medio escribir si el
            # proceso muere a mitad (p. ej. timeout de gunicorn).
            _atomic_copy(src / rel, dst)
            copied += 1
        except OSError as exc:
            errors += 1
            errors_detail.append(f"{rel}: {exc}")

    for rel in sorted(old_manifest):
        if rel in new_manifest or is_sensitive(rel):
            continue
        stale = app_root / rel
        try:
            if stale.is_file():
                stale.unlink()
                deleted += 1
        except OSError as exc:
            errors += 1
            errors_detail.append(f"{rel}: {exc}")

    save_manifest(app_root / MANIFEST_PATH, version, new_manifest)
    return {
        "copied": copied, "skipped": skipped, "deleted": deleted,
        "errors": errors, "error_detail": errors_detail,
    }


# ---------------------------------------------------------------- backups --


def backups_dir(app_root: Path) -> Path:
    return app_root / "data" / "backups"


def list_backups(app_root: Path) -> list[Path]:
    base = backups_dir(app_root)
    if not base.is_dir():
        return []
    return sorted(
        (p for p in base.iterdir() if p.is_dir() and p.name.startswith(BACKUP_PREFIX)),
        reverse=True,
    )


def create_backup(app_root: Path) -> Path:
    """Copia los ficheros gestionados a data/backups/backup_YYYYMMDD_HHMMSS.

    Si dos backups caen en el mismo segundo, se sufija con _1, _2, ...
    (p. ej. el 'pre-backup' de una restauración inmediata tras otro backup).
    """
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backups_dir(app_root) / f"{BACKUP_PREFIX}{base}"
    suffix = 0
    while dest.exists():
        suffix += 1
        dest = backups_dir(app_root) / f"{BACKUP_PREFIX}{base}_{suffix}"
    dest.mkdir(parents=True, exist_ok=False)

    manifest = load_manifest(app_root / MANIFEST_PATH)
    if not manifest:
        # Instalación sin manifiesto todavía (primera actualización tras un
        # git clone): sin esto el "backup previo" quedaría vacío e inservible.
        manifest = build_manifest(app_root)
    for rel in manifest:
        src = app_root / rel
        if not src.is_file():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_copy(src, target)
    # el backup lleva SIEMPRE su manifiesto (aunque el original no existiera),
    # para que restore_backup sepa exactamente qué ficheros gestionaba.
    save_manifest(dest / MANIFEST_PATH, installed_version(app_root), manifest)
    return dest


def restore_backup(backup_name: str, app_root: Path) -> dict:
    """Restaura un backup (haciendo antes backup del estado actual).

    Anti path-traversal: el nombre debe seguir el patrón y resolved debe
    estar dentro de data/backups.
    """
    import re

    if not re.fullmatch(rf"{BACKUP_PREFIX}\d{{8}}_\d{{6}}(_\d+)?", backup_name):
        raise ValueError("Nombre de backup no válido")
    backup_dir = (backups_dir(app_root) / backup_name).resolve()
    if not str(backup_dir).startswith(str(backups_dir(app_root).resolve())):
        raise ValueError("Ruta de backup fuera de data/backups")
    if not backup_dir.is_dir():
        raise ValueError("Backup no encontrado")

    check_writable(app_root)
    backup_files = load_manifest(backup_dir / MANIFEST_PATH)
    if not backup_files:
        raise ValueError("El backup no contiene manifiesto: no se puede restaurar")

    pre = create_backup(app_root)
    copied = removed = 0
    for rel in backup_files:
        src = backup_dir / rel
        if not src.is_file():
            continue
        dst = app_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        _atomic_copy(src, dst)
        copied += 1
    # rollback completo: los ficheros gestionados que introdujo la versión
    # posterior y que no existen en el backup también se eliminan.
    current_files = load_manifest(app_root / MANIFEST_PATH)
    for rel in current_files:
        if rel in backup_files or is_sensitive(rel):
            continue
        stale = app_root / rel
        try:
            if stale.is_file():
                stale.unlink()
                removed += 1
        except OSError:
            pass
    save_manifest(app_root / MANIFEST_PATH, installed_version(app_root), backup_files)
    return {"restored": copied, "removed": removed, "pre_backup": pre.name}


# ------------------------------------------------------------------- ZIP --


def extract_zip(zip_path: Path, dest: Path) -> Path:
    """Extrae validando nombres (anti zip-slip). Devuelve la raíz del worker."""
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            parts = Path(name).parts
            if name.startswith(("/", "\\")) or ".." in parts:
                raise ValueError(f"Entrada peligrosa en el ZIP: {name}")
        zf.extractall(dest)

    # localizar .../worker que contenga cronworker/ (zipball: repo-sha/worker)
    for candidate in [dest / "worker", *dest.glob("*/worker"), *dest.rglob("worker")]:
        if (candidate / "cronworker" / "__init__.py").is_file():
            return candidate
    raise RuntimeError("No se encontró la carpeta worker/ con cronworker/ en el ZIP")


# --------------------------------------------------------------- versiones --


def compare_versions(a: str, b: str) -> int:
    """-1 si a<b, 0 si iguales, 1 si a>b (comparación numérica por segmentos)."""
    def parts(v: str) -> list[int]:
        return [int(p) for p in re.sub(r"[^0-9.]", "", v).split(".") if p] or [0]

    pa, pb = parts(a), parts(b)
    length = max(len(pa), len(pb))
    pa += [0] * (length - len(pa))
    pb += [0] * (length - len(pb))
    return (pa > pb) - (pa < pb)


def installed_version(app_root: Path) -> str:
    vf = app_root / "VERSION"
    return vf.read_text(encoding="utf-8").strip() if vf.is_file() else "0.0.0"


# --------------------------------------------------------------- orquesta --


def update(app_root: Path, token: str | None = None, force: bool = False) -> dict:
    """Descarga la última release, hace backup y sincroniza."""
    release = get_latest_release(token)
    if release is None:
        raise RuntimeError("No hay releases ni tags publicados en el repositorio")

    current = installed_version(app_root)
    remote = release["version"]
    if not force and compare_versions(current, remote) >= 0:
        return {"updated": False, "current": current, "remote": remote,
                "message": "Ya estás en la última versión"}

    check_writable(app_root)
    backup = create_backup(app_root)
    tmp = Path(tempfile.mkdtemp(prefix="cron-upd-"))
    try:
        zip_path = tmp / "release.zip"
        download_file(release["zip_url"], zip_path, token)
        extract_dir = tmp / "extracted"
        extract_dir.mkdir()
        src_worker = extract_zip(zip_path, extract_dir)
        result = sync_from_source(src_worker, app_root, remote)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not result["errors"]:
        _atomic_write(app_root / "VERSION", remote + "\n")
    return {
        "updated": True, "current": current, "remote": remote,
        "backup": backup.name, **result,
    }
