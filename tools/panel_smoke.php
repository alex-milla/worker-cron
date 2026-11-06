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
$CRONPANEL_CONFIG = [
    'db_path' => $tmpDir . '/panel.sqlite',
    'admin_user' => 'admin',
    'admin_pass_hash' => password_hash('test1234', PASSWORD_DEFAULT),
];

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

    // ------------------------------------------------------- 9. usuarios --
    $users = new \CronPanel\UserRepository($pdo);
    check('tabla users vacía al empezar', $users->count() === 0);

    $creado = $users->ensureBootstrapUser();
    check('bootstrap crea el usuario de config.php', $creado !== null && $creado['username'] === 'admin');
    check('bootstrap es idempotente', $users->ensureBootstrapUser() === null && $users->count() === 1);

    check('verify con la contraseña buena', $users->verify('admin', 'test1234') !== null);
    check('verify rechaza contraseña mala', $users->verify('admin', 'mala') === null);
    check('verify rechaza usuario inexistente', $users->verify('nadie', 'test1234') === null);

    $uid = (int)$users->findByUsername('admin')['id'];
    check('verifyCurrentPassword correcta', $users->verifyCurrentPassword($uid, 'test1234'));
    check('verifyCurrentPassword incorrecta', !$users->verifyCurrentPassword($uid, 'mala'));

    $lanzado = false;
    try {
        $users->setUsername($uid, 'x');
    } catch (InvalidArgumentException) {
        $lanzado = true;
    }
    check('rechaza usuario demasiado corto', $lanzado);

    $users->setUsername($uid, 'gestor');
    check('cambio de usuario aplicado', $users->findById($uid)['username'] === 'gestor');
    check('login con el usuario nuevo', $users->verify('gestor', 'test1234') !== null);
    check('login con el usuario viejo falla', $users->verify('admin', 'test1234') === null);

    $lanzado = false;
    try {
        $users->setPassword($uid, 'corta');
    } catch (InvalidArgumentException) {
        $lanzado = true;
    }
    check('rechaza contraseña demasiado corta', $lanzado);

    $users->setPassword($uid, 'nueva-clave-9');
    $fila = $users->findById($uid);
    check('contraseña nueva funciona', $users->verify('gestor', 'nueva-clave-9') !== null);
    check('contraseña vieja ya no', $users->verify('gestor', 'test1234') === null);
    check('password_changed_at queda sellado', !empty($fila['password_changed_at']));
    check('last_login_at se actualiza', !empty($fila['last_login_at']));

    // ------------------------------------------------ 10. actualizaciones --
    $llamadas = 0;
    $fake = function (string $url, array $headers) use (&$llamadas): string {
        $llamadas++;
        return json_encode([
            'tag_name' => 'v9.9.9',
            'body' => 'notas de prueba',
            'zipball_url' => 'https://example.com/z.zip',
            'html_url' => 'https://example.com/r',
            'published_at' => '2026-11-06T00:00:00Z',
        ], JSON_THROW_ON_ERROR);
    };

    $up = new \CronPanel\Updater($fake, $pdo);
    $r1 = $up->check();
    check('updater parsea la version', ($r1['release']['version'] ?? null) === '9.9.9');
    check('updater no viene de cache', $r1['cached'] === false);
    check('updater llamó una vez', $llamadas === 1);
    check('updater lee la version instalada', $up->installedVersion() !== '');

    $r2 = $up->check();
    check('segunda consulta usa cache', $r2['cached'] === true && $llamadas === 1);

    $r3 = $up->check(true);
    check('forzar ignora la cache', $r3['cached'] === false && $llamadas === 2);

    $viejo = json_encode([
        'checkedAt' => time() - 1900,
        'release' => ['version' => '1.0.0'],
        'error' => null,
    ]);
    $pdo->prepare(
        "INSERT INTO meta (key, value) VALUES ('github_release', ?)"
        . ' ON CONFLICT(key) DO UPDATE SET value = excluded.value'
    )->execute([$viejo]);
    $r4 = $up->check();
    check('cache caducada se ignora', $r4['cached'] === false && $llamadas === 3);

    $fallo = function (): string {
        throw new \RuntimeException('sin conexión');
    };
    $upFallo = new \CronPanel\Updater($fallo, $pdo);
    $r5 = $upFallo->check(true);
    check('un error de red no rompe', $r5['release'] === null && $r5['error'] === 'sin conexión');
    check('el error tambien se cachea', $upFallo->check()['cached'] === true);

    // ------------------------------------------------ 11. instalador (panel) --
    $app = $tmpDir . '/app';
    @mkdir($app . '/src', 0775, true);
    @mkdir($app . '/config', 0775, true);
    @mkdir($app . '/data', 0775, true);
    file_put_contents($app . '/index.php', "<?php // v0\n");
    file_put_contents($app . '/src/a.php', "<?php // a v1\n");
    file_put_contents($app . '/config/config.php', "<?php return []; // DEL USUARIO\n");
    file_put_contents($app . '/data/panel.sqlite', 'BD');
    file_put_contents($app . '/VERSION', "0.9\n");

    $inst = new \CronPanel\Installer($app);

    $man = $inst->buildManifest();
    check('manifiesto excluye config.php', !isset($man['config/config.php']));
    check('manifiesto excluye data/', !isset($man['data/panel.sqlite']));
    check('manifiesto incluye el resto', isset($man['index.php'], $man['src/a.php'], $man['VERSION']));

    // release v1: instala también un fichero que luego desaparecerá
    $rel1 = $tmpDir . '/rel1/public_html';
    @mkdir($rel1 . '/src', 0775, true);
    file_put_contents($rel1 . '/index.php', "<?php // v1\n");
    file_put_contents($rel1 . '/src/a.php', "<?php // a v1\n");
    file_put_contents($rel1 . '/MORIR.php', "<?php // obsoleto\n");
    file_put_contents($rel1 . '/VERSION', "1.0\n");
    $r1 = $inst->syncFrom($rel1, '1.0');
    check('v1: copia 3 y salta el idéntico', $r1['copied'] === 3 && $r1['skipped'] === 1, json_encode($r1));
    check('v1: MORIR.php queda gestionado', is_file($app . '/MORIR.php'));

    // release v2: cambia index, añade b, quita MORIR
    $rel = $tmpDir . '/release/public_html';
    @mkdir($rel . '/src', 0775, true);
    file_put_contents($rel . '/index.php', "<?php // v2\n");
    file_put_contents($rel . '/src/a.php', "<?php // a v1\n");   // idéntico
    file_put_contents($rel . '/src/b.php', "<?php // b nuevo\n");
    file_put_contents($rel . '/VERSION', "2.0\n");

    $sync = $inst->syncFrom($rel, '2.0');
    check('sync: copia 3 (index, b, VERSION)', $sync['copied'] === 3, json_encode($sync));
    check('sync: salta el idéntico (a)', $sync['skipped'] === 1, json_encode($sync));
    check('sync: borra el obsoleto', $sync['deleted'] === 1 && !is_file($app . '/MORIR.php'), json_encode($sync));
    check('sync: config.php intacto', str_contains((string)file_get_contents($app . '/config/config.php'), 'DEL USUARIO'));
    check('sync: BD intacta', file_get_contents($app . '/data/panel.sqlite') === 'BD');
    check('sync: VERSION actualizada', $inst->version() === '2.0');
    check('sync: errores 0', $sync['errors'] === 0);

    $backup = $inst->createBackup();
    check('backup creado', is_dir($app . '/data/backups/' . $backup));
    check('backup con manifiesto', is_file($app . '/data/backups/' . $backup . '/data/.manifest.json'));
    check('backup con ficheros', is_file($app . '/data/backups/' . $backup . '/index.php'));
    check('backup NO lleva config.php', !is_file($app . '/data/backups/' . $backup . '/config/config.php'));

    // nueva versión que añade un fichero; luego rollback
    file_put_contents($rel . '/index.php', "<?php // v3\n");
    file_put_contents($rel . '/src/nuevo.php', "<?php // sobra\n");
    $inst->syncFrom($rel, '3.0');
    check('v3 añade el fichero nuevo', is_file($app . '/src/nuevo.php'));

    $restore = $inst->restoreBackup($backup);
    check('restore copia', $restore['restored'] >= 3, json_encode($restore));
    check('restore elimina lo nuevo', !is_file($app . '/src/nuevo.php'));
    check('restore recupera index', str_contains((string)file_get_contents($app . '/index.php'), 'v2'));
    check('restore recupera VERSION', $inst->version() === '2.0');

    $lanzado = false;
    try {
        $inst->restoreBackup('backup_9999');
    } catch (\RuntimeException) {
        $lanzado = true;
    }
    check('restore rechaza nombre inválido', $lanzado);

    // zip-slip
    check('safeEntry acepta rutas normales', \CronPanel\Installer::safeEntry('repo-sha/public_html/index.php'));
    check('safeEntry rechaza ..', !\CronPanel\Installer::safeEntry('../evil.php'));
    check('safeEntry rechaza .. en medio', !\CronPanel\Installer::safeEntry('a/../../b'));
    check('safeEntry rechaza absolutas', !\CronPanel\Installer::safeEntry('/etc/passwd'));
    check('safeEntry rechaza unidad Windows', !\CronPanel\Installer::safeEntry('C:/x.php'));

    // extracción real (PharData o ZipArchive, lo que haya)
    $zipPath = $tmpDir . '/rel.zip';
    $creado = false;
    try {
        if (class_exists(\ZipArchive::class)) {
            $z = new \ZipArchive();
            $z->open($zipPath, \ZipArchive::CREATE);
            $z->addFromString('repo-sha/public_html/index.php', "<?php // z\n");
            $z->addFromString('repo-sha/public_html/VERSION', "9.9\n");
            $z->addFromString('repo-sha/public_html/src/blob.bin', random_bytes(4096));
            $z->close();
            $creado = true;
        } else {
            $p = new \PharData($zipPath);
            $p->addFromString('repo-sha/public_html/index.php', "<?php // z\n");
            $p->addFromString('repo-sha/public_html/VERSION', "9.9\n");
            $p->addFromString('repo-sha/public_html/src/blob.bin', random_bytes(4096));
            unset($p);
            $creado = filesize($zipPath) > 1024;
        }
    } catch (\Throwable $e) {
        $creado = false;
    }

    if ($creado) {
        $found = $inst->extractArchive($zipPath, $tmpDir . '/x');
        check('zip: encuentra public_html', is_file($found . '/index.php') && is_dir($found . '/src'));
        check('zip: extrae el contenido', str_contains((string)file_get_contents($found . '/index.php'), 'z'));
    } else {
        echo "SKIP  zip: no se pudo crear el fixture en este PHP\n";
    }
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
