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
        global $CRONPANEL_CONFIG;

        $headers = [
            'Accept: application/vnd.github+json',
            'User-Agent: cronpanel/' . $this->installedVersion(),
        ];
        $token = trim((string)($CRONPANEL_CONFIG['github_token'] ?? ''));
        if ($token !== '') {
            $headers[] = 'Authorization: Bearer ' . $token;
        }

        if ($this->httpGet !== null) {
            /** @var mixed $body */
            $body = ($this->httpGet)($url, $headers);
            if (!is_string($body)) {
                throw new RuntimeException('respuesta HTTP inválida');
            }

            return $body;
        }

        if (function_exists('curl_init')) {
            $ch = curl_init($url);
            curl_setopt_array($ch, [
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_FOLLOWLOCATION => true,
                CURLOPT_MAXREDIRS => 3,
                CURLOPT_CONNECTTIMEOUT => 5,
                CURLOPT_TIMEOUT => self::TIMEOUT,
                CURLOPT_HTTPHEADER => $headers,
            ]);
            $body = curl_exec($ch);
            $status = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
            $error = curl_error($ch);
            curl_close($ch);

            if ($body === false) {
                throw new RuntimeException('sin conexión con GitHub: ' . $error);
            }
            $this->assertStatus($status);

            return (string)$body;
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
        if (isset($http_response_header[0])
            && preg_match('#\s(\d{3})\s#', (string)$http_response_header[0], $m) === 1) {
            $status = (int)$m[1];
        }
        $this->assertStatus($status);

        return (string)$body;
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
