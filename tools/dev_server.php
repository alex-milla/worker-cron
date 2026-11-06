<?php
declare(strict_types=1);

/**
 * Servidor de desarrollo con el mismo enrutado que el .htaccess del hosting.
 *
 *   php -S 127.0.0.1:8099 -t public_html tools/dev_server.php
 *
 * - Sirve los estáticos de public_html/.
 * - Todo lo demás pasa por index.php (equivalente al RewriteRule ^(.*)$ index.php).
 * - Replica el bloqueo de config/, data/, src/, views/ y sql/.
 *
 * Solo para desarrollo: no se sube al hosting (vive fuera de public_html).
 */

$root = dirname(__DIR__) . '/public_html';
$path = (string)(parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/');

if (preg_match('#^/(config|data|src|views|sql)(/|$)#', $path) === 1) {
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    echo '403 Forbidden';
    return true;
}

$file = $root . $path;
if ($path !== '/' && is_file($file)) {
    return false;  // el servidor embebido sirve el estático
}

// La API se sirve por api/index.php (como el RewriteRule del hosting)
if (preg_match('#^/api(/|$)#', $path) === 1) {
    require $root . '/api/index.php';
    return true;
}

require $root . '/index.php';

return true;
