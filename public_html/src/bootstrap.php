<?php
declare(strict_types=1);

/**
 * Bootstrap del panel (hosting compartido, PHP 8.4).
 *
 * Autoload de CronPanel\ + carga de config/config.php.
 * La variable de entorno CRONPANEL_CONFIG_FILE permite usar otra config
 * (tests locales y despliegues con varias configuraciones).
 */

define('CRONPANEL_ROOT', __DIR__ . '/..');

$versionFile = CRONPANEL_ROOT . '/VERSION';
define(
    'CRONPANEL_VERSION',
    is_file($versionFile) ? trim((string)file_get_contents($versionFile)) : 'dev'
);

spl_autoload_register(function (string $class): void {
    if (str_starts_with($class, 'CronPanel\\')) {
        $rel = str_replace('\\', '/', substr($class, strlen('CronPanel\\')));
        $file = CRONPANEL_ROOT . '/src/' . $rel . '.php';
        if (is_file($file)) {
            require $file;
        }
    }
});

$cfgFile = getenv('CRONPANEL_CONFIG_FILE') ?: CRONPANEL_ROOT . '/config/config.php';
if (!is_file($cfgFile)) {
    http_response_code(500);
    exit('Falta config/config.php — copia config/config.example.php');
}
/** @var array<string,mixed> $CRONPANEL_CONFIG */
$CRONPANEL_CONFIG = require $cfgFile;

/**
 * Ruta interna con el prefijo de despliegue (config 'base_path').
 * Sirve tanto si el dominio apunta a public_html/ como a un subdirectorio.
 */
function url(string $path = '/'): string
{
    global $CRONPANEL_CONFIG;

    $base = rtrim((string)($CRONPANEL_CONFIG['base_path'] ?? ''), '/');
    if ($path === '' || $path[0] !== '/') {
        $path = '/' . $path;
    }

    return $base . $path;
}

/** Escapa texto para HTML. */
function e(?string $value): string
{
    return htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}
