"""Tests del ejecutor: estados, timeout, corte de salida y errores."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cronworker import executor  # noqa: E402

PY = sys.executable


def cmd(code: str) -> str:
    return f'"{PY}" -c "{code}"'


# 1. éxito
r = executor.run_job(cmd("print('hola')"))
assert r["status"] == "ok", r
assert r["exit_code"] == 0
assert "hola" in r["output"]
assert r["started_at"] <= r["finished_at"]
assert "T" in r["started_at"]
print("1. comando ok: OK")

# 2. fallo con código de salida
r = executor.run_job(cmd("import sys; sys.exit(3)"))
assert r["status"] == "failed", r
assert r["exit_code"] == 3
print("2. exit code != 0 -> failed: OK")

# 3. timeout (mata el proceso)
t0 = time.monotonic()
r = executor.run_job(cmd("import time; time.sleep(20)"), timeout_sec=1)
transcurrido = time.monotonic() - t0
assert r["status"] == "timeout", r
assert r["exit_code"] is None
assert transcurrido < 15, transcurrido
print(f"3. timeout en {transcurrido:.1f}s: OK")

# 4. salida grande -> truncada
r = executor.run_job(cmd("print('x' * 200000)"))
assert r["status"] == "ok"
assert len(r["output"]) <= executor.MAX_OUTPUT + 80, len(r["output"])
assert "truncada" in r["output"]
print("4. salida truncada a 64 KiB: OK")

# 5. comando vacío
r = executor.run_job("   ")
assert r["status"] == "failed"
assert "vacío" in r["output"]
print("5. comando vacío: OK")

# 6. comando inexistente -> failed, no excepción
r = executor.run_job("comando_que_no_existe_xyz_123")
assert r["status"] == "failed"
assert r["exit_code"] != 0
print("6. comando inexistente: OK")

# 7. stderr también se captura
r = executor.run_job(cmd("import sys; print('mal', file=sys.stderr); sys.exit(1)"))
assert r["status"] == "failed"
assert "mal" in r["output"]
print("7. stderr capturado: OK")

print("\nTODOS LOS TESTS DEL EXECUTOR OK")
