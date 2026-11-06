<?php
declare(strict_types=1);

/**
 * Test de humo de la capa de datos del panel (CLI, no web).
 *
 *   php tools/panel_smoke.php
 *
 * Vive FUERA de public_html a propósito: no se sube al hosting ni es
 * accesible por HTTP. No necesita config.php (usa una BD temporal).
 */

use CronPanel\Database;
use CronPanel\JobRepository;

error_reporting(E_ALL);
ini_set('display_errors', '1');

define('CRONPANEL_ROOT', dirname(__DIR__) . '/public_html');

$tmpDir = sys_get_temp_dir() . '/panel-smoke-' . bin2hex(random_bytes(4));
$CRONPANEL_CONFIG = ['db_path' => $tmpDir . '/panel.sqlite'];

// Mismo autoloader que public_html/src/bootstrap.php: así el test valida
// también que namespace y nombre de fichero se corresponden.
spl_autoload_register(static function (string $class): void {
    if (!str_starts_with($class, 'CronPanel\\')) {
        return;
    }
    $rel = str_replace('\\', '/', substr($class, strlen('CronPanel\\')));
    $file = CRONPANEL_ROOT . '/src/' . $rel . '.php';
    if (is_file($file)) {
        require $file;
    }
});

$fallos = 0;

function check(string $label, bool $ok, string $detalle = ''): void
{
    global $fallos;
    if ($ok) {
        echo "OK    {$label}\n";
        return;
    }
    $fallos++;
    echo "FALLO {$label}" . ($detalle !== '' ? " -> {$detalle}" : '') . "\n";
}

function borrarArbol(string $dir): void
{
    if (!is_dir($dir)) {
        return;
    }
    foreach (scandir($dir) ?: [] as $item) {
        if ($item === '.' || $item === '..') {
            continue;
        }
        $path = $dir . '/' . $item;
        is_dir($path) ? borrarArbol($path) : @unlink($path);
    }
    @rmdir($dir);
}

