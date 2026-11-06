<?php
declare(strict_types=1);

namespace CronPanel;

use PDO;

/**
 * Workers registrados (tabla `workers`, latidos de /api/v1/heartbeat).
 */
final class WorkerRepository
{
    /** Longitud máxima del nombre de worker que aceptamos. */
    private const MAX_NAME = 100;

    private PDO $pdo;

    public function __construct(?PDO $pdo = null)
    {
        $this->pdo = $pdo ?? Database::pdo();
    }

    /** Alta o actualización del latido de un worker. */
    public function heartbeat(string $name, ?int $revision): void
    {
        $name = trim($name);
        if ($name === '') {
            return;
        }
        if (strlen($name) > self::MAX_NAME) {
            $name = substr($name, 0, self::MAX_NAME);
        }

        $stmt = $this->pdo->prepare(
            "INSERT INTO workers (name, last_heartbeat, last_seen_revision)"
            . " VALUES (?, datetime('now'), ?)"
            . ' ON CONFLICT(name) DO UPDATE SET'
            . " last_heartbeat = datetime('now'),"
            . ' last_seen_revision = COALESCE(excluded.last_seen_revision, workers.last_seen_revision)'
        );
        $stmt->execute([$name, $revision]);
    }

    /** @return array<int, array<string, mixed>> */
    public function listAll(): array
    {
        return $this->pdo->query(
            'SELECT * FROM workers ORDER BY last_heartbeat DESC, name'
        )->fetchAll();
    }
}
