<?php
declare(strict_types=1);

namespace CronPanel;

use InvalidArgumentException;
use PDO;
use Throwable;

/**
 * CRUD de jobs y cálculo de la revisión para la sincronización con el worker.
 *
 * `meta.revision` es un contador monótono que se incrementa en cada cambio.
 * El worker consulta GET /api/v1/version (barato) y solo descarga la lista
 * completa de jobs cuando la revisión cambia.
 */
final class JobRepository
{
    private const CRON_FIELDS = 5;

    /** Rango [min, max] por campo: minuto, hora, día del mes, mes, día semana. */
    private const RANGES = [
        [0, 59],
        [0, 23],
        [1, 31],
        [1, 12],
        [0, 7],   // 0 y 7 son domingo
    ];

    private const MONTHS = [
        'jan' => 1, 'feb' => 2, 'mar' => 3, 'apr' => 4, 'may' => 5, 'jun' => 6,
        'jul' => 7, 'aug' => 8, 'sep' => 9, 'oct' => 10, 'nov' => 11, 'dec' => 12,
    ];

    private const DAYS = [
        'sun' => 0, 'mon' => 1, 'tue' => 2, 'wed' => 3,
        'thu' => 4, 'fri' => 5, 'sat' => 6,
    ];

    private PDO $pdo;

    public function __construct(?PDO $pdo = null)
    {
        $this->pdo = $pdo ?? Database::pdo();
    }

    // ------------------------------------------------------------- lectura --

    /** @return array<int, array<string, mixed>> */
    public function listJobs(bool $soloActivos = false): array
    {
        $sql = 'SELECT * FROM jobs';
        if ($soloActivos) {
            $sql .= ' WHERE enabled = 1';
        }
        $sql .= ' ORDER BY enabled DESC, name COLLATE NOCASE, id ASC';

        return $this->pdo->query($sql)->fetchAll();
    }

    /** @return array<string, mixed>|null */
    public function getJob(int $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM jobs WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();

        return $row === false ? null : $row;
    }

    // ------------------------------------------------------------ escritura --

    /**
     * Crea o actualiza un job y devuelve su id.
     *
     * @param array<string, mixed> $data
     * @throws InvalidArgumentException si los datos no son válidos
     */
    public function saveJob(array $data): int
    {
        $name = trim((string)($data['name'] ?? ''));
        $cron = trim((string)($data['cron_expr'] ?? ''));
        $command = trim((string)($data['command'] ?? ''));
        $comment = trim((string)($data['comment'] ?? ''));
        $timeout = (int)($data['timeout_sec'] ?? 0);
        $enabled = empty($data['enabled']) ? 0 : 1;

        $rawId = $data['id'] ?? null;
        $id = ($rawId !== null && (int)$rawId > 0) ? (int)$rawId : null;

        if ($name === '') {
            throw new InvalidArgumentException('El nombre es obligatorio');
        }
        if ($command === '') {
            throw new InvalidArgumentException('El comando es obligatorio');
        }
        if (!self::isValidCron($cron)) {
            throw new InvalidArgumentException("Expresión cron inválida: {$cron}");
        }
        if ($timeout < 0) {
            throw new InvalidArgumentException('El timeout no puede ser negativo');
        }

        $this->pdo->beginTransaction();
        try {
            if ($id !== null) {
                $stmt = $this->pdo->prepare(
                    'UPDATE jobs SET name = ?, cron_expr = ?, command = ?,'
                    . ' timeout_sec = ?, enabled = ?, comment = ?,'
                    . " updated_at = datetime('now') WHERE id = ?"
                );
                $stmt->execute([
                    $name, $cron, $command, $timeout, $enabled,
                    $comment === '' ? null : $comment, $id,
                ]);
                if ($stmt->rowCount() === 0) {
                    throw new InvalidArgumentException("No existe el job #{$id}");
                }
                $savedId = $id;
            } else {
                $stmt = $this->pdo->prepare(
                    'INSERT INTO jobs (name, cron_expr, command, timeout_sec, enabled, comment)'
                    . ' VALUES (?, ?, ?, ?, ?, ?)'
                );
                $stmt->execute([
                    $name, $cron, $command, $timeout, $enabled,
                    $comment === '' ? null : $comment,
                ]);
                $savedId = (int)$this->pdo->lastInsertId();
            }

            $this->bumpRevision();
            $this->pdo->commit();
        } catch (Throwable $e) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            throw $e;
        }

