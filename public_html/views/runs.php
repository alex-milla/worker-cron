<?php
declare(strict_types=1);

/**
 * Historial de ejecuciones (las escribe el worker vía API, fase 4).
 * Variables: $runs
 */
?>
<section class="card">
    <div class="toolbar">
        <h2>Ejecuciones</h2>
        <span class="muted">últimas <?= e((string)count($runs ?? [])) ?></span>
    </div>

    <?php if (!empty($runs)): ?>
        <table>
            <thead>
            <tr>
                <th>#</th><th>Tarea</th><th>Inicio</th><th>Fin</th>
                <th>Estado</th><th>Exit</th><th>Salida</th>
            </tr>
            </thead>
            <tbody>
            <?php foreach ($runs as $run): ?>
                <tr>
                    <td><?= e((string)$run['id']) ?></td>
                    <td><?= e((string)($run['job_name'] ?? ('#' . $run['job_id']))) ?></td>
                    <td class="muted"><?= e((string)$run['started_at']) ?></td>
                    <td class="muted"><?= e((string)($run['finished_at'] ?? '—')) ?></td>
                    <td><?= status_pill($run['status'] ?? null) ?></td>
                    <td><?= $run['exit_code'] === null ? '—' : e((string)$run['exit_code']) ?></td>
                    <td>
                        <?php $salida = trim((string)($run['output'] ?? '')); ?>
                        <?php if ($salida === ''): ?>
                            <span class="muted">—</span>
                        <?php else: ?>
                            <details>
                                <summary class="muted">ver</summary>
                                <pre class="output"><?= e($salida) ?></pre>
                            </details>
                        <?php endif; ?>
                    </td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    <?php else: ?>
        <p class="muted">Sin ejecuciones registradas todavía. El worker aún no reporta
            resultados (fase 4).</p>
    <?php endif; ?>
</section>
