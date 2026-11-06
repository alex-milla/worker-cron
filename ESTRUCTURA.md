# Estructura del repositorio

```
worker-cron/
├── README.md                     Este fichero: visión general del proyecto
├── .gitignore                    Excluye config real, datos, logs y temporales
│
├── public_html/                  Aplicación del hosting compartido (PHP 8.4)
│   │                             Panel maestro: GUI de crons + API REST para el worker
│   ├── index.php                 Front controller único (single entry point)
│   ├── .htaccess                 Bloquea acceso directo a config/, data/, src/
│   ├── config/
│   │   ├── config.example.php    Plantilla de configuración (copiar a config.php)
│   │   └── (.htaccess)           Deniega acceso web a la configuración real
│   ├── src/                      Código fuente (clases autoload)
│   │   ├── Database.php          Conexión SQLite/PDO y esquema
│   │   ├── Auth.php              Autenticación de usuarios y de API (token Bearer)
│   │   ├── JobRepository.php     CRUD de jobs de cron, versionado y diff de jobs
│   │   ├── ApiController.php     Endpoints REST: sync de jobs, resultados, heartbeat
│   │   └── WebController.php     Rutas web, sesiones, flash messages, render
│   ├── sql/
│   │   └── schema.sqlite.sql     Esquema de la base de datos (jobs, runs, users, tokens)
│   ├── views/                    Plantillas PHP del panel GUI
│   │   ├── layout.php            Shell HTML: tema, sidebar, toasts
│   │   ├── login.php, jobs.php, job_form.php, runs.php, dashboard.php
│   ├── assets/
│   │   └── css/app.css           Estilos (sistema de tokens: naranja + semánticos)
│   ├── data/                     (gitignored) BD SQLite y logs del panel
│   └── api/
│       └── index.php             Router de la API REST  /api/*
│
└── worker/                       Worker del LXC (Python 3.10+)
    ├── cronworker/               Paquete principal
    │   ├── __init__.py
    │   ├── scheduler.py          Bucle principal: sincroniza y dispara ejecuciones
    │   ├── executor.py           Ejecución de comandos con timeout y captura de salida
    │   ├── store.py              Espejo local SQLite del estado de los jobs
    │   ├── sync.py               Cliente de la API del hosting (pull/push con backoff)
    │   └── webgui.py             GUI local de monitorización (eso vendrá después)
    ├── config.example.yaml       Plantilla de configuración del worker
    ├── requirements.txt          Dependencias Python
    └── deploy/
        ├── cron-worker.service   Unidad systemd para el arranque del daemon
        └── install.sh            Instalador del worker en el LXC (Linux Debian/Ubuntu)
```

## Modelo de despliegue

- **Hosting compartido** (`public_html/`): la autoridad. Dónde se definen los crons vía GUI.
  En shared hosting no se pueden programar tareas reales: aquí solo se guardan y gestionan.
- **Worker LXC** (`worker/`): hace *pull* de los jobs contra la API del hosting en un intervalo
  configurable y de forma ligera (comparando un hash de versión); ejecuta los comandos según
  expresiones cron; reporta el resultado (éxito/fallo, salida) de vuelta a la API.

## Flujo de sincronización

1. El worker pide a la API el número de versión actual de los jobs (petición HEAD/barata).
2. Si es distinto a su versión local, descarga la lista completa de jobs activos y sus hashes.
3. Los jobs nuevos o modificados se aplican al almacenamiento local (espejo SQLite).
4. En cada ejecución el worker efectúa un push del resultado.

Las peticiones al hosting están limitadas a un intervalo entero de minutos y con backoff
exponencial en caso de error, para no sobrecargar el hosting compartido.
