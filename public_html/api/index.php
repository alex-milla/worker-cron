<?php
declare(strict_types=1);

/**
 * API REST para el worker (hosting compartido).
 * Autenticación: cabecera Authorization: Bearer <token> (config 'api_token').
 *
 * Endpoints previstos (v1) — el worker hace PULL, nunca se le empuja desde aquí:
 *   GET  /api/v1/version          → MUY BARATO: {revision} (hash de estado dejobs) para polling
 *   GET  /api/v1/jobs             → lista completa de jobs activos {revision, jobs:[...]}
 *   POST /api/v1/results          → el worker reporta el resultado de una ejecución
 *   POST /api/v1/heartbeat        → el worker avisa de que sigue vivo (barato, cada N min)
 *
 * Límite de peticiones: el worker respeta intervalo configurable + backoff exponencial.
 */

require __DIR__ . '/../src/bootstrap.php';

use CronPanel\ApiController;

$controller = new ApiController();
$controller->handle($_SERVER['REQUEST_METHOD'], $_SERVER['REQUEST_URI']);
