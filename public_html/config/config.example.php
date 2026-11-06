<?php
/**
 * Panel Cron Scheduler — configuración de ejemplo (hosting compartido, PHP 8.4).
 * Copia este fichero a config.php y ajusta los valores.
 * config.php NUNCA se sube al repositorio.
 */

return [
    // --- Base de datos (SQLite en data/, fuera del alcance web vía .htaccess) ---
    'db_path' => __DIR__ . '/../data/panel.sqlite',

    // --- Seguridad del panel ---
    // Usuario admin inicial (se puede cambiar desde la GUI).
    'admin_user'     => 'admin',
    // Hash bcrypt de la contraseña; generarlo con: php -r "echo password_hash('CAMBIAME', PASSWORD_DEFAULT);"
    'admin_pass_hash' => '',

    // --- API del worker ---
    // Token Bearer que el worker debe enviar en la cabecera Authorization.
    'api_token' => 'CAMBIA-ESTE-TOKEN-LARGO-Y-ALEATORIO',

    // --- Sincronización ---
    // Versión de la estructura de API soportada por el hosting.
    'api_version' => 'v1',

    // --- Actualizaciones (pantalla informativa del panel) ---
    // Repositorio del que se leen las releases. Público por defecto.
    'github_repo' => 'alex-milla/worker-cron',
    // Base de la API; solo se cambia para GitHub Enterprise o pruebas.
    'github_api_base' => 'https://api.github.com',
    // Opcional: solo hace falta si el repositorio pasa a privado.
    'github_token' => '',

    // --- Aplicación ---
    // Prefijo si public_html/ no es la raíz del dominio (p. ej. '/cron').
    'base_path' => '',
    'app_name' => 'Cron Scheduler',
    'timezone' => 'Europe/Madrid',
    'debug'    => false,
];
