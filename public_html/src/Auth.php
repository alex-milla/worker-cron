<?php
declare(strict_types=1);

namespace CronPanel;

/**
 * Autenticación del panel (sesión + CSRF) y de la API (Bearer token).
 *
 * El usuario y el hash bcrypt salen de config.php (`admin_user`,
 * `admin_pass_hash`). La GUI de cambio de contraseña es una fase posterior.
 */
final class Auth
{
    private const SESSION_KEY = 'cronpanel_user';
    private const CSRF_KEY = 'cronpanel_csrf';

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

    /** ¿Está configurado el hash de la contraseña del panel? */
    public static function isConfigured(): bool
    {
        global $CRONPANEL_CONFIG;

        $hash = (string)($CRONPANEL_CONFIG['admin_pass_hash'] ?? '');
        $user = (string)($CRONPANEL_CONFIG['admin_user'] ?? '');

        return $hash !== '' && $user !== '';
    }

    /** Comprueba credenciales y abre la sesión. */
    public static function login(string $username, string $password): bool
    {
        global $CRONPANEL_CONFIG;

        if (!self::isConfigured() || $password === '') {
            return false;
        }

        $expectedUser = (string)$CRONPANEL_CONFIG['admin_user'];
        $hash = (string)$CRONPANEL_CONFIG['admin_pass_hash'];

        if (!hash_equals($expectedUser, trim($username))) {
            return false;
        }
        if (!password_verify($password, $hash)) {
            return false;
        }

        session_regenerate_id(true);
        $_SESSION[self::SESSION_KEY] = $expectedUser;
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

    public static function check(): bool
    {
        return isset($_SESSION[self::SESSION_KEY]);
    }

    public static function user(): string
    {
        return (string)($_SESSION[self::SESSION_KEY] ?? '');
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