try {
    // ---------------------------------------------------------------- 1. BD --
    $pdo = Database::pdo();
    check(
        'esquema creado automáticamente',
        (bool)$pdo->query("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'")->fetchColumn()
    );
    check(
        'tablas base presentes',
        (bool)$pdo->query("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")->fetchColumn() >= 5
    );
    check(
        'journal_mode = WAL',
        strtolower((string)$pdo->query('PRAGMA journal_mode')->fetchColumn()) === 'wal'
    );
    check('singleton: pdo() estable', Database::pdo() === $pdo);

    $repo = new JobRepository($pdo);
    check('revisión inicial = 0', $repo->revision() === 0);
    check('lista inicial vacía', $repo->listJobs() === []);

    // ------------------------------------------------------------ 2. crear --
    $id = $repo->saveJob([
        'name' => 'Backup diario',
        'cron_expr' => '30 3 * * *',
        'command' => 'tar -czf /tmp/b.tgz /data',
        'timeout_sec' => 600,
        'enabled' => 1,
        'comment' => 'prueba',
    ]);
    check('saveJob inserta y devuelve id', $id === 1, "id={$id}");
    check('revisión = 1 tras insertar', $repo->revision() === 1);

    $job = $repo->getJob($id);
    check('getJob devuelve el registro', $job !== null && $job['name'] === 'Backup diario');
    check('getJob: timeout guardado', $job !== null && (int)$job['timeout_sec'] === 600);
    check('getJob: enabled = 1', $job !== null && (int)$job['enabled'] === 1);
    check('listJobs devuelve 1', count($repo->listJobs()) === 1);

    // ---------------------------------------------------------- 3. actualizar --
    $repo->saveJob([
        'id' => $id,
        'name' => 'Backup semanal',
        'cron_expr' => '0 4 * * 0',
        'command' => 'echo ok',
        'timeout_sec' => 0,
        'enabled' => 1,
        'comment' => '',
    ]);
    check('revisión = 2 tras actualizar', $repo->revision() === 2);
    check('actualización aplicada', $repo->getJob($id)['name'] === 'Backup semanal');

    // -------------------------------------------------------- 4. validación --
    $revisionAntes = $repo->revision();

    foreach ([
        'cron inválido (6 campos)' => '0 0 0 0 0 0',
        'cron inválido (minuto 60)' => '60 * * * *',
        'cron inválido (hora 24)' => '* 24 * * *',
        'cron inválido (día mes 0)' => '0 0 0 * *',
        'cron inválido (texto)' => 'abc * * * *',
        'cron inválido (step 0)' => '*/0 * * * *',
    ] as $caso => $expr) {
        $lanzado = false;
        try {
            $repo->saveJob([
                'name' => 'X', 'cron_expr' => $expr, 'command' => 'x',
                'timeout_sec' => 1, 'enabled' => 1,
            ]);
        } catch (InvalidArgumentException) {
            $lanzado = true;
        }
        check("rechaza {$caso}", $lanzado);
    }

    $lanzado = false;
    try {
        $repo->saveJob(['name' => '', 'cron_expr' => '* * * * *', 'command' => 'x']);
    } catch (InvalidArgumentException) {
        $lanzado = true;
    }
    check('rechaza nombre vacío', $lanzado);

    $lanzado = false;
    try {
        $repo->saveJob(['id' => 999, 'name' => 'Y', 'cron_expr' => '* * * * *', 'command' => 'x']);
    } catch (InvalidArgumentException) {
        $lanzado = true;
    }
    check('rechaza id inexistente', $lanzado);
    check('revisión intacta tras los rechazos', $repo->revision() === $revisionAntes);

    // --------------------------------------------------- 5. cron válidos --
    foreach ([
        '* * * * *', '*/5 * * * *', '0 3 * * 1', '0 0 1 jan *',
        '1-5/2 8-18 * * mon-fri', '0 0 * * 7',
    ] as $expr) {
        check("cron válido: {$expr}", JobRepository::isValidCron($expr));
    }

    // -------------------------------------------------------- 6. pausar --
    $repo->saveJob([
        'id' => $id, 'name' => 'Backup semanal', 'cron_expr' => '0 4 * * 0',
        'command' => 'echo ok', 'timeout_sec' => 0, 'enabled' => 0,
    ]);
    check('soloActivos filtra los pausados', $repo->listJobs(true) === []);
    check('listJobs completo sigue viéndolo', count($repo->listJobs()) === 1);
    check('revisión sube al pausar', $repo->revision() === $revisionAntes + 1);

    // ------------------------------------------------------- 7. borrar --
    $revisionAntes = $repo->revision();
    check('deleteJob borra', $repo->deleteJob($id) === true);
    check('deleteJob id inexistente = false', $repo->deleteJob(999) === false);
    check('lista vacía tras borrar', $repo->listJobs() === []);
    check('revisión sube una sola vez', $repo->revision() === $revisionAntes + 1);

    // --------------------------------------------- 8. cascada de job_runs --
    $id2 = $repo->saveJob([
        'name' => 'Con historial', 'cron_expr' => '* * * * *',
        'command' => 'echo h', 'timeout_sec' => 5, 'enabled' => 1,
    ]);
    $pdo->prepare(
        'INSERT INTO job_runs (job_id, started_at, status) VALUES (?, ?, ?)'
    )->execute([$id2, '2026-01-01T00:00:00', 'ok']);
    $repo->deleteJob($id2);
    $runs = (int)$pdo->query('SELECT COUNT(*) FROM job_runs')->fetchColumn();
    check('ON DELETE CASCADE limpia job_runs', $runs === 0, "runs={$runs}");
} catch (Throwable $e) {
    $fallos++;
    echo 'EXCEPCIÓN: ' . $e->getMessage() . ' (' . basename($e->getFile()) . ':' . $e->getLine() . ")\n";
} finally {
    borrarArbol($tmpDir);
}

echo "\n";
if ($fallos > 0) {
    echo "PANEL SMOKE: {$fallos} FALLO(S)\n";
    exit(1);
}

echo "PANEL SMOKE: TODO OK\n";
