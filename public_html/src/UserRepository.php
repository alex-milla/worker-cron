<?php
declare(strict_types=1);

namespace CronPanel;

use InvalidArgumentException;
use PDO;
use PDOException;

/**
 * Usuarios del panel (tabla `users`).
 *
 * El primer arranque siembra la tabla desde `config.php` (`admin_user` +
 * `admin_pass_hash`), así las credenciales que ya había siguen valiendo.
 * A partir de ahí la BD es la fuente de verdad y la GUI puede cambiarlas.
 */
final class UserRepository
{
    private const MIN_USERNAME = 3;
    private const MAX_USERNAME = 64;
    private const MIN_PASSWORD = 8;

    private PDO $pdo;

    public function __construct(?PDO $pdo = null)
    {
        $this->pdo = $pdo ?? Database::pdo();
    }

    // ----------------------------------------------------------- bootstrap --

    /** Crea el usuario inicial desde config.php si la tabla está vacía. */
    public function ensureBootstrapUser(): ?array
    {
        if ($this->count() > 0) {
            return null;
        }

        global $CRONPANEL_CONFIG;

        $username = trim((string)($CRONPANEL_CONFIG['admin_user'] ?? ''));
        $hash = (string)($CRONPANEL_CONFIG['admin_pass_hash'] ?? '');
        if ($username === '' || $hash === '') {
            return null;
        }

        $stmt = $this->pdo->prepare(
            'INSERT OR IGNORE INTO users (username, pass_hash, is_admin) VALUES (?, ?, 1)'
        );
        $stmt->execute([$username, $hash]);

        return $stmt->rowCount() > 0 ? $this->findByUsername($username) : null;
    }

    public function count(): int
    {
        return (int)$this->pdo->query('SELECT COUNT(*) FROM users')->fetchColumn();
    }

    // -------------------------------------------------------------- lectura --

    /** @return array<string, mixed>|null */
    public function findById(int $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM users WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();

        return $row === false ? null : $row;
    }

    /** @return array<string, mixed>|null */
    public function findByUsername(string $username): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM users WHERE username = ?');
        $stmt->execute([trim($username)]);
        $row = $stmt->fetch();

        return $row === false ? null : $row;
    }

    // -------------------------------------------------------------- login --

    /**
     * Verifica credenciales y actualiza `last_login_at`.
     *
     * @return array<string, mixed>|null fila del usuario si son correctas
     */
    public function verify(string $username, string $password): ?array
    {
        $user = $this->findByUsername($username);
        if ($user === null || $password === '') {
            return null;
        }
        if (!password_verify($password, (string)$user['pass_hash'])) {
            return null;
        }

        $stmt = $this->pdo->prepare(
            "UPDATE users SET last_login_at = datetime('now') WHERE id = ?"
        );
        $stmt->execute([(int)$user['id']]);

        return $user;
    }

    public function verifyCurrentPassword(int $id, string $password): bool
    {
        $user = $this->findById($id);
        if ($user === null || $password === '') {
            return false;
        }

        return password_verify($password, (string)$user['pass_hash']);
    }

    // -------------------------------------------------------------- cambios --

    /** Cambia el nombre de usuario. Lanza excepción si no es válido u ocupado. */
    public function setUsername(int $id, string $newUsername): void
    {
        $username = trim($newUsername);
        $len = function_exists('mb_strlen') ? mb_strlen($username) : strlen($username);

        if ($len < self::MIN_USERNAME || $len > self::MAX_USERNAME) {
            throw new InvalidArgumentException(
                'El usuario debe tener entre ' . self::MIN_USERNAME . ' y '
                . self::MAX_USERNAME . ' caracteres'
            );
        }

        try {
            $stmt = $this->pdo->prepare('UPDATE users SET username = ? WHERE id = ?');
            $stmt->execute([$username, $id]);
        } catch (PDOException $e) {
            if ((string)$e->getCode() === '23000') {
                throw new InvalidArgumentException('Ese nombre de usuario ya está en uso');
            }
            throw $e;
        }
    }

    /**
     * Cambia la contraseña y sella el cambio (invalida las demás sesiones).
     * La contraseña actual la valida antes el controlador.
     */
    public function setPassword(int $id, string $newPassword): void
    {
        if (strlen($newPassword) < self::MIN_PASSWORD) {
            throw new InvalidArgumentException(
                'La nueva contraseña debe tener al menos ' . self::MIN_PASSWORD . ' caracteres'
            );
        }

        $stmt = $this->pdo->prepare(
            "UPDATE users SET pass_hash = ?,"
            . " password_changed_at = strftime('%Y-%m-%d %H:%M:%f', 'now')"
            . ' WHERE id = ?'
        );
        $stmt->execute([password_hash($newPassword, PASSWORD_DEFAULT), $id]);
    }
}
