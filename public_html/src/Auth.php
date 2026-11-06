<?php
declare(strict_types=1);

namespace CronPanel;

/**
 * Autenticación del panel (sesión) y de la API (Bearer token).
 * TODO: login/logout, verificación de hash, middleware requireAuth().
 */
final class Auth
{
    public static function verifyApiToken(string $headerValue): bool
    {
        global $CRONPANEL_CONFIG;
        $expected = 'Bearer ' . (string)$CRONPANEL_CONFIG['api_token'];
        return hash_equals($expected, trim($headerValue));
    }
}
