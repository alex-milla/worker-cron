<?php
declare(strict_types=1);

/**
 * Bootstrap del panel (hosting compartido, PHP 8.4).
 */

define('CRONPANEL_ROOT', __DIR__ . '/..');

spl_autoload_register(function (string $class): void {
    if (str_starts_with($class, 'CronPanel\\')) {
        $rel = str_replace('\\', '/', substr($class, strlen('CronPanel\\')));
        $file = CRONPANEL_ROOT . '/src/' . $rel . '.php';
        if (is_file($file)) {
            require $file;
        }
    }
});

$cfgFile = CRONPANEL_ROOT . '/config/config.php';
if (!is_file($cfgFile)) {
    http_response_code(500);
    exit('Falta config/config.php — copia config/config.example.php');
}
/** @var array<string,mixed> $CRONPANEL_CONFIG */
$CRONPANEL_CONFIG = require $cfgFile;
