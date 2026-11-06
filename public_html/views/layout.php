<?php
declare(strict_types=1);

/** Shell HTML común del panel. TODO: parte del sistema visual de referencia (tema claro/oscuro, sidebar, toasts). */
$assetVersion = '1';
?>
<!DOCTYPE html>
<html lang="es" data-theme="light">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title><?= htmlspecialchars($title ?? 'Panel') ?> · Cron Scheduler</title>
    <link rel="stylesheet" href="/assets/css/app.css?v=<?= $assetVersion ?>">
</head>
<body>
<header><!-- TODO: barra superior con menú de usuario y toggle de tema --></header>
<main>
    <?= $content ?? '' ?>
</main>
<footer><!-- TODO: barra de versión --></footer>
</body>
</html>
