<?php
declare(strict_types=1);

namespace CronPanel;

/**
 * API REST para el worker (v1). El worker hace PULL: nunca se le empuja nada.
 *
 *   GET  /api/v1/version    {revision}                        (polling barato)
 *   GET  /api/v1/jobs       {revision, jobs:[...]}            (solo activos)
 *   POST /api/v1/results    registra una ejecución            -> 201 {id}
 *   POST /api/v1/heartbeat  aviso de vida del worker          -> 200 {ok}
 *
 * Autenticación: `Authorization: Bearer <api_token>` (config.php).
 * Todas las respuestas llevan la cabecera `X-Revision`.
 */
final class ApiController
{
    private const MAX_BODY = 1048576;   // 1 MiB
    private const MAX_OUTPUT = 65536;   // 64 KiB
    private const STATUSES = ['ok', 'failed', 'timeout'];

    private JobRepository $jobs;
    private RunRepository $runs;
    private WorkerRepository $workers;
    private ?int $cachedRevision = null;

    public function __construct(
        ?JobRepository $jobs = null,
        ?RunRepository $runs = null,
        ?WorkerRepository $workers = null
    ) {
        $this->jobs = $jobs ?? new JobRepository();
        $this->runs = $runs ?? new RunRepository();
        $this->workers = $workers ?? new WorkerRepository();
    }

    public function handle(string $method, string $uri): void
    {
        $method = strtoupper($method);
        $path = $this->path($uri);

        if (preg_match('#^/api/v1/([a-z]+)/?$#', $path, $m) !== 1) {
            $this->fail(404, 'Endpoint no encontrado');
        }
        $route = $m[1];

        if (!Auth::apiTokenValid()) {
            $this->fail(401, 'Token de API inválido');
        }

        $allowed = [
            'version' => 'GET',
            'jobs' => 'GET',
            'results' => 'POST',
            'heartbeat' => 'POST',
        ];
        if (!isset($allowed[$route])) {
            $this->fail(404, 'Endpoint no encontrado');
        }
        if ($allowed[$route] !== $method) {
            header('Allow: ' . $allowed[$route]);
            $this->fail(405, 'Método no permitido');
        }

        match ($route) {
            'version' => $this->version(),
            'jobs' => $this->jobs(),
            'results' => $this->results(),
            'heartbeat' => $this->heartbeat(),
        };
    }

    // -------------------------------------------------------------- rutas --

    private function version(): void
    {
        global $CRONPANEL_CONFIG;

        $this->respond(200, [
            'revision' => $this->revision(),
            'api_version' => (string)($CRONPANEL_CONFIG['api_version'] ?? 'v1'),
            'server_time' => gmdate('c'),
        ]);
    }

    private function jobs(): void
    {
        // Solo activos: el worker sincroniza lo que debe ejecutar.
        $rows = $this->jobs->listJobs(true);

        $jobs = [];
        foreach ($rows as $row) {
            $jobs[] = [
                'id' => (int)$row['id'],
                'name' => (string)$row['name'],
                'cron_expr' => (string)$row['cron_expr'],
                'command' => (string)$row['command'],
                'timeout_sec' => (int)$row['timeout_sec'],
                'enabled' => (int)$row['enabled'],
                'comment' => $row['comment'],
                'updated_at' => (string)($row['updated_at'] ?? ''),
            ];
        }

        $this->respond(200, [
            'revision' => $this->revision(),
            'count' => count($jobs),
            'jobs' => $jobs,
        ]);
    }

    private function results(): void
    {
        $data = $this->jsonBody();

        $jobId = (int)($data['job_id'] ?? 0);
        $status = (string)($data['status'] ?? '');
        $started = (string)($data['started_at'] ?? '');

        if ($jobId <= 0) {
            $this->fail(400, 'job_id obligatorio');
        }
        if (!in_array($status, self::STATUSES, true)) {
            $this->fail(400, 'status debe ser ok, failed o timeout');
        }
        if (!self::validTimestamp($started)) {
            $this->fail(400, 'started_at obligatorio (ISO-8601)');
        }
        if ($this->jobs->getJob($jobId) === null) {
            $this->fail(404, 'job_id inexistente');
        }

        $finished = isset($data['finished_at']) ? (string)$data['finished_at'] : '';
        if ($finished !== '' && !self::validTimestamp($finished)) {
            $this->fail(400, 'finished_at inválido (ISO-8601)');
        }

        $exitCode = $data['exit_code'] ?? null;
        if ($exitCode !== null && !is_int($exitCode) && !ctype_digit((string)$exitCode)) {
            $this->fail(400, 'exit_code debe ser entero');
        }

        $output = (string)($data['output'] ?? '');
        if (strlen($output) > self::MAX_OUTPUT) {
            $output = substr($output, 0, self::MAX_OUTPUT) . "\n[truncado]";
        }

        $id = $this->runs->add([
            'job_id' => $jobId,
            'started_at' => $started,
            'finished_at' => $finished,
            'status' => $status,
            'exit_code' => $exitCode === null ? null : (int)$exitCode,
            'output' => $output,
        ]);

        $this->respond(201, ['id' => $id, 'revision' => $this->revision()]);
    }

    private function heartbeat(): void
    {
        $data = $this->jsonBody();
        $name = trim((string)($data['name'] ?? ''));

        if ($name === '') {
            $this->fail(400, 'name obligatorio');
        }

        $revision = isset($data['revision']) ? (int)$data['revision'] : null;
        $this->workers->heartbeat($name, $revision);

        $this->respond(200, ['ok' => true, 'revision' => $this->revision()]);
    }

    // ------------------------------------------------------------ helpers --

    private function path(string $uri): string
    {
        global $CRONPANEL_CONFIG;

        $path = (string)(parse_url($uri, PHP_URL_PATH) ?: '/');
        $base = rtrim((string)($CRONPANEL_CONFIG['base_path'] ?? ''), '/');
        if ($base !== '' && str_starts_with($path, $base)) {
            $path = substr($path, strlen($base));
        }

        return $path === '' ? '/' : $path;
    }

    private function revision(): int
    {
        return $this->cachedRevision ??= $this->jobs->revision();
    }

    /** @return array<string, mixed> */
    private function jsonBody(): array
    {
        $raw = (string)file_get_contents('php://input');
        if (strlen($raw) > self::MAX_BODY) {
            $this->fail(413, 'Cuerpo demasiado grande');
        }
        if (trim($raw) === '') {
            $this->fail(400, 'Cuerpo JSON obligatorio');
        }

        try {
            $data = json_decode($raw, true, 16, JSON_THROW_ON_ERROR);
        } catch (\JsonException) {
            $this->fail(400, 'JSON inválido');
        }

        if (!is_array($data)) {
            $this->fail(400, 'El cuerpo debe ser un objeto JSON');
        }

        return $data;
    }

    private static function validTimestamp(string $value): bool
    {
        return preg_match('/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}/', $value) === 1;
    }

    /** @param array<string, mixed> $payload */
    private function respond(int $status, array $payload): void
    {
        http_response_code($status);
        header('Content-Type: application/json; charset=utf-8');
        header('Cache-Control: no-store');
        header('X-Revision: ' . $this->revision());

        echo json_encode(
            $payload,
            JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE
        );
    }

    private function fail(int $status, string $message): never
    {
        $this->respond($status, ['error' => $message]);
        exit;
    }
}
