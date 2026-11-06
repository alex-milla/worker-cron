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

# 12. update() end-to-end con release simulada (sin red): zip local + mocks
import zipfile as zf2  # noqa: E402
from cronworker import updater as U  # noqa: E402
if U is None:
    from cronworker import updater as U

app2 = tmp / "app2"
app2.mkdir()
(app2 / "cronworker").mkdir()
(app2 / "cronworker" / "__init__.py").write_text("viejo\n")
(app2 / "config.yaml").write_text("worker:\n  name: PROD\n")
(app2 / "VERSION").write_text("0.1.0\n")

zip_path2 = tmp / "rel.zip"
with zf2.ZipFile(zip_path2, "w") as z:
    z.writestr("repo-sha/worker/cronworker/__init__.py", "nuevo\n")
    z.writestr("repo-sha/worker/VERSION", "0.9.9\n")

orig_get, orig_dl = updater.get_latest_release, updater.download_file
updater.get_latest_release = lambda token=None: {
    "version": "0.9.9", "zip_url": "http://local/fake.zip",
    "notes": "notas de prueba", "published_at": None, "source": "release"
}
try:
    def fake_download(url, dest, token=None, timeout=120):
        dest.write_bytes(zip_path2.read_bytes())
        return dest
    updater.download_file = fake_download
    res = updater.update(app2, token="mi-token-gh")
finally:
    updater.get_latest_release, updater.download_file = orig_get, orig_dl

assert res["updated"] is True and res["remote"] == "0.9.9", res
assert (app2 / "VERSION").read_text().strip() == "0.9.9"
assert (app2 / "cronworker" / "__init__.py").read_text() == "nuevo\n"
assert (app2 / "config.yaml").read_text() == "worker:\n  name: PROD\n"  # intacto
assert len(updater.list_backups(app2)) >= 1
print("12. update() end-to-end (release simulada): OK")

# 13. backup de una instalacion SIN manifiesto no queda vacio (1a actualizacion)
fresh = tmp / "fresh"
(fresh / "cronworker").mkdir(parents=True)
(fresh / "cronworker" / "__init__.py").write_text("v0\n")
(fresh / "VERSION").write_text("0.0.1\n")
b = updater.create_backup(fresh)
assert len([p for p in b.rglob("*") if p.is_file()]) >= 3, "backup inicial vacio"
print("13. primer backup no vacio: OK")

# 14. restore elimina los ficheros que introdujo la version posterior
src2 = tmp / "src2" / "worker"
(src2 / "cronworker").mkdir(parents=True)
(src2 / "cronworker" / "__init__.py").write_text("v1\n")
(src2 / "VERSION").write_text("1.0\n")
updater.sync_from_source(src2, fresh, "1.0")
b1 = updater.create_backup(fresh)
(src2 / "cronworker" / "nuevo.py").write_text("nuevo\n")
(src2 / "VERSION").write_text("1.1\n")
updater.sync_from_source(src2, fresh, "1.1")
assert (fresh / "cronworker" / "nuevo.py").exists()
updater.restore_backup(b1.name, fresh)
assert not (fresh / "cronworker" / "nuevo.py").exists(), "restore dejo ficheros nuevos"
print("14. restore elimina ficheros nuevos: OK")

# 15. VERSION se respalda y se restaura (ya no es "sensible")
assert (fresh / "VERSION").read_text().strip() == "1.0"
print("15. VERSION restaurada: OK")

# 16. check_writable no molesta cuando hay permisos
updater.check_writable(fresh)
print("16. check_writable con permisos: OK")

# 17. los temporales de escritura atomica nunca entran en el manifiesto
tm = tmp / "tmpscan"
tm.mkdir()
(tm / "a.py").write_text("x\n")
(tm / "a.py.tmp-upd").write_text("basura\n")
assert all(not k.endswith(".tmp-upd") for k in updater.build_manifest(tm))
print("17. .tmp-upd fuera del manifiesto: OK")

import os  # noqa: E402

if os.name == "posix" and os.geteuid() != 0:
    # 18. fichero read-only (de otro dueño) + directorio escribible: os.replace
    #     funciona igual. Es el caso real: git pull como root + servicio cronworker.
    d = tmp / "atomic"
    d.mkdir()
    target = d / "cronworker.py"
    target.write_text("viejo\n")
    os.chmod(target, 0o444)
    srcf = tmp / "nuevo.py"
    srcf.write_text("nuevo\n")
    updater._atomic_copy(srcf, target)
    assert target.read_text() == "nuevo\n"
    v = d / "VERSION"
    v.write_text("1.0\n")
    os.chmod(v, 0o444)
    updater._atomic_write(v, "2.0\n")
    assert v.read_text() == "2.0\n"
    print("18. escritura atomica sobre fichero read-only: OK")

    # 19. directorio no escribible: error claro con el comando de arreglo
    ro = tmp / "readonly"
    ro.mkdir()
    os.chmod(ro, 0o555)
    try:
        updater.check_writable(ro)
        raise AssertionError("check_writable debia fallar en un directorio read-only")
    except RuntimeError as exc:
        assert "chown -R" in str(exc), str(exc)
    finally:
        os.chmod(ro, 0o755)
    print("19. check_writable sugiere el chown: OK")

print("\nTODOS LOS TESTS DEL UPDATER OK")
