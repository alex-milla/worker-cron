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
pantalla «Contraseña» al entrar. Desde la GUI se crean, editan, pausan y
borran tareas con validación de la expresión cron (cualquier cambio local
queda marcado `pending_sync` para empujarse al hosting cuando la API esté lista).

### Panel (hosting compartido)

Sube `public_html/`, copia `config/config.example.php` a `config/config.php`
y apunta el dominio a `public_html/`.
