<?php
declare(strict_types=1);

namespace CronPanel;

use PDO;

/**
 * Lectura del historial de ejecuciones (tabla job_runs).
 *
 * Las filas las escribe el worker vía POST /api/v1/results (fase 4); el panel
 * solo las muestra.
 */
final class RunRepository
{
    private PDO $pdo;

    public function __construct(?PDO $pdo = null)
    {
        $this->pdo = $pdo ?? Database::pdo();
    }

    /**
     * Últimas ejecuciones con el nombre del job.
     *
     * @return array<int, array<string, mixed>>
     */
    public function recent(int $limit = 10): array
    {
        $limit = max(1, min($limit, 500));

        $sql = 'SELECT r.*, j.name AS job_name'
            . ' FROM job_runs r'
            . ' LEFT JOIN jobs j ON j.id = r.job_id'
            . ' ORDER BY r.started_at DESC, r.id DESC'
            . ' LIMIT ' . $limit;

        return $this->pdo->query($sql)->fetchAll();
    }
}
