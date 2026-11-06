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
cp worker/config.example.yaml worker/config.yaml
pip install -r worker/requirements.txt
python -m cronworker.scheduler
```

### Panel (hosting compartido)

Sube `public_html/`, copia `config/config.example.php` a `config/config.php`
y apunta el dominio a `public_html/`.
