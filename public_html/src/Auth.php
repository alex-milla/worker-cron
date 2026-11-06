<?php
declare(strict_types=1);

namespace CronPanel;

/**
 * Autenticación del panel (sesión + CSRF) y de la API (Bearer token).
 *
 * Los usuarios viven en la tabla `users` (sembrada desde config.php la
 * primera vez). La sesión guarda además el sello `password_changed_at`:
 * si cambias la contraseña, las demás sesiones dejan de valer.
 */
final class Auth
{
    private const UID_KEY = 'cronpanel_uid';
    private const USER_KEY = 'cronpanel_user';
    private const PWD_KEY = 'cronpanel_pwd';
    private const CSRF_KEY = 'cronpanel_csrf';

    private static ?UserRepository $users = null;

    private static function users(): UserRepository
    {
        return self::$users ??= new UserRepository();
    }

    /** Arranca la sesión con cookies HttpOnly + SameSite=Lax. */
    public static function startSession(): void
    {
        if (session_status() === PHP_SESSION_ACTIVE) {
            return;
        }

        $secure = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
        session_set_cookie_params([
            'lifetime' => 0,
            'path' => '/',
            'httponly' => true,
            'secure' => $secure,
            'samesite' => 'Lax',
        ]);
        session_name('cronpanel');
        session_start();
    }

    /** Token Bearer de la API del worker (config 'api_token'). */
    public static function verifyApiToken(string $headerValue): bool
    {
        global $CRONPANEL_CONFIG;

        $token = (string)($CRONPANEL_CONFIG['api_token'] ?? '');
        if ($token === '') {
            return false;
        }

        return hash_equals('Bearer ' . $token, trim($headerValue));
    }

    /** ¿Hay alguna forma de entrar? (usuario en BD o hash en config.php) */
    public static function isConfigured(): bool
    {
        global $CRONPANEL_CONFIG;

        if ((string)($CRONPANEL_CONFIG['admin_user'] ?? '') !== ''
            && (string)($CRONPANEL_CONFIG['admin_pass_hash'] ?? '') !== '') {
            return true;
        }

        try {
            return self::users()->count() > 0;
        } catch (\Throwable) {
            return false;
        }
    }

    /** Comprueba credenciales y abre la sesión. */
    public static function login(string $username, string $password): bool
    {
        if ($password === '') {
            return false;
        }

        $users = self::users();
        $users->ensureBootstrapUser();

        $user = $users->verify($username, $password);
        if ($user === null) {
            return false;
        }

        session_regenerate_id(true);
        $_SESSION[self::UID_KEY] = (int)$user['id'];
        $_SESSION[self::USER_KEY] = (string)$user['username'];
        $_SESSION[self::PWD_KEY] = (string)($user['password_changed_at'] ?? '');
        $_SESSION[self::CSRF_KEY] = bin2hex(random_bytes(16));

        return true;
    }

    public static function logout(): void
    {
        $_SESSION = [];

        if (ini_get('session.use_cookies')) {
            $params = session_get_cookie_params();
            setcookie(
                session_name(),
                '',
                time() - 42000,
                $params['path'],
                $params['domain'],
                $params['secure'],
                $params['httponly']
            );
        }

        session_destroy();
    }

    /**
     * ¿Sesión válida? Comprueba que el usuario siga existiendo y que su
     * contraseña no se haya cambiado en otro sitio (invalida la sesión).
     */
    public static function check(): bool
    {
        if (empty($_SESSION[self::UID_KEY])) {
            return false;
        }

        $user = self::users()->findById((int)$_SESSION[self::UID_KEY]);
        if ($user === null) {
            self::logout();

            return false;
        }

        $stamp = (string)($user['password_changed_at'] ?? '');
        if ($stamp !== (string)($_SESSION[self::PWD_KEY] ?? '')) {
            self::logout();

            return false;
        }

        // mantiene el nombre al día si se cambió desde otro dispositivo
        $_SESSION[self::USER_KEY] = (string)$user['username'];

        return true;
    }

    public static function id(): int
    {
        return (int)($_SESSION[self::UID_KEY] ?? 0);
    }

    public static function user(): string
    {
        return (string)($_SESSION[self::USER_KEY] ?? '');
    }

    /** Refresca el nombre en la sesión tras un cambio de usuario. */
    public static function setUsername(string $username): void
    {
        $_SESSION[self::USER_KEY] = $username;
    }

    /** Re-sella la sesión tras cambiar la contraseña (la propia sigue viva). */
    public static function refreshPasswordStamp(): void
    {
        $user = self::users()->findById(self::id());
        $_SESSION[self::PWD_KEY] = (string)($user['password_changed_at'] ?? '');
    }

    /** Corta la petición y manda al login si no hay sesión. */
    public static function requireAuth(): void
    {
        if (self::check()) {
            return;
        }
        header('Location: ' . url('/login'), true, 302);
        exit;
    }

    /** Token CSRF de la sesión (se genera la primera vez). */
    public static function csrfToken(): string
    {
        if (empty($_SESSION[self::CSRF_KEY])) {
            $_SESSION[self::CSRF_KEY] = bin2hex(random_bytes(16));
        }

        return (string)$_SESSION[self::CSRF_KEY];
    }

    public static function checkCsrf(): bool
    {
        $sent = (string)($_POST['csrf'] ?? '');

        return $sent !== '' && hash_equals(self::csrfToken(), $sent);
    }
}