        return $savedId;
    }

    /** Borra un job (y sus ejecuciones por ON DELETE CASCADE). */
    public function deleteJob(int $id): bool
    {
        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare('DELETE FROM jobs WHERE id = ?');
            $stmt->execute([$id]);
            $deleted = $stmt->rowCount() > 0;
            if ($deleted) {
                $this->bumpRevision();
            }
            $this->pdo->commit();
        } catch (Throwable $e) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            throw $e;
        }

        return $deleted;
    }

    // ------------------------------------------------------------ revisión --

    /** Revisión actual (0 si aún no hubo cambios). */
    public function revision(): int
    {
        $stmt = $this->pdo->query("SELECT value FROM meta WHERE key = 'revision'");
        $value = $stmt->fetchColumn();

        return $value === false ? 0 : (int)$value;
    }

    /**
     * Incrementa la revisión. Debe llamarse dentro de la transacción del
     * cambio para que ambos sean atómicos.
     */
    public function bumpRevision(): int
    {
        $this->pdo->exec(
            "INSERT INTO meta (key, value) VALUES ('revision', '1')"
            . ' ON CONFLICT(key) DO UPDATE SET'
            . ' value = CAST(COALESCE(CAST(value AS INTEGER), 0) + 1 AS TEXT)'
        );

        return $this->revision();
    }

    // -------------------------------------------------------- validación --

    /** Expresión cron estándar de 5 campos (admite * , - / y nombres). */
    public static function isValidCron(string $expr): bool
    {
        $parts = preg_split('/\s+/', trim($expr));
        if (!is_array($parts) || count($parts) !== self::CRON_FIELDS) {
            return false;
        }

        foreach ($parts as $field => $part) {
            if (!self::isValidField($part, $field)) {
                return false;
            }
        }

        return true;
    }

    private static function isValidField(string $part, int $field): bool
    {
        if ($part === '') {
            return false;
        }
        foreach (explode(',', $part) as $item) {
            if (!self::isValidItem($item, $field)) {
                return false;
            }
        }

        return true;
    }

    /** Item: asterisco, asterisco/paso, valor, rango, valor/paso o rango/paso. */
    private static function isValidItem(string $item, int $field): bool
    {
        if ($item === '*') {
            return true;
        }

        if (str_contains($item, '/')) {
            [$item, $step] = explode('/', $item, 2);
            if (!ctype_digit($step) || (int)$step < 1) {
                return false;
            }
            if ($item === '*') {
                return true;
            }
        }

        if (str_contains($item, '-')) {
            $bounds = explode('-', $item, 2);
            if (count($bounds) !== 2) {
                return false;
            }
            $min = self::fieldValue($bounds[0], $field);
            $max = self::fieldValue($bounds[1], $field);

            return $min !== null && $max !== null && $min <= $max;
        }

        return self::fieldValue($item, $field) !== null;
    }

    private static function fieldValue(string $token, int $field): ?int
    {
        [$min, $max] = self::RANGES[$field];

        if (ctype_digit($token)) {
            $value = (int)$token;

            return ($value >= $min && $value <= $max) ? $value : null;
        }

        $lower = strtolower($token);
        if ($field === 3 && isset(self::MONTHS[$lower])) {
            return self::MONTHS[$lower];
        }
        if ($field === 4 && isset(self::DAYS[$lower])) {
            return self::DAYS[$lower];
        }

        return null;
    }
}
