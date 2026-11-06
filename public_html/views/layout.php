<?php
declare(strict_types=1);

/**
 * Shell HTML común del panel: sidebar + topbar + footer.
 *
 * Variables que recibe (las pone WebController::renderLayout()):
 *   $title, $content, $active, $appName, $version, $user, $csrf, $flashes
 */

require_once CRONPANEL_ROOT . '/views/icons.php';

$active = $active ?? '';
$flashes = $flashes ?? [];
$version = $version ?? 'dev';
$user = $user ?? '';
?>
<!DOCTYPE html>
<html lang="es" data-theme="light">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title><?= e($title ?? 'Panel') ?> · <?= e($appName ?? 'Cron Scheduler') ?></title>
    <link rel="stylesheet" href="<?= e(url('/assets/css/app.css')) ?>?v=<?= e($version) ?>">
    <script>(function(){try{var t=localStorage.getItem('cw-theme');if(t==='dark'||t==='light'){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();</script>
</head>
<body>
<div class="app-shell">

    <div class="shell-overlay" data-shell-overlay></div>

    <aside class="app-sidebar" id="app-sidebar" aria-label="Navegación principal">
        <a class="sidebar-brand" href="<?= e(url('/')) ?>">
            <span class="sidebar-logo">⏱</span><span><?= e($appName ?? 'Cron Scheduler') ?></span>
        </a>
        <nav class="sidebar-nav">
            <div class="sidebar-group-label">Gestión</div>
            <a class="sidebar-link<?= $active === 'dashboard' ? ' active' : '' ?>" href="<?= e(url('/')) ?>">
                <?= icon('grid') ?>Dashboard</a>
            <a class="sidebar-link<?= $active === 'jobs' ? ' active' : '' ?>" href="<?= e(url('/jobs/new')) ?>">
                <?= icon('plus') ?>Nueva tarea</a>
            <a class="sidebar-link<?= $active === 'runs' ? ' active' : '' ?>" href="<?= e(url('/runs')) ?>">
                <?= icon('list') ?>Ejecuciones</a>
            <div class="sidebar-group-label">Sistema</div>
            <a class="sidebar-link<?= $active === 'profile' ? ' active' : '' ?>" href="<?= e(url('/perfil')) ?>">
                <?= icon('person') ?>Perfil y contraseña</a>
        </nav>
        <div class="sidebar-foot mono">v<?= e($version) ?></div>
    </aside>

    <div class="app-main">
        <header class="app-header">
            <div class="h-left">
                <button type="button" class="icon-btn shell-menu" data-shell-menu aria-label="Abrir menú">
                    <?= icon('menu', 20) ?></button>
                <h1 class="page-title"><?= e($title ?? 'Panel') ?></h1>
            </div>
            <div class="h-actions">
                <button type="button" class="icon-btn" data-theme-toggle aria-label="Cambiar tema">
                    <?= icon('moon', 20, 'icon-moon') ?><?= icon('sun', 20, 'icon-sun') ?></button>
                <div class="user-menu" data-user-menu>
                    <button type="button" class="user-btn" data-user-menu-toggle aria-expanded="false">
                        <?= icon('person') ?><span><?= e($user) ?></span>
                        <span class="user-role">admin</span><?= icon('chevron') ?></button>
                    <ul class="user-panel">
                        <li><span class="user-panel-info"><?= e($user) ?></span></li>
                        <li><a href="<?= e(url('/perfil')) ?>"><?= icon('person') ?>Perfil y contraseña</a></li>
                        <li class="sep" role="separator"></li>
                        <li><form method="post" action="<?= e(url('/logout')) ?>">
                            <input type="hidden" name="csrf" value="<?= e($csrf) ?>">
                            <button type="submit"><?= icon('logout') ?>Salir</button></form></li>
                    </ul>
                </div>
            </div>
        </header>

        <main>
            <div class="page-container">
                <?php foreach ($flashes as $flash): ?>
                    <div class="alert-<?= ($flash['type'] ?? '') === 'ok' ? 'ok' : 'err' ?>"><?= e($flash['message'] ?? '') ?></div>
                <?php endforeach; ?>
                <?= $content ?>
            </div>
        </main>

        <footer class="page-footer">
            <div class="inner">
                <span><?= e($appName ?? 'Cron Scheduler') ?> — panel de programación</span>
                <span class="mono">v<?= e($version) ?></span>
            </div>
        </footer>
    </div>
</div>

<script>
(function () {
    'use strict';
    var d = document.documentElement;
    function mode() { return d.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'; }
    var tt = document.querySelector('[data-theme-toggle]');
    if (tt) tt.addEventListener('click', function () {
        var n = mode() === 'dark' ? 'light' : 'dark';
        d.setAttribute('data-theme', n);
        try { localStorage.setItem('cw-theme', n); } catch (e) {}
    });

    var shell = document.querySelector('.app-shell');
    var mbtn = document.querySelector('[data-shell-menu]');
    var ov = document.querySelector('[data-shell-overlay]');
    if (mbtn && shell) mbtn.addEventListener('click', function () { shell.classList.toggle('drawer-open'); });
    if (ov && shell) ov.addEventListener('click', function () { shell.classList.remove('drawer-open'); });
    document.querySelectorAll('.sidebar-link').forEach(function (a) {
        a.addEventListener('click', function () { if (shell) shell.classList.remove('drawer-open'); });
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && shell) shell.classList.remove('drawer-open');
    });

    var um = document.querySelector('[data-user-menu]');
    var ub = document.querySelector('[data-user-menu-toggle]');
    if (ub && um) {
        ub.addEventListener('click', function (e) {
            e.stopPropagation();
            um.classList.toggle('open');
            ub.setAttribute('aria-expanded', um.classList.contains('open') ? 'true' : 'false');
        });
        document.addEventListener('click', function (e) { if (!um.contains(e.target)) um.classList.remove('open'); });
        document.addEventListener('keydown', function (e) { if (e.key === 'Escape') um.classList.remove('open'); });
    }

    document.querySelectorAll('form[data-confirm]').forEach(function (f) {
        f.addEventListener('submit', function (e) {
            if (!window.confirm(f.getAttribute('data-confirm'))) e.preventDefault();
        });
    });
})();
</script>
</body>
</html>
