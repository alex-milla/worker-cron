"""Cliente de la API del hosting compartido.

Peticiones mínimas para no saturar el hosting compartido:
    GET  /api/v1/version   → polling barato por revision
    GET  /api/v1/jobs      → solo si cambia la revision
    POST /api/v1/results   → reportar ejecución (con reintentos)
    POST /api/v1/heartbeat → aviso de vida, a un intervalo largo

TODO: backoff exponencial, timeout, reintentos encolando resultados.
"""

from __future__ import annotations
