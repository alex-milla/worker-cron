<?php
declare(strict_types=1);

namespace CronPanel;

use Closure;
use PDO;
use RuntimeException;
use Throwable;

/**
 * Comprobación de la última release del repositorio en GitHub.
 *
 * Es SOLO informativa: consulta `releases/latest` y la cachea en `meta` para
 * no agotar el límite de la API (60 peticiones/hora por IP). No descarga ni
 * escribe código: el panel se despliega subiendo ficheros al hosting.
 */
final class Updater
{
    private const CACHE_KEY = 'github_release';
    private const TTL_OK = 1800;    // 30 min si fue bien
    private const TTL_ERROR = 300;  // 5 min si falló
    private const TIMEOUT = 8;
    private const DEFAULT_REPO = 'alex-milla/worker-cron';

    private ?Closure $httpGet;
    private PDO $pdo;

    public function __construct(?callable $httpGet = null, ?PDO $pdo = null)
    {
        $this->httpGet = $httpGet === null ? null : Closure::fromCallable($httpGet);
        $this->pdo = $pdo ?? Database::pdo();
    }

    public function installedVersion(): string
    {
        return defined('CRONPANEL_VERSION') ? (string)CRONPANEL_VERSION : 'dev';
    }

    public function repo(): string
    {
        global $CRONPANEL_CONFIG;

        $repo = trim((string)($CRONPANEL_CONFIG['github_repo'] ?? ''));

        return $repo !== '' ? $repo : self::DEFAULT_REPO;
    }

    // ------------------------------------------------------------- token --

    private ?string $tokenCache = null;

    /** Token de GitHub: BD (`meta.github_token`) y, si no hay, config.php. */
    public function token(): string
    {
        if ($this->tokenCache !== null) {
            return $this->tokenCache;
        }

        global $CRONPANEL_CONFIG;

        $token = '';
        try {
            $stmt = $this->pdo->prepare("SELECT value FROM meta WHERE key = 'github_token'");
            $stmt->execute();
            $value = $stmt->fetchColumn();
            $token = $value === false || $value === null ? '' : (string)$value;
        } catch (Throwable) {
            $token = '';
        }

        if ($token === '') {
            $token = trim((string)($CRONPANEL_CONFIG['github_token'] ?? ''));
        }

        return $this->tokenCache = $token;
    }

