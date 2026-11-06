<?php
declare(strict_types=1);

namespace CronPanel;

use InvalidArgumentException;

/**
 * Rutas y vistas del panel (hosting compartido).
 *
 * Rutas:
 *   GET  /                      dashboard (tareas + últimas ejecuciones)
 *   GET  /login  POST /login    acceso
 *   POST /logout                salir
 *   GET  /jobs/new              alta de tarea
 *   GET  /jobs/{id}/edit        edición
 *   POST /jobs/new|/{id}/edit   guardar
 *   POST /jobs/{id}/toggle      activar/pausar
 *   POST /jobs/{id}/delete      borrar
 *   GET  /runs                  historial de ejecuciones
 *
 * La API del worker (POST /api/*) la sirve ApiController y no pasa por aquí.
 */
final class WebController
{
    private JobRepository $jobs;
    private RunRepository $runs;
    private UserRepository $users;
    private Updater $updater;

    public function __construct(
        ?JobRepository $jobs = null,
        ?RunRepository $runs = null,
        ?UserRepository $users = null,
        ?Updater $updater = null
    ) {
        $this->jobs = $jobs ?? new JobRepository();
        $this->runs = $runs ?? new RunRepository();
        $this->users = $users ?? new UserRepository();
        $this->updater = $updater ?? new Updater();
    }

    public function handle(string $method, string $uri): void
    {
        Auth::startSession();

        $path = (string)(parse_url($uri, PHP_URL_PATH) ?: '/');
        $path = $this->stripBasePath($path);
        $path = rtrim($path, '/');
        if ($path === '') {
            $path = '/';
        }
        $method = strtoupper($method);

        // ---- públicas ----
        if ($path === '/login') {
            $this->login($method);
            return;
        }
        if ($path === '/logout' && $method === 'POST') {
            $this->logout();
            return;
        }

        // ---- a partir de aquí hace falta sesión ----
        Auth::requireAuth();

        if ($path === '/') {
            $this->dashboard();
            return;
        }
        if ($path === '/jobs/new') {
            $this->jobForm($method, null);
            return;
        }
        if ($path === '/runs') {
            $this->runsPage();
            return;
        }
        if ($path === '/perfil') {
            $this->profile($method);
            return;
        }
        if ($path === '/updates') {
            $this->updatesPage();
            return;
        }
        if (preg_match('#^/jobs/(\d+)/edit$#', $path, $m) === 1) {
            $this->jobForm($method, (int)$m[1]);
            return;
        }
        if ($method === 'POST' && preg_match('#^/jobs/(\d+)/toggle$#', $path, $m) === 1) {
            $this->jobToggle((int)$m[1]);
            return;
        }
        if ($method === 'POST' && preg_match('#^/jobs/(\d+)/delete$#', $path, $m) === 1) {
            $this->jobDelete((int)$m[1]);
            return;
        }

        $this->notFound();
    }

    // ------------------------------------------------------------- login --

    private function login(string $method): void
    {
        if (Auth::check()) {
            $this->redirect('/');
        }

        $error = '';
        $username = '';

        if ($method === 'POST') {
            $this->requireCsrf();
            $username = trim((string)($_POST['username'] ?? ''));
            $password = (string)($_POST['password'] ?? '');

            if ($username === '' || $password === '') {
                $error = 'Todos los campos son obligatorios.';
            } elseif (Auth::login($username, $password)) {
                $this->flash('ok', 'Sesión iniciada.');
                $this->redirect('/');
            } else {
                $error = 'Credenciales inválidas.';
            }
        }

        $this->renderStandalone('login', [
            'title' => 'Iniciar sesión',
            'error' => $error,
            'username' => $username,
            'csrf' => Auth::csrfToken(),
            'configurado' => Auth::isConfigured(),
        ]);
    }

    private function logout(): void
    {
        $this->requireCsrf();
        Auth::logout();
        $this->redirect('/login');
    }

    // --------------------------------------------------------- dashboard --

    private function dashboard(): void
    {
        $this->render('Dashboard', 'dashboard', [
            'active' => 'dashboard',
            'jobs' => $this->jobs->listJobs(),
            'runs' => $this->runs->recent(10),
            'revision' => $this->jobs->revision(),
            'csrf' => Auth::csrfToken(),
        ]);
    }

