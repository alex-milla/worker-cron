"""Race-safe bootstrap: dos workers arrancando a la vez no deben chocar."""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cronworker import store  # noqa: E402

tmp = Path(tempfile.mkdtemp()) / "race.sqlite"

c1 = store.connect(tmp)
c2 = store.connect(tmp)

# worker 2 llega primero y crea el usuario
assert store.ensure_bootstrap_user(c2) is True

# worker 1 ya habia contado 0 usuarios (antes del insert del otro):
# INSERT OR IGNORE lo trata sin explotar y NO toca la meta ya cerrada
c1.execute("SELECT COUNT(*) FROM users")  # sin commit: replica el conteo previo
assert store.ensure_bootstrap_user(c1) is False

# y si el usuario ya cambio su contrasena, el bootstrap perdedor no reactiva el aviso
store.set_meta(c2, "default_password", "0")
c2.commit()
store.ensure_bootstrap_user(c1)
row = c1.execute("SELECT value FROM meta WHERE key='default_password'").fetchone()
assert row["value"] == "0", row["value"]

# la secret de sesion: dos creators en paralelo terminan con la MISMA secret
store.set_meta(c2, "webgui_secret", "SECRETA-DEL-GANADOR")
c2.commit()
c1.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('webgui_secret', 'del-perdedor')")
c1.commit()
assert store.get_meta(c1, "webgui_secret") == "SECRETA-DEL-GANADOR"

c1.close()
c2.close()
print("RACE TESTS OK")
