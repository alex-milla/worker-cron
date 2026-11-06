<?php
declare(strict_types=1);

namespace CronPanel;

/**
 * Conexión PDO a la BD del panel. TODO: inicializar esquema si no existe
 * (cargar sql/schema.sqlite.sql) y gestionar la revisión de jobs en `meta`.
 */
final class Database
{
    private static ?\PDO $pdo = null;

    public static function pdo(): \PDO
    {
        if (self::$pdo === null) {
            global $CRONPANEL_CONFIG;
            $path = (string)$CRONPANEL_CONFIG['db_path'];
            @mkdir(dirname($path), 0775, true);
            self::$pdo = new \PDO('sqlite:' . $path, null, null, [
                \PDO::ATTR_ERRMODE => \PDO::ERRMODE_EXCEPTION,
                \PDO::ATTR_DEFAULT_FETCH_MODE => \PDO::FETCH_ASSOC,
            ]);
        }
        return self::$pdo;
    }
}
