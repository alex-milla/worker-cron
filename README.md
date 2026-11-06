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
todas las pantallas). Desde la GUI se crean, editan, pausan y borran tareas
con validación de la expresión cron (cualquier cambio local queda marcado
`pending_sync` para empujarse al hosting cuando la API esté lista).

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
`sql/schema.sqlite.sql` a mano. `data/` queda protegido por el `.htaccess`
raíz (`RewriteRule ^data(/|$) - [F,L]`), además del bloqueo por extensión.

Comprobar la capa de datos sin desplegar nada:

```bash
php tools/panel_smoke.php     # 37 comprobaciones: esquema, CRUD, revisión, cron
```

Ojo: el auto-update del worker **solo sincroniza `worker/`**. Los cambios en
`public_html/` se despliegan subiendo los ficheros al hosting.
