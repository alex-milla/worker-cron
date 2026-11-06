<?php
declare(strict_types=1);

namespace CronPanel;

use PharData;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;
use RuntimeException;
use Throwable;
use ZipArchive;

/**
 * Instalador del panel: port de `worker/cronworker/updater.py`.
 *
 * Misma mecánica que en el worker, pero `app_root` es `public_html/`:
 * manifiesto SHA-256, sincronización por diferencias, backups y restauración.
 *
 * Nunca toca `config/config.php` ni `data/` (la BD, los backups y el temporal).
 */
final class Installer
{
    public const MANIFEST = 'data/.manifest.json';

    private const BACKUP_PREFIX = 'backup_';
    private const TMP_SUFFIX = '.tmp-upd';

    /** Estado del usuario: nunca se copia ni se borra. */
    private const SENSITIVE_FILES = ['config/config.php'];
    private const SENSITIVE_PREFIXES = ['data/'];

    private string $appRoot;

    public function __construct(?string $appRoot = null)
    {
        $root = $appRoot ?? (defined('CRONPANEL_ROOT') ? CRONPANEL_ROOT : dirname(__DIR__));
        $this->appRoot = rtrim(str_replace('\\', '/', (string)$root), '/');
    }

    public function appRoot(): string
    {
        return $this->appRoot;
    }

    /** Versión instalada (fichero VERSION del panel). */
    public function version(): string
    {
        $file = $this->appRoot . '/VERSION';

        return is_file($file) ? trim((string)file_get_contents($file)) : '0.0.0';
    }

    public function isSensitive(string $rel): bool
    {
        $rel = str_replace('\\', '/', $rel);
        if (in_array($rel, self::SENSITIVE_FILES, true)) {
            return true;
        }
        foreach (self::SENSITIVE_PREFIXES as $prefix) {
            if (str_starts_with($rel, $prefix)) {
                return true;
            }
        }

        return false;
    }

    // --------------------------------------------------------- manifiesto --

    /** @return array<string, string> ruta relativa => sha256 */
    public function buildManifest(?string $root = null): array
    {
        $root = rtrim(str_replace('\\', '/', $root ?? $this->appRoot), '/');
        if (!is_dir($root)) {
            return [];
        }

        $manifest = [];
        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($root, \FilesystemIterator::SKIP_DOTS)
        );

        foreach ($iterator as $file) {
            if (!$file->isFile()) {
                continue;
            }
            $path = str_replace('\\', '/', $file->getPathname());
            $rel = ltrim(substr($path, strlen($root)), '/');
            if ($rel === '' || str_ends_with($rel, self::TMP_SUFFIX) || $this->isSensitive($rel)) {
                continue;
            }
            $hash = hash_file('sha256', $path);
            if ($hash !== false) {
                $manifest[$rel] = $hash;
            }
        }

        ksort($manifest);

