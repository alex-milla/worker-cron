<?php
declare(strict_types=1);

/**
 * Iconos SVG en línea (mismos que la GUI del worker para que se vean igual).
 * Devuelven markup de confianza: no pasar datos de usuario por aquí.
 */

if (!function_exists('icon')) {
    function icon(string $name, int $size = 18, string $class = ''): string
    {
        static $paths = [
            'menu' => '<line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/>',
            'grid' => '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
            'clock' => '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
            'list' => '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
            'plus' => '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
            'person' => '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6.5 8-6.5s8 2.5 8 6.5"/>',
            'logout' => '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
            'chevron' => '<path d="M6 9l6 6 6-6"/>',
            'sun' => '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
            'moon' => '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
            'trash' => '<path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
            'pause' => '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
            'play' => '<path d="M7 4l13 8-13 8z"/>',
            'theme' => '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
            'update' => '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
            'edit' => '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
        ];

        $body = $paths[$name] ?? '';
        $cls = $class !== '' ? ' class="' . htmlspecialchars($class, ENT_QUOTES) . '"' : '';

        return '<svg' . $cls . ' width="' . $size . '" height="' . $size . '" viewBox="0 0 24 24"'
            . ' fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"'
            . ' stroke-linejoin="round" aria-hidden="true">' . $body . '</svg>';
    }
}

if (!function_exists('status_pill')) {
    /** Píldora de estado de una ejecución (ok / timeout / fallo). */
    function status_pill(?string $status): string
    {
        if ($status === 'ok') {
            return '<span class="pill ok">ok</span>';
        }
        if ($status === 'timeout') {
            return '<span class="pill warn">timeout</span>';
        }
        if ($status === null || $status === '') {
            return '<span class="pill off">—</span>';
        }

        return '<span class="pill bad">' . htmlspecialchars($status, ENT_QUOTES) . '</span>';
    }
}
