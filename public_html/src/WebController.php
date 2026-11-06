<?php
declare(strict_types=1);

namespace CronPanel;

/**
 * Rutas de la GUI del panel: login, dashboard (estado del worker), jobs y runs.
 */
final class WebController
{
    public function handle(string $method, string $uri): void
    {
        http_response_code(501);
        echo 'Panel en construcción';
    }
}