    public function setToken(string $token): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO meta (key, value) VALUES (?, ?)'
            . ' ON CONFLICT(key) DO UPDATE SET value = excluded.value'
        );
        $stmt->execute(['github_token', $token]);
        $this->tokenCache = $token;
    }

    public function clearToken(): void
    {
        $this->pdo->prepare("DELETE FROM meta WHERE key = 'github_token'")->execute();
        $this->tokenCache = null;
    }

    /** Descarga el zipball de la release (binario) al fichero indicado. */
    public function downloadRelease(array $release, string $dest): void
    {
        $url = trim((string)($release['zip_url'] ?? ''));
        if ($url === '') {
            throw new RuntimeException('la release no trae zipball_url');
        }

        $body = $this->request($url);
        if (strlen($body) < 1024) {
            throw new RuntimeException('ZIP sospechosamente pequeño (< 1 KiB): descarga corrupta');
        }

        $this->ensureDir(dirname($dest));
        if (@file_put_contents($dest, $body) === false) {
            throw new RuntimeException('no se pudo guardar el ZIP descargado');
        }
    }

    private function ensureDir(string $dir): void
    {
        if (!is_dir($dir) && !@mkdir($dir, 0775, true) && !is_dir($dir)) {
            throw new RuntimeException("no se pudo crear el directorio {$dir}");
        }
    }

    /**
     * Consulta (o lee de caché) la última release.
     *
     * @return array{release: ?array<string, mixed>, error: ?string, cached: bool, checkedAt: ?int}
     */
    public function check(bool $force = false): array
    {
        if (!$force) {
            $cached = $this->readCache();
            if ($cached !== null) {
                return $cached;
            }
        }

        $resultado = $this->fetch();
        $this->writeCache($resultado);

        return $resultado;
    }

    // ------------------------------------------------------------ interno --

    /** @return array{release: ?array<string, mixed>, error: ?string, cached: bool, checkedAt: int} */
    private function fetch(): array
    {
        global $CRONPANEL_CONFIG;

        $base = rtrim((string)($CRONPANEL_CONFIG['github_api_base'] ?? 'https://api.github.com'), '/');
        $url = $base . '/repos/' . $this->repo() . '/releases/latest';

        try {
            $body = $this->request($url);
            $data = json_decode($body, true, 16, JSON_THROW_ON_ERROR);
        } catch (Throwable $e) {
            return [
                'release' => null,
                'error' => $e->getMessage(),
                'cached' => false,
                'checkedAt' => time(),
            ];
        }

        if (!is_array($data) || empty($data['tag_name'])) {
            return [
                'release' => null,
                'error' => 'GitHub devolvió una respuesta inesperada',
                'cached' => false,
                'checkedAt' => time(),
            ];
        }

        return [
            'release' => [
                'version' => ltrim((string)$data['tag_name'], 'v'),
                'notes' => (string)($data['body'] ?? ''),
                'zip_url' => (string)($data['zipball_url'] ?? ''),
                'html_url' => (string)($data['html_url'] ?? ''),
                'published_at' => $data['published_at'] ?? null,
            ],
            'error' => null,
            'cached' => false,
            'checkedAt' => time(),
        ];
    }

    private function request(string $url): string
    {
        $token = $this->token();
        $origHost = (string)parse_url($url, PHP_URL_HOST);
        $target = $url;

        for ($hop = 0; $hop <= 3; $hop++) {
            $headers = [
                'Accept: application/vnd.github+json',
                'User-Agent: cronpanel/' . $this->installedVersion(),
            ];
            // el token solo viaja al host original (el zipball redirige a codeload)
            if ($token !== '' && (string)parse_url($target, PHP_URL_HOST) === $origHost) {
                $headers[] = 'Authorization: Bearer ' . $token;
            }

            if ($this->httpGet !== null) {
                /** @var mixed $body */
                $body = ($this->httpGet)($target, $headers);
                if (!is_string($body)) {
                    throw new RuntimeException('respuesta HTTP inválida');
                }

                return $body;
            }

            [$status, $body, $location] = $this->fetchOnce($target, $headers);

            if ($status === 200) {
                return $body;
            }
            if (in_array($status, [301, 302, 303, 307, 308], true)
                && $location !== null
                && $hop < 3) {
                $target = $location;
                continue;
            }

            $this->assertStatus($status);

            return $body;
        }

        throw new RuntimeException('demasiadas redirecciones desde GitHub');
    }

    /**
     * Una petición, sin seguir redirecciones (las gestiona `request()`).
     *
     * @param list<string> $headers
     * @return array{0:int, 1:string, 2:?string} [status, body, location]
     */
    private function fetchOnce(string $url, array $headers): array
    {
        if (function_exists('curl_init')) {
            $ch = curl_init($url);
            curl_setopt_array($ch, [
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_FOLLOWLOCATION => false,
                CURLOPT_CONNECTTIMEOUT => 5,
                CURLOPT_TIMEOUT => self::TIMEOUT,
                CURLOPT_HTTPHEADER => $headers,
            ]);
            $body = curl_exec($ch);
            $status = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
            $location = curl_getinfo($ch, CURLINFO_REDIRECT_URL);
            $error = curl_error($ch);
            curl_close($ch);

            if ($body === false) {
                throw new RuntimeException('sin conexión con GitHub: ' . $error);
            }

            return [$status, (string)$body, is_string($location) && $location !== '' ? $location : null];
        }

        if (!ini_get('allow_url_fopen')) {
            throw new RuntimeException('el hosting no permite cURL ni allow_url_fopen');
        }

        $context = stream_context_create([
            'http' => [
                'method' => 'GET',
                'header' => implode("\r\n", $headers),
                'timeout' => self::TIMEOUT,
                'ignore_errors' => true,
            ],
            'ssl' => ['verify_peer' => true, 'verify_peer_name' => true],
        ]);
        $body = @file_get_contents($url, false, $context);
        if ($body === false) {
            throw new RuntimeException('sin conexión con GitHub');
        }

        $status = 200;
        $location = null;
        foreach ($http_response_header ?? [] as $header) {
            if (preg_match('#^HTTP/\S+\s+(\d{3})#', $header, $m) === 1) {
                $status = (int)$m[1];
            } elseif (stripos($header, 'Location:') === 0) {
                $location = trim(substr($header, 9));
            }
        }

        return [$status, (string)$body, $location];
    }

    private function assertStatus(int $status): void
    {
        if ($status === 200) {
            return;
        }
        if ($status === 403 || $status === 429) {
            throw new RuntimeException('GitHub ha limitado las peticiones (espera unos minutos)');
        }
        if ($status === 404) {
            throw new RuntimeException('el repositorio no existe o no tiene releases publicadas');
        }

        throw new RuntimeException('GitHub devolvió HTTP ' . $status);
    }

    /** @return array{release: ?array<string, mixed>, error: ?string, cached: bool, checkedAt: int}|null */
    private function readCache(): ?array
    {
        $stmt = $this->pdo->prepare('SELECT value FROM meta WHERE key = ?');
        $stmt->execute([self::CACHE_KEY]);
        $raw = $stmt->fetchColumn();
        if ($raw === false || $raw === null) {
            return null;
        }

        $data = json_decode((string)$raw, true);
        if (!is_array($data) || !isset($data['checkedAt'])) {
            return null;
        }

        $ttl = ($data['error'] ?? null) === null ? self::TTL_OK : self::TTL_ERROR;
        if (time() - (int)$data['checkedAt'] > $ttl) {
            return null;
        }

        return [
            'release' => is_array($data['release'] ?? null) ? $data['release'] : null,
            'error' => isset($data['error']) ? (string)$data['error'] : null,
            'cached' => true,
            'checkedAt' => (int)$data['checkedAt'],
        ];
    }

    /** @param array{release: ?array<string, mixed>, error: ?string, checkedAt: int} $result */
    private function writeCache(array $result): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO meta (key, value) VALUES (?, ?)'
            . ' ON CONFLICT(key) DO UPDATE SET value = excluded.value'
        );
        $stmt->execute([
            self::CACHE_KEY,
            json_encode($result, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
        ]);
    }
}
