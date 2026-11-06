<?php
declare(strict_types=1);

namespace CronPanel;

/**
 * Respuestas y router de la API REST para el worker.
 * TODO: GET /api/v1/version, GET /api/v1/jobs, POST /api/v1/results, POST /api/v1/heartbeat.
 * En la respuesta siempre se incluye la cabecera X-Revision.
 */
final class ApiController
{
    public function handle(string $method, string $uri): void
    {
        http_response_code(501);
        header('Content-Type: application/json');
        echo json_encode(['error' => 'API en construcción'], JSON_UNESCAPED_UNICODE);
    }
}