    private function runsPage(): void
    {
        $this->render('Ejecuciones', 'runs', [
            'active' => 'runs',
            'runs' => $this->runs->recent(50),
            'revision' => $this->jobs->revision(),
        ]);
    }

    // -------------------------------------------------------------- perfil --

    private function profile(string $method): void
    {
        $uid = Auth::id();
        $user = $this->users->findById($uid);
        if ($user === null) {
            $this->redirect('/logout');
        }

        $error = '';
        $values = ['username' => (string)$user['username']];

        if ($method === 'POST') {
            $this->requireCsrf();

            $current = (string)($_POST['current_password'] ?? '');
            $newUsername = trim((string)($_POST['username'] ?? ''));
            $new = (string)($_POST['new_password'] ?? '');
            $new2 = (string)($_POST['new_password2'] ?? '');
            $values['username'] = $newUsername;

            try {
                if ($current === '') {
                    throw new InvalidArgumentException('Escribe tu contraseña actual');
                }
                if (!$this->users->verifyCurrentPassword($uid, $current)) {
                    throw new InvalidArgumentException('La contraseña actual no es correcta');
                }

                $cambioClave = ($new !== '' || $new2 !== '');
                if ($cambioClave) {
                    if ($new !== $new2) {
                        throw new InvalidArgumentException('Las contraseñas nuevas no coinciden');
                    }
                    if (strlen($new) < 8) {
                        throw new InvalidArgumentException(
                            'La nueva contraseña debe tener al menos 8 caracteres'
                        );
                    }
                }

                $cambioUsuario = $newUsername !== '' && $newUsername !== (string)$user['username'];

                if ($cambioUsuario) {
                    $this->users->setUsername($uid, $newUsername);
                    Auth::setUsername($newUsername);
                    $this->flash('ok', 'Usuario actualizado.');
                }
                if ($cambioClave) {
                    $this->users->setPassword($uid, $new);
                    Auth::refreshPasswordStamp();
                    $this->flash('ok', 'Contraseña actualizada. Las demás sesiones se han cerrado.');
                }
                if (!$cambioUsuario && !$cambioClave) {
                    $this->flash('ok', 'No había cambios que guardar.');
                }

                $this->redirect('/perfil');
            } catch (InvalidArgumentException $e) {
                $error = $e->getMessage();
            }

            $user = $this->users->findById($uid) ?? $user;
        }

        $this->render('Perfil y contraseña', 'perfil', [
            'active' => 'profile',
            'user' => $user,
            'values' => $values,
            'error' => $error,
            'csrf' => Auth::csrfToken(),
        ]);
    }

    // -------------------------------------------------------------- jobs --

    private function jobForm(string $method, ?int $id): void
    {
        $job = null;
        if ($id !== null) {
            $job = $this->jobs->getJob($id);
            if ($job === null) {
                $this->notFound();
                return;
            }
        }

        $error = '';
        $values = $job ?? [
            'name' => '', 'cron_expr' => '', 'command' => '',
            'timeout_sec' => 3600, 'comment' => '', 'enabled' => 1,
        ];

        if ($method === 'POST') {
            $this->requireCsrf();

            $values = [
                'name' => trim((string)($_POST['name'] ?? '')),
                'cron_expr' => trim((string)($_POST['cron_expr'] ?? '')),
                'command' => trim((string)($_POST['command'] ?? '')),
                'timeout_sec' => (int)($_POST['timeout_sec'] ?? 0),
                'comment' => trim((string)($_POST['comment'] ?? '')),
                'enabled' => empty($_POST['enabled']) ? 0 : 1,
            ];

            try {
                $data = $values;
                if ($id !== null) {
                    $data['id'] = $id;
                }
                $this->jobs->saveJob($data);
                $this->flash('ok', $id === null ? 'Tarea creada.' : "Tarea #{$id} actualizada.");
                $this->redirect('/');
            } catch (InvalidArgumentException $e) {
                $error = $e->getMessage();
            }
        }

        $this->render($id === null ? 'Nueva tarea' : 'Editar tarea', 'job_form', [
            'active' => 'jobs',
            'job' => $job,
            'values' => $values,
            'error' => $error,
            'csrf' => Auth::csrfToken(),
        ]);
    }