        return $manifest;
    }

    /** @return array<string, string> */
    public function loadManifest(): array
    {
        return $this->readManifest($this->appRoot . '/' . self::MANIFEST);
    }

    /** @return array<string, string> */
    private function readManifest(string $file): array
    {
        if (!is_file($file)) {
            return [];
        }
        $data = json_decode((string)file_get_contents($file), true);
        if (!is_array($data) || !is_array($data['files'] ?? null)) {
            return [];
        }

        return $data['files'];
    }

    /** @param array<string, string> $files */
    public function saveManifest(string $version, array $files): void
    {
        $this->atomicWrite(
            $this->appRoot . '/' . self::MANIFEST,
            (string)json_encode([
                'version' => $version,
                'generated_at' => date('Y-m-d\TH:i:s'),
                'files' => $files,
            ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)
        );
    }

    // ------------------------------------------------------------ escritura --

    private function atomicWrite(string $path, string $contents): void
    {
        $this->ensureDir(dirname($path));

        $tmp = $path . self::TMP_SUFFIX;
        if (@file_put_contents($tmp, $contents) === false) {
            throw new RuntimeException("no se pudo escribir {$path}");
        }
        if (!@rename($tmp, $path)) {
            @unlink($tmp);
            throw new RuntimeException("no se pudo reemplazar {$path}");
        }
    }

    private function atomicCopy(string $src, string $dst): void
    {
        $this->ensureDir(dirname($dst));

        $tmp = $dst . self::TMP_SUFFIX;
        if (!@copy($src, $tmp)) {
            throw new RuntimeException("no se pudo copiar a {$dst}");
        }
        if (!@rename($tmp, $dst)) {
            @unlink($tmp);
            throw new RuntimeException("no se pudo reemplazar {$dst}");
        }
    }

    private function ensureDir(string $dir): void
    {
        if (!is_dir($dir) && !@mkdir($dir, 0775, true) && !is_dir($dir)) {
            throw new RuntimeException("no se pudo crear el directorio {$dir}");
        }
    }

    /** Comprueba de verdad que podemos escribir (error claro antes de nada). */
    public function checkWritable(): void
    {
        foreach ([$this->appRoot, $this->appRoot . '/data'] as $dir) {
            $this->ensureDir($dir);
            $probe = $dir . '/.write-probe';
            if (@file_put_contents($probe, '') === false) {
                throw new RuntimeException(
                    "sin permiso de escritura en {$dir}. Revisa los permisos de ficheros del hosting."
                );
            }
            @unlink($probe);
        }
    }

    // ----------------------------------------------------------------- sync --

    /**
     * Sincroniza `$src` (la `public_html/` de la release) sobre el panel.
     *
     * @return array{copied:int, skipped:int, deleted:int, errors:int, error_detail:list<string>}
     */
    public function syncFrom(string $src, string $version): array
    {
        $src = rtrim(str_replace('\\', '/', $src), '/');
        $new = $this->buildManifest($src);
        $old = $this->loadManifest();

        if ($new === []) {
            throw new RuntimeException('la release no contiene ficheros de public_html/');
        }

        $copied = $skipped = $deleted = $errors = 0;
        $detail = [];

        foreach ($new as $rel => $sha) {
            $dst = $this->appRoot . '/' . $rel;
            try {
                if (is_file($dst) && hash_file('sha256', $dst) === $sha) {
                    $skipped++;
                    continue;
                }
                $this->atomicCopy($src . '/' . $rel, $dst);
                $copied++;
            } catch (Throwable $e) {
                $errors++;
                $detail[] = $rel . ': ' . $e->getMessage();
            }
        }

        foreach ($old as $rel => $sha) {
            if (isset($new[$rel]) || $this->isSensitive($rel)) {
                continue;
            }
            $stale = $this->appRoot . '/' . $rel;
            try {
                if (is_file($stale)) {
                    unlink($stale);
                    $deleted++;
                }
            } catch (Throwable $e) {
                $errors++;
                $detail[] = $rel . ': ' . $e->getMessage();
            }
        }

        $this->saveManifest($version, $new);

        return [
            'copied' => $copied, 'skipped' => $skipped,
            'deleted' => $deleted, 'errors' => $errors, 'error_detail' => $detail,
        ];
    }

    // ------------------------------------------------------------------ zip --

    /** Extrae el ZIP (anti zip-slip) y devuelve la carpeta `public_html/` de dentro. */
    public function extractArchive(string $archive, string $dest): string
    {
        $this->ensureDir($dest);

        if (!is_file($archive) || filesize($archive) < 1024) {
            throw new RuntimeException('el ZIP descargado está vacío o es demasiado pequeño');
        }

        if (class_exists(ZipArchive::class)) {
            $zip = new ZipArchive();
            if ($zip->open($archive) !== true) {
                throw new RuntimeException('no se pudo abrir el ZIP de la release');
            }
            for ($i = 0; $i < $zip->numFiles; $i++) {
                $name = (string)$zip->getNameIndex($i);
                if (!self::safeEntry($name)) {
                    throw new RuntimeException('entrada peligrosa en el ZIP: ' . $name);
                }
            }
            $ok = $zip->extractTo($dest);
            $zip->close();
            if (!$ok) {
                throw new RuntimeException('fallo al extraer el ZIP');
            }
        } else {
            try {
                $phar = new PharData($archive);
                $phar->extractTo($dest, null, true);
                unset($phar);
            } catch (Throwable $e) {
                throw new RuntimeException(
                    'no se pudo extraer el ZIP: falta la extensión zip y PharData falló ('
                    . $e->getMessage() . ')'
                );
            }
        }

        return $this->locateAppDir($dest);
    }

    /** Entrada segura: sin rutas absolutas, sin `..` y sin unidad de Windows. */
    public static function safeEntry(string $name): bool
    {
        $normalized = str_replace('\\', '/', $name);
        if (str_starts_with($normalized, '/')) {
            return false;
        }
        if (preg_match('#^[A-Za-z]:/#', $normalized) === 1) {
            return false;
        }

        return preg_match('#(^|/)\.\.(/|$)#', $normalized) !== 1;
    }

    private function locateAppDir(string $dest): string
    {
        $candidates = array_merge(
            [rtrim($dest, '/') . '/public_html'],
            glob(rtrim($dest, '/') . '/*/public_html', GLOB_ONLYDIR) ?: []
        );

        foreach ($candidates as $candidate) {
            if (is_file($candidate . '/index.php') && is_dir($candidate . '/src')) {
                return str_replace('\\', '/', $candidate);
            }
        }

        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($dest, \FilesystemIterator::SKIP_DOTS),
            RecursiveIteratorIterator::SELF_FIRST
        );
        foreach ($iterator as $file) {
            if ($file->isDir() && $file->getFilename() === 'public_html') {
                $path = str_replace('\\', '/', $file->getPathname());
                if (is_file($path . '/index.php') && is_dir($path . '/src')) {
                    return $path;
                }
            }
        }

        throw new RuntimeException('no se encontró la carpeta public_html/ dentro del ZIP');
    }

    // -------------------------------------------------------------- backups --

    private function backupsDir(): string
    {
        return $this->appRoot . '/data/backups';
    }

    public function createBackup(): string
    {
        $base = date('Ymd_His');
        $dir = $this->backupsDir() . '/' . self::BACKUP_PREFIX . $base;
        $suffix = 0;
        while (is_dir($dir)) {
            $suffix++;
            $dir = $this->backupsDir() . '/' . self::BACKUP_PREFIX . $base . '_' . $suffix;
        }
        $this->ensureDir($dir);

        $manifest = $this->loadManifest();
        if ($manifest === []) {
            // Primera actualización (no hay manifiesto): backup del árbol completo.
            $manifest = $this->buildManifest();
        }

        foreach ($manifest as $rel => $sha) {
            $src = $this->appRoot . '/' . $rel;
            if (!is_file($src)) {
                continue;
            }
            $this->atomicCopy($src, $dir . '/' . $rel);
        }

        // El backup lleva su propio manifiesto para poder restaurar el estado exacto.
        $this->atomicWrite(
            $dir . '/' . self::MANIFEST,
            (string)json_encode([
                'version' => $this->version(),
                'generated_at' => date('Y-m-d\TH:i:s'),
                'files' => $manifest,
            ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)
        );

        return basename($dir);
    }

    /** @return list<string> nombres ordenados del más reciente al más antiguo */
    public function listBackups(): array
    {
        $base = $this->backupsDir();
        if (!is_dir($base)) {
            return [];
        }

        $names = [];
        foreach (scandir($base) ?: [] as $item) {
            if ($item === '.' || $item === '..') {
                continue;
            }
            if (is_dir($base . '/' . $item) && str_starts_with($item, self::BACKUP_PREFIX)) {
                $names[] = $item;
            }
        }

        rsort($names);

        return $names;
    }

    /**
     * Restaura un backup (con pre-backup del estado actual).
     *
     * @return array{restored:int, removed:int, pre_backup:string}
     */
    public function restoreBackup(string $name): array
    {
        if (preg_match('/^' . self::BACKUP_PREFIX . '\d{8}_\d{6}(_\d+)?$/', $name) !== 1) {
            throw new RuntimeException('nombre de backup no válido');
        }

        $base = realpath($this->backupsDir());
        $dir = realpath($this->backupsDir() . '/' . $name);
        if ($base === false || $dir === false || !str_starts_with(str_replace('\\', '/', $dir), str_replace('\\', '/', $base))) {
            throw new RuntimeException('backup fuera de data/backups');
        }
        if (!is_dir($dir)) {
            throw new RuntimeException('backup no encontrado');
        }

        $files = $this->readManifest($dir . '/' . self::MANIFEST);
        if ($files === []) {
            throw new RuntimeException('el backup no contiene manifiesto: no se puede restaurar');
        }

        $pre = $this->createBackup();

        $copied = 0;
        foreach ($files as $rel => $sha) {
            if ($this->isSensitive($rel)) {
                continue;
            }
            $src = $dir . '/' . $rel;
            if (!is_file($src)) {
                continue;
            }
            $this->atomicCopy($src, $this->appRoot . '/' . $rel);
            $copied++;
        }

        // Rollback completo: fuera los gestionados que introdujo la versión posterior.
        $current = $this->loadManifest();
        $removed = 0;
        foreach ($current as $rel => $sha) {
            if (isset($files[$rel]) || $this->isSensitive($rel)) {
                continue;
            }
            $stale = $this->appRoot . '/' . $rel;
            try {
                if (is_file($stale)) {
                    unlink($stale);
                    $removed++;
                }
            } catch (Throwable) {
                // se ignora: el resto del rollback ya se aplicó
            }
        }

        $this->saveManifest($this->version(), $files);

        return ['restored' => $copied, 'removed' => $removed, 'pre_backup' => $pre];
    }
}
