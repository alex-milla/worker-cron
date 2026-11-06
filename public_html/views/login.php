<?php
declare(strict_types=1);

/**
 * Pantalla de acceso (independiente del shell).
 * Variables: $error, $username, $csrf, $configurado, $appName
 */
?>
<!DOCTYPE html>
<html lang="es" data-theme="light">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Iniciar sesión · <?= e($appName ?? 'Cron Scheduler') ?></title>
    <link rel="stylesheet" href="<?= e(url('/assets/css/app.css')) ?>?v=<?= e(defined('CRONPANEL_VERSION') ? CRONPANEL_VERSION : 'dev') ?>">
</head>
<body class="login-body">
<div class="login-col">
    <div class="login-brand">
        <div class="login-logo">⏱</div>
        <h1><?= e($appName ?? 'Cron Scheduler') ?></h1>
        <p class="sub">Panel de programación de tareas</p>
    </div>

    <?php if (empty($configurado)): ?>
        <div class="alert-err">
            Falta configurar <code>admin_pass_hash</code> en
            <code>config/config.php</code>. Genera el hash con
            <code>php -r "echo password_hash('tu-clave', PASSWORD_DEFAULT);"</code>
            y vuelve a cargar esta página.
        </div>
    <?php endif; ?>

    <form method="post" action="<?= e(url('/login')) ?>" class="login-form">
        <input type="hidden" name="csrf" value="<?= e($csrf ?? '') ?>">
        <div class="field">
            <label for="username">Usuario</label>
            <input id="username" name="username" type="text" autofocus
                   autocomplete="username" value="<?= e($username ?? '') ?>">
        </div>
        <div class="field">
            <label for="password">Contraseña</label>
            <input id="password" name="password" type="password"
                   autocomplete="current-password">
        </div>
        <?php if (!empty($error)): ?>
            <div class="alert-err"><?= e($error) ?></div>
        <?php endif; ?>
        <button type="submit" class="btn btn-block">Entrar</button>
    </form>

    <p class="hint">Acceso solo desde el panel del hosting</p>
</div>
</body>
</html>
