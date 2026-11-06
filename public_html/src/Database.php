<?php
declare(strict_types=1);

namespace CronPanel;

use PDO;
use RuntimeException;

/**
 * Conexión PDO a la BD del panel (SQLite en el hosting compartido).
 *
 * Crea el esquema automáticamente la primera vez que se abre la conexión
 * (`sql/schema.sqlite.sql`, idempotente) y activa WAL para que lecturas y
 * escrituras no se bloqueen entre sí.
 */
final class Database
{
    /** Conexión única del proceso. */
    private static ?PDO $pdo = null;

    public static function pdo(): PDO
    {
        if (self::$pdo instanceof PDO) {
            return self::$pdo;
        }

        global $CRONPANEL_CONFIG;

        $path = (string)($CRONPANEL_CONFIG['db_path'] ?? '');
        if ($path === '') {
            throw new RuntimeException('config.php: falta la clave db_path');
        }

        $dir = dirname($path);
        if (!is_dir($dir) && !mkdir($dir, 0775, true) && !is_dir($dir)) {
            throw new RuntimeException("No se pudo crear el directorio de datos: {$dir}");
        }

        $pdo = new PDO('sqlite:' . $path, null, null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
        $pdo->exec('PRAGMA journal_mode = WAL');
        $pdo->exec('PRAGMA busy_timeout = 10000');
        $pdo->exec('PRAGMA foreign_keys = ON');

        self::ensureSchema($pdo);
        self::migrate($pdo);

        self::$pdo = $pdo;

        return $pdo;
    }

    /**
     * Aplica el esquema si falta alguna tabla base.
     *
     * Se comprueba antes de ejecutarlo para no lanzar el DDL en cada request.
     */
    private static function ensureSchema(PDO $pdo): void
    {
        if (self::tableExists($pdo, 'jobs')
            && self::tableExists($pdo, 'meta')
            && self::tableExists($pdo, 'login_attempts')) {
            return;
        }

        $root = defined('CRONPANEL_ROOT') ? CRONPANEL_ROOT : dirname(__DIR__);
        $schemaFile = $root . '/sql/schema.sqlite.sql';
        if (!is_file($schemaFile)) {
            throw new RuntimeException("Falta el esquema: {$schemaFile}");
        }

        $sql = file_get_contents($schemaFile);
        if ($sql === false || trim($sql) === '') {
            throw new RuntimeException("No se pudo leer el esquema: {$schemaFile}");
        }

        // PDO::exec() usa sqlite3_exec(): acepta varias sentencias separadas por ';'.
        $pdo->exec($sql);
    }

    private static function tableExists(PDO $pdo, string $name): bool
    {
        $stmt = $pdo->prepare(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
        );
        $stmt->execute([$name]);

        return $stmt->fetchColumn() !== false;
    }

    /**
     * Columnas añadidas después de la primera versión del esquema.
     *
     * `CREATE TABLE IF NOT EXISTS` no añade columnas a una tabla que ya
     * existe, así que las BD creadas con v0.1.4/v0.1.5 necesitan este ALTER.
     */
    private static function migrate(PDO $pdo): void
    {
        $columns = [];
        foreach ($pdo->query('PRAGMA table_info(users)') as $row) {
            $columns[(string)$row['name']] = true;
        }

        if (!isset($columns['last_login_at'])) {
            $pdo->exec('ALTER TABLE users ADD COLUMN last_login_at TEXT');
        }
        if (!isset($columns['password_changed_at'])) {
            $pdo->exec('ALTER TABLE users ADD COLUMN password_changed_at TEXT');
        }
    }
}
