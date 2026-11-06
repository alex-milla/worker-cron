# Proyecto Cron Scheduler

Programador de tareas (crons) distribuido entre un panel web (hosting compartido, PHP 8.4)
y un worker (LXC, Python 3) que ejecuta los comandos y reporta los resultados.

## Componentes

| Carpeta        | Stack              | Rol                                             |
|----------------|--------------------|-------------------------------------------------|
| `public_html/` | PHP 8.4 + SQLite   | Panel GUI donde se definen y gestionan los crons |
| `worker/`      | Python 3.10+       | Daemon que consulta, ejecuta y reporta           |

## Modelo de sincronización

- El hosting es la **autoridad**: allí se definen los jobs.
- El worker hace **pull** de los jobs (petición ligera de versión) y **reporta** cada ejecución.
- Las peticiones hacia el hosting se limitan al mínimo (intervalo configurable + backoff).

## Instalación rápida

### Worker (LXC)

```bash
git clone https://github.com/alex-milla/worker-cron.git /opt/worker-cron
bash /opt/worker-cron/worker/deploy/install.sh
nano /opt/worker-cron/worker/config.yaml   # base_url y api_token del panel
systemctl enable --now cron-gui cron-worker
```

La GUI del worker (Apache :80 → gunicorn → Flask) pide sesión en `/login`.
La primera vez se crea el usuario **admin / admin**; cámbiala en la
pantalla «Contraseña» al entrar (mientras no la cambies verás un aviso en
todas las pantallas).

**El worker sincroniza, ejecuta y reporta** (desde v0.1.9):

```
cada minuto:  GET /api/v1/version   (barato) ─┐
              si cambió: GET /api/v1/jobs      │ pull
              POST /api/v1/results (pendientes)│
              POST /api/v1/heartbeat           ┘
cada 5 s:     ejecutar las tareas cuya hora cron ha llegado
```

- Las tareas del **panel** son la autoridad: se replican en el espejo local
  (`source='hosting'`) y las que se borran o pausan allí desaparecen aquí.
- Las tareas creadas en la **GUI del worker** son **locales**: solo existen en
  el LXC, se ejecutan igual y **no se envían** al panel.
- Las ejecuciones se guardan primero en local y se reportan después. Si el
  panel no responde, quedan pendientes y se reintentan con backoff exponencial
  (hasta `hosting.backoff_max_min`).
- Cron clásico: lo que se pierde con el worker apagado **no se recupera**, y
  las tareas se ejecutan **de una en una** (sin solaparse).

### Actualizar el worker

Dos vías, ambas con backup previo automático:

1. **Desde la GUI**: *Actualizaciones → Instalar última versión*. Descarga la
   release de GitHub, respalda el código en `worker/data/backups/` y sincroniza
   por manifiesto SHA-256. Después: `systemctl restart cron-gui cron-worker`.
2. **Desde el repo**:
   ```bash
   sudo -u cronworker git -C /opt/worker-cron pull
   sudo systemctl restart cron-gui cron-worker
   ```

> **Importante:** haz siempre `git pull` **como `cronworker`** (o ejecuta
> `sudo chown -R cronworker:cronworker /opt/worker-cron` después). Si el pull
> se hace como root, los ficheros cambian de dueño y la actualización desde la
> GUI falla con `[Errno 13] Permission denied: .../worker/VERSION`, porque el
> servicio corre como `cronworker`. Desde v0.1.3 el updater escribe con
> `os.replace` (solo necesita permiso sobre el directorio) y, si aun así no
> puede escribir, muestra el comando exacto para arreglarlo.

### Panel (hosting compartido)

Sube `public_html/`, copia `config/config.example.php` a `config/config.php`
y apunta el dominio a `public_html/`.

Requisitos: **PHP 8.0+ con `pdo_sqlite`**. El esquema de la BD
(`data/panel.sqlite`) se crea **automáticamente** la primera vez que la app
abre la conexión (`src/Database.php`), así que ya no hay que cargar
`sql/schema.sqlite.sql` a mano. `data/`, `src/`, `views/` y `sql/` están
bloqueados desde el `.htaccess` raíz.