    private function jobToggle(int $id): void
    {
        $this->requireCsrf();

        $job = $this->jobs->getJob($id);
        if ($job === null) {
            $this->notFound();
            return;
        }

        $job['enabled'] = ((int)$job['enabled'] === 1) ? 0 : 1;
        $this->jobs->saveJob($job);
        $this->flash('ok', ((int)$job['enabled'] === 1) ? 'Tarea activada.' : 'Tarea pausada.');
        $this->redirect('/');
    }

    private function jobDelete(int $id): void
    {
        $this->requireCsrf();

        if (!$this->jobs->deleteJob($id)) {
            $this->notFound();
            return;
        }

        $this->flash('ok', "Tarea #{$id} eliminada.");
        $this->redirect('/');
    }

    // ---------------------------------------------------------- actualizaciones --

    private function updatesPage(): void
    {
        $forzar = isset($_GET['refresh']);
        $check = $this->updater->check($forzar);
        $instalada = $this->updater->installedVersion();
        $release = $check['release'];

        $alDia = $release !== null
            && version_compare($instalada, (string)$release['version'], '>=');

        $this->render('Actualizaciones', 'updates', [
            'active' => 'updates',
            'instalada' => $instalada,
            'release' => $release,
            'error' => $check['error'],
            'cacheada' => $check['cached'],
            'comprobada' => $check['checkedAt'],
            'alDia' => $alDia,
            'repo' => $this->updater->repo(),
            'csrf' => Auth::csrfToken(),
        ]);
    }

    // ------------------------------------------------------------ helpers --

    private function stripBasePath(string $path): string
    {
        global $CRONPANEL_CONFIG;

        $base = rtrim((string)($CRONPANEL_CONFIG['base_path'] ?? ''), '/');
        if ($base !== '' && str_starts_with($path, $base)) {
            $path = substr($path, strlen($base));
        }

        return $path === '' ? '/' : $path;
    }

    /** @param array<string, mixed> $data */
    private function render(string $title, string $view, array $data = []): void
    {
        $flashes = $this->pullFlashes();
        $data['flashes'] = $flashes;
        $content = $this->capture($view, $data);

        $this->renderLayout($title, $content, (string)($data['active'] ?? ''), $flashes);
    }

    private function renderStandalone(string $view, array $data = []): void
    {
        echo $this->capture($view, $data);
    }

    /** @param array<string, mixed> $data */
    private function capture(string $view, array $data): string
    {
        $file = CRONPANEL_ROOT . '/views/' . $view . '.php';
        if (!is_file($file)) {
            http_response_code(500);
            return '<p>Falta la vista ' . e($view) . '.</p>';
        }

        require_once CRONPANEL_ROOT . '/views/icons.php';

        $title = (string)($data['title'] ?? '');
        $csrf = Auth::csrfToken();
        $appName = (string)($GLOBALS['CRONPANEL_CONFIG']['app_name'] ?? 'Cron Scheduler');

        extract($data, EXTR_SKIP);
        ob_start();
        require $file;

        return (string)ob_get_clean();
    }

    /**
     * @param array<int, array{type:string,message:string}> $flashes
     */
    private function renderLayout(string $title, string $content, string $active, array $flashes): void
    {
        global $CRONPANEL_CONFIG;

        $appName = (string)($CRONPANEL_CONFIG['app_name'] ?? 'Cron Scheduler');
        $version = defined('CRONPANEL_VERSION') ? CRONPANEL_VERSION : '';
        $user = Auth::user();
        $csrf = Auth::csrfToken();

        require CRONPANEL_ROOT . '/views/layout.php';
    }

    private function flash(string $type, string $message): void
    {
        $_SESSION['cronpanel_flash'][] = ['type' => $type, 'message' => $message];
    }

    /** @return array<int, array{type:string,message:string}> */
    private function pullFlashes(): array
    {
        $flashes = $_SESSION['cronpanel_flash'] ?? [];
        unset($_SESSION['cronpanel_flash']);

        return is_array($flashes) ? $flashes : [];
    }

    private function requireCsrf(): void
    {
        if (!Auth::checkCsrf()) {
            http_response_code(400);
            echo 'Petición no válida (CSRF).';
            exit;
        }
    }

    private function redirect(string $path): void
    {
        header('Location: ' . url($path), true, 302);
        exit;
    }

    private function notFound(): void
    {
        http_response_code(404);
        $this->render('No encontrado', 'error', [
            'active' => '',
            'mensaje' => 'La página que buscas no existe.',
            'csrf' => Auth::csrfToken(),
        ]);
    }
}
