<?php
declare(strict_types=1);

/**
 * Panel Cron Scheduler — front controller (hosting compartido, PHP 8.4).
 * TODO: implementar rutas de la GUI (login, dashboard, jobs, runs) en src/WebController.php.
 */

require __DIR__ . '/src/bootstrap.php';

use CronPanel\WebController;

$controller = new WebController();
$controller->handle($_SERVER['REQUEST_METHOD'], $_SERVER['REQUEST_URI']);
