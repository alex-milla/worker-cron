<?php
declare(strict_types=1);

/**
 * Alta / edición de una tarea.
 * Variables: $job (fila o null), $values, $error, $csrf
 */

$esEdicion = !empty($job);
$accion = $esEdicion
    ? url('/jobs/' . (int)$job['id'] . '/edit')
    : url('/jobs/new');
?>
<section class="card card-form">
    <h2><?= $esEdicion ? 'Editar tarea' : 'Nueva tarea' ?></h2>

    <?php if (!empty($error)): ?>
        <div class="alert-err"><?= e($error) ?></div>
    <?php endif; ?>

    <form method="post" action="<?= e($accion) ?>">
        <input type="hidden" name="csrf" value="<?= e($csrf) ?>">

        <div class="field">
            <label for="name">Nombre</label>
            <input id="name" name="name" type="text" required autofocus
                   value="<?= e((string)($values['name'] ?? '')) ?>"
                   placeholder="Backup diario de BD">
        </div>

        <div class="grid-2">
            <div class="field">
                <label for="cron_expr">Expresión cron (5 campos)</label>
                <input id="cron_expr" name="cron_expr" type="text" required
                       value="<?= e((string)($values['cron_expr'] ?? '')) ?>"
                       placeholder="30 3 * * *">
                <div class="helper">min · hora · día del mes · mes · día de semana</div>
            </div>
            <div class="field">
                <label for="timeout_sec">Timeout (segundos, 0 = sin límite)</label>
                <input id="timeout_sec" name="timeout_sec" type="number" min="0"
                       value="<?= e((string)($values['timeout_sec'] ?? 3600)) ?>">
                <div class="helper">Si se supera, el worker lo marca como <code>timeout</code>.</div>
            </div>
        </div>

        <div class="field">
            <label for="command">Comando</label>
            <textarea id="command" name="command" required
                      placeholder="tar -czf /backups/$(date +\%F).tar.gz /var/lib/mysql"><?= e((string)($values['command'] ?? '')) ?></textarea>
            <div class="helper">Se ejecuta en el <strong>worker</strong> (LXC), no en el hosting.</div>
        </div>

        <div class="field">
            <label for="comment">Comentario (opcional)</label>
            <input id="comment" name="comment" type="text"
                   value="<?= e((string)($values['comment'] ?? '')) ?>">
        </div>

        <div class="field field-check">
            <label>
                <input type="checkbox" name="enabled" value="1"
                    <?= !empty($values['enabled']) ? 'checked' : '' ?>>
                Activa
            </label>
            <div class="helper">El worker solo sincroniza las tareas activas.</div>
        </div>

        <div class="form-actions">
            <a class="btn btn-cancel" href="<?= e(url('/')) ?>">Cancelar</a>
            <button type="submit" class="btn">Guardar</button>
        </div>
    </form>
</section>
