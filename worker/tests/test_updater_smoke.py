"""Smoke test del updater: manifiesto, sync, backups, restore y anti zip-slip."""
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cronworker import updater  # noqa: E402

tmp = Path(tempfile.mkdtemp())

# 1. comparación de versiones
assert updater.compare_versions("0.1.0", "0.1.0") == 0
assert updater.compare_versions("0.2.0", "0.1.0") == 1
assert updater.compare_versions("0.1.0", "1.0.0") == -1
print("1. compare_versions: OK")

# 2. árbol fuente simulado (como el interior del ZIP)
src = tmp / "src" / "worker"
(src / "cronworker").mkdir(parents=True)
(src / "cronworker" / "__init__.py").write_text("__version__ = '0.1.0'\n")
(src / "cronworker" / "updater.py").write_text("# codigo\n")
(src / "tests").mkdir()
(src / "tests" / "test.txt").write_text("hola\n")

# 3. app_root destino con estado del usuario que NUNCA debe tocarse
app = tmp / "app"
(app / "data").mkdir(parents=True)
(app / "config.yaml").write_text("worker:\n  name: PRODUCCION\n")
(app / "data" / "worker.sqlite").write_bytes(b"sqlite-bytes")
(app / "data" / "backups").mkdir()

r = updater.sync_from_source(src, app, "0.1.0")
assert r["copied"] == 3 and r["errors"] == 0, r
assert (app / "cronworker" / "__init__.py").is_file()
assert (app / "config.yaml").read_text() == "worker:\n  name: PRODUCCION\n"
assert (app / "data" / "worker.sqlite").read_bytes() == b"sqlite-bytes"
print("2-3. sync inicial + sensibles intactos: OK")

# 4. re-sync sin cambios: todo skipped
r = updater.sync_from_source(src, app, "0.1.0")
assert r["copied"] == 0 and r["skipped"] == 3, r
print("4. idempotencia: OK")

# 5. cambio + fichero obsoleto: copia el cambiado y borra el gestionado que desaparece
(src / "cronworker" / "updater.py").write_text("# codigo v2\n")
(src / "tests" / "test.txt").unlink()
r = updater.sync_from_source(src, app, "0.1.1")
assert r["copied"] == 1 and r["deleted"] == 1, r
assert not (app / "tests" / "test.txt").exists()
assert "# codigo v2" in (app / "cronworker" / "updater.py").read_text()
print("5. diff por hash + stale cleanup: OK")

# 6. fichero NO gestionado jamas se borra
(app / "extensions" / "mipatch.py").parent.mkdir(exist_ok=True)
(app / "extensions" / "mipatch.py").write_text("# del usuario\n")
r = updater.sync_from_source(src, app, "0.1.2")
assert (app / "extensions" / "mipatch.py").exists()
print("6. no gestionados intactos: OK")

# 7. backup y restore
backup_path = updater.create_backup(app)
assert backup_path.is_dir()
(app / "cronworker" / "updater.py").write_text("# roto\n")
res = updater.restore_backup(backup_path.name, app)
assert "# codigo v2" in (app / "cronworker" / "updater.py").read_text()
assert (app / "config.yaml").read_text() == "worker:\n  name: PRODUCCION\n"
print("7. backup + restore: OK")

# 8. anti path-traversal en restore
for bad in ("../etc", "backup_9999", "backup_20260101_0101XX"):
    try:
        updater.restore_backup(bad, app)
        raise AssertionError(f"restore debia rechazar {bad}")
    except ValueError:
        pass
print("8. anti path-traversal: OK")

# 8b. colision de timestamps: backup + pre-backup de restore en el mismo segundo
b2 = updater.create_backup(app)
b3 = updater.create_backup(app)          # mismo segundo -> sufijo _1
assert b2 != b3
res = updater.restore_backup(b2.name, app)
assert "# codigo v2" in (app / "cronworker" / "updater.py").read_text()
print("8b. colision de timestamps en backups: OK")

# 9. extraccion de ZIP con validacion zip-slip
zip_path = tmp / "fake.zip"
with zipfile.ZipFile(zip_path, "w") as zf:
    zf.writestr("repo-sha/worker/cronworker/__init__.py", "__version__ = '0.9.9'\n")
    zf.writestr("repo-sha/worker/tests/x.txt", "hola\n")
out = tmp / "zipout"
out.mkdir()
found = updater.extract_zip(zip_path, out)
assert (found / "cronworker" / "__init__.py").read_text() == "__version__ = '0.9.9'\n"
print("9. extract + locate worker/: OK")

zip_evil = tmp / "evil.zip"
with zipfile.ZipFile(zip_evil, "w") as zf:
    zf.writestr("../evil.py", "boom\n")
try:
    updater.extract_zip(zip_evil, tmp / "evilout")
    raise AssertionError("extract_zip debia rechazar zip-slip")
except ValueError:
    print("10. anti zip-slip: OK")

# 11. VERSION instalada
(app / "VERSION").write_text("0.5.3\n")
assert updater.installed_version(app) == "0.5.3"
assert updater.installed_version(tmp / "noexiste") == "0.0.0"
print("11. VERSION: OK")

print("\nTODOS LOS TESTS DEL UPDATER OK")
