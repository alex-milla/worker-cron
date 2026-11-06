<?php
declare(strict_types=1);

/**
 * Dashboard: tareas programadas + últimas ejecuciones.
 * Variables: $jobs, $runs, $revision, $csrf
 */
?>
<section class="card">
    <div class="toolbar">
        <h2>Tareas programadas</h2>
        <a class="btn" href="<?= e(url('/jobs/new')) ?>"><?= icon('plus') ?>Nueva tarea</a>
    </div>

    <?php if (!empty($jobs)): ?>
        <table>
            <thead>
            <tr>
                <th>#</th><th>Nombre</th><th>Cron</th><th>Timeout</th>
                <th>Estado</th><th>Acciones</th>
            </tr>
            </thead>
            <tbody>
            <?php foreach ($jobs as $job): ?>
                <tr>
                    <td><?= e((string)$job['id']) ?></td>
                    <td>
                        <?= e((string)$job['name']) ?>
                        <?php if (!empty($job['comment'])): ?>
                            <div class="muted"><?= e((string)$job['comment']) ?></div>
                        <?php endif; ?>
                    </td>
                    <td><code class="mono"><?= e((string)$job['cron_expr']) ?></code></td>
                    <td class="muted"><?= e((string)$job['timeout_sec']) ?> s</td>
                    <td>
                        <?php if ((int)$job['enabled'] === 1): ?>
                            <span class="pill ok">activa</span>
                        <?php else: ?>
                            <span class="pill off">pausada</span>
                        <?php endif; ?>
                    </td>
                    <td class="row-actions">
                        <a href="<?= e(url('/jobs/' . (int)$job['id'] . '/edit')) ?>"><?= icon('edit', 14) ?>Editar</a>
                        <form method="post" action="<?= e(url('/jobs/' . (int)$job['id'] . '/toggle')) ?>">
                            <input type="hidden" name="csrf" value="<?= e($csrf) ?>">
                            <button type="submit">
                                <?= (int)$job['enabled'] === 1 ? icon('pause', 14) . 'Pausar' : icon('play', 14) . 'Activar' ?>
                            </button>
                        </form>
                        <form method="post" action="<?= e(url('/jobs/' . (int)$job['id'] . '/delete')) ?>"
                              data-confirm="¿Eliminar «<?= e((string)$job['name']) ?>» y todas sus ejecuciones?">
                            <input type="hidden" name="csrf" value="<?= e($csrf) ?>">
                            <button type="submit" class="danger"><?= icon('trash', 14) ?>Borrar</button>
                        </form>
                    </td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    <?php else: ?>
        <p class="muted">Todavía no hay tareas. Crea la primera con «Nueva tarea».</p>
    <?php endif; ?>
</section>

<section class="card">
    <h2>Últimas ejecuciones</h2>
    <?php if (!empty($runs)): ?>
        <table>
            <thead>
            <tr><th>Tarea</th><th>Inicio</th><th>Fin</th><th>Estado</th><th>Exit</th></tr>
            </thead>
            <tbody>
            <?php foreach ($runs as $run): ?>
                <tr>
                    <td><?= e((string)($run['job_name'] ?? ('#' . $run['job_id']))) ?></td>
                    <td class="muted"><?= e((string)$run['started_at']) ?></td>
                    <td class="muted"><?= e((string)($run['finished_at'] ?? '—')) ?></td>
                    <td><?= status_pill($run['status'] ?? null) ?></td>
                    <td><?= $run['exit_code'] === null ? '—' : e((string)$run['exit_code']) ?></td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    <?php else: ?>
        <p class="muted">Sin ejecuciones registradas todavía. Aparecerán cuando el worker
            reporte resultados (fase 4).</p>
    <?php endif; ?>
</section>

<p class="muted mono">revisión: <?= e((string)($revision ?? 0)) ?></p>