El panel ya es funcional: **login con sesión + CSRF**, dashboard, alta/edición
de tareas, activar/pausar/borrar y **«Perfil y contraseña»** (cambiar usuario y
contraseña sin tocar ficheros). La API del worker (`/api/v1/*`) sigue en 501
hasta la fase 4, así que **el worker todavía no sincroniza nada**.

> La contraseña se **siembra desde `config.php`** la primera vez (tabla
> `users`) y a partir de ahí se cambia desde «Perfil y contraseña». Al
> cambiarla se cierran las demás sesiones abiertas.

Comprobar el panel sin desplegar nada (PHP en el PATH):

```bash
php tools/panel_smoke.php              # 37 comprobaciones de la capa de datos
pwsh -File tools/panel_e2e.ps1         # 31 comprobaciones HTTP (login, CSRF, CRUD)
```

Para probarlo en local con el mismo enrutado que el hosting:

```bash
php -S 127.0.0.1:8099 -t public_html tools/dev_server.php
```
(`tools/` vive fuera de `public_html`, no se sube al hosting.)

### API para el worker

Autenticación: `Authorization: Bearer <api_token>` (el de `config.php`).
Todas las respuestas llevan `X-Revision`, y el worker hace **pull** (nunca se
le empuja nada).

| Método | Ruta | Devuelve |
|---|---|---|
| GET | `/api/v1/version` | `{revision}` — polling barato |
| GET | `/api/v1/jobs` | `{revision, count, jobs:[…]}` — solo tareas activas |
| POST | `/api/v1/results` | registra una ejecución → `201 {id}` |
| POST | `/api/v1/heartbeat` | aviso de vida → `200 {ok}` |

```bash
curl -H "Authorization: Bearer $TOKEN" https://panel.example.com/api/v1/version
curl -H "Authorization: Bearer $TOKEN" https://panel.example.com/api/v1/jobs

curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"job_id":1,"started_at":"2026-11-06T23:00:00","finished_at":"2026-11-06T23:00:05","status":"ok","exit_code":0,"output":"ok"}' \
  https://panel.example.com/api/v1/results

curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"lxc-cron-worker","revision":7}' \
  https://panel.example.com/api/v1/heartbeat
```

Estados válidos en `results`: `ok`, `failed`, `timeout`. El `output` se trunca
a 64 KiB y el cuerpo máximo es 1 MiB. Si Apache no pasa la cabecera
`Authorization`, el `.htaccess` ya la reexpone vía entorno.

### Actualizaciones

El panel **se actualiza solo desde GitHub**, igual que el worker: la única
diferencia es el destino (el worker sincroniza `worker/`, el panel
`public_html/`).

- **Instalar última versión** / **Reinstalar (forzar)**: descarga el zipball de
  la release, hace **backup previo** en `data/backups/` y sincroniza por
  manifiesto SHA-256 (solo copia lo cambiado y borra los ficheros gestionados
  que hayan desaparecido).
- **Nunca toca** `config/config.php` ni `data/` (BD, backups y temporal).
- **Backups** con restauración desde la misma pantalla (con pre-backup del
  estado actual).
- **Token de GitHub** opcional, guardado en la BD y enmascarado en el
  formulario (solo hace falta si el repo pasa a privado).
- Tras instalar, **recarga la página** para cargar el código nuevo.

> Requiere permiso de escritura en `public_html/` (normal en hosting
> compartido) y, para extraer el ZIP, `ext-zip` **o** `PharData` (la extensión
> `phar`, casi siempre activa). Si no hay ninguna de las dos, la pantalla lo
> dice.

Ajustes opcionales en `config.php`:

| Clave | Por defecto | Para qué |
|---|---|---|
| `github_repo` | `alex-milla/worker-cron` | repositorio del que se leen las releases |
| `github_api_base` | `https://api.github.com` | GitHub Enterprise o pruebas |
| `github_token` | vacío | semilla; el token real se guarda en la BD |

Ojo: el auto-update del worker **solo sincroniza `worker/`**. Los cambios en
`public_html/` se despliegan subiendo los ficheros al hosting.
