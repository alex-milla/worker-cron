<?php
declare(strict_types=1);

namespace CronPanel;

use PDO;

/**
 * Limitador de intentos de acceso (fuerza bruta).
 *
 * Dos límites para que un atacante no pueda bloquear al admin legítimo:
 *   - por (IP, usuario): `MAX_PER_USER` fallos en la ventana -> bloqueo.
 *   - por IP: `MAX_PER_IP` fallos -> bloqueo global (red de seguridad).
 *
 * Los intentos se guardan en `login_attempts` y se purgan solos.
 */
final class LoginThrottle
{
    private const MAX_PER_USER = 5;
    private const MAX_PER_IP = 20;
    private const WINDOW_SECONDS = 900;   // 15 minutos

    private PDO $pdo;

    public function __construct(?PDO $pdo = null)
    {
        $this->pdo = $pdo ?? Database::pdo();
    }

    /** IP del cliente (no se confía en X-Forwarded-For: sería falsificable). */
    public static function clientIp(): string
    {
        $ip = (string)($_SERVER['REMOTE_ADDR'] ?? '');

        return $ip !== '' ? $ip : '0.0.0.0';
    }

    /** Segundos restantes de bloqueo, o 0 si no está bloqueado. */
    public function blockedFor(string $ip, string $username): int
    {
        $this->purge();

        $since = date('Y-m-d H:i:s', time() - self::WINDOW_SECONDS);

        $porUsuario = $this->count(
            'ip = ? AND username = ? AND created_at >= ?',
            [$ip, $username, $since]
        );
        if ($porUsuario >= self::MAX_PER_USER) {
            return $this->retryAfter($ip, $username);
        }

        $porIp = $this->count('ip = ? AND created_at >= ?', [$ip, $since]);
        if ($porIp >= self::MAX_PER_IP) {
            return $this->retryAfter($ip, null);
        }

        return 0;
    }

    public function recordFailure(string $ip, string $username): void
    {
        $stmt = $this->pdo->prepare(
            "INSERT INTO login_attempts (ip, username, created_at) VALUES (?, ?, datetime('now'))"
        );
        $stmt->execute([$ip, $username]);
    }

    /** Al entrar bien se limpian los intentos de esa IP. */
    public function clear(string $ip): void
    {
        $this->pdo->prepare('DELETE FROM login_attempts WHERE ip = ?')->execute([$ip]);
    }

    /** @param list<string|int> $params */
    private function count(string $where, array $params): int
    {
        $stmt = $this->pdo->prepare("SELECT COUNT(*) FROM login_attempts WHERE {$where}");
        $stmt->execute($params);

        return (int)$stmt->fetchColumn();
    }

    /** Segundos que faltan para que caduque el intento más antiguo. */
    private function retryAfter(string $ip, ?string $username): int
    {
        $sql = 'SELECT MIN(created_at) FROM login_attempts WHERE ip = ?';
        $params = [$ip];
        if ($username !== null) {
            $sql .= ' AND username = ?';
            $params[] = $username;
        }

        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($params);
        $oldest = $stmt->fetchColumn();

        if ($oldest === false || $oldest === null) {
            return self::WINDOW_SECONDS;
        }

        $timestamp = strtotime((string)$oldest);
        if ($timestamp === false) {
            return self::WINDOW_SECONDS;
        }

        return max(1, ($timestamp + self::WINDOW_SECONDS) - time());
    }

    private function purge(): void
    {
        $this->pdo->exec(
            "DELETE FROM login_attempts WHERE created_at < datetime('now', '-1 hour')"
        );
    }
}
