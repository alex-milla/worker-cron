<?php
declare(strict_types=1);

/**
 * Actualizaciones del panel: misma pantalla que la del worker, pero
 * sincronizando sobre public_html/ en vez de worker/.
 *
 * Variables: $instalada, $release, $result, $error, $tokenSet, $backups, $repo, $csrf
 */

$remota = $release !== null ? (string)$release['version'] : null;
$alDia = $remota !== null && version_compare($instalada, $remota, '>=');
?>
<section class="card">
    <h2>Actualizaciones desde GitHub</h2>

    <?php if (!empty($error)): ?>
        <div class="alert-err"><?= e($error) ?></div>
    <?php endif; ?>

    <?php if (is_array($result)): ?>
        <?php if (!empty($result['updated'])): ?>
            <div class="alert-ok">
                Actualizado a <strong>v<?= e((string)$result['remote']) ?></strong>
                (copiados: <?= e((string)$result['copied']) ?>
                · borrados: <?= e((string)$result['deleted']) ?>
                · sin cambios: <?= e((string)$result['skipped']) ?>
                · errores: <?= e((string)$result['errors']) ?>)
                <?php if (!empty($result['error_detail'])): ?>
                    <br><small>
                    <?php foreach ((array)$result['error_detail'] as $i => $detalle): ?>
                        <?= $i > 0 ? '<br>' : '' ?><?= e((string)$detalle) ?>
                    <?php endforeach; ?>
                    </small>
                <?php endif; ?>
                <br>Backup previo: <code class="mono"><?= e((string)($result['backup'] ?? '')) ?></code>
                <br><strong>Recarga la página</strong> para cargar el código nuevo.
            </div>
        <?php else: ?>
            <div class="alert-ok"><?= e((string)($result['message'] ?? 'Sin cambios')) ?></div>
        <?php endif; ?>
    <?php endif; ?>

    <table>
        <thead><tr><th>Instalada</th><th>Última en GitHub</th><th>Repositorio</th></tr></thead>
        <tbody>
        <tr>
            <td><strong>v<?= e($instalada) ?></strong></td>
            <td>
                <?php if ($remota !== null): ?>
                    v<?= e($remota) ?>
                    <?php if ($alDia): ?>
                        <span class="pill ok">al día</span>
                    <?php else: ?>
                        <span class="pill warn">nueva</span>
                    <?php endif; ?>
                <?php else: ?>
                    <span class="muted">sin releases publicadas</span>
                <?php endif; ?>
            </td>
            <td class="mono"><?= e($repo) ?></td>
        </tr>
        </tbody>
    </table>

    <?php if ($release !== null && !empty($release['notes'])): ?>
        <details style="margin-top:12px">
            <summary class="muted">Notas de la release</summary>
            <pre class="output output-wide"><?= e((string)$release['notes']) ?></pre>
        </details>
    <?php endif; ?>

    <div class="form-actions">
        <form method="post" action="<?= e(url('/updates')) ?>"
              data-confirm="¿Instalar v<?= e((string)$remota) ?>? Se hará backup antes.">
            <input type="hidden" name="csrf" value="<?= e($csrf) ?>">
            <input type="hidden" name="action" value="install">
            <button type="submit" class="btn" <?= $remota === null ? 'disabled' : '' ?>>Instalar última versión</button>
        </form>
        <form method="post" action="<?= e(url('/updates')) ?>"
              data-confirm="¿Reinstalar v<?= e((string)($remota ?? $instalada)) ?>? Se hará backup antes.">
            <input type="hidden" name="csrf" value="<?= e($csrf) ?>">
            <input type="hidden" name="action" value="reinstall">
            <button type="submit" class="btn btn-cancel">Reinstalar (forzar)</button>
        </form>
    </div>

    <p class="helper" style="margin-top:1rem">
        Se descarga la release de GitHub y se sincroniza <code>public_html/</code> por
        manifiesto SHA-256. Nunca se toca <code>config/config.php</code> ni <code>data/</code>.
        El worker del LXC se actualiza aparte desde su propia GUI.
    </p>
</section>

<section class="card">
    <h2>Token de GitHub</h2>
    <p class="muted">Opcional: solo hace falta si el repositorio pasa a privado o para
        saltarte el límite de peticiones de la API. Se guarda en la BD local del panel
        (nunca se envía al navegador una vez guardado).</p>

    <form method="post" action="<?= e(url('/updates')) ?>" style="max-width:480px">
        <input type="hidden" name="csrf" value="<?= e($csrf) ?>">
        <input type="hidden" name="action" value="save_token">
        <div class="field">
            <label for="github_token">Token personal (fine-grained PAT)</label>
            <input id="github_token" type="password" name="github_token"
                   autocomplete="off"
                   placeholder="<?= $tokenSet ? '•••••••• (ya configurado — deja vacío para mantener)' : 'github_pat_...' ?>">
            <div class="helper">
                <?php if ($tokenSet): ?>
                    Hay un token configurado: escribe uno nuevo para sustituirlo o envíalo
                    vacío para eliminarlo.
                <?php else: ?>
                    Sin token: solo funciona con repositorio público (60 peticiones/hora).
                <?php endif; ?>
            </div>
        </div>
        <div class="form-actions">
            <button type="submit" class="btn">Guardar token</button>
        </div>
    </form>
</section>

<section class="card">
    <h2>Backups</h2>
    <?php if (!empty($backups)): ?>
        <table>
            <thead><tr><th>Backup</th><th>Acción</th></tr></thead>
            <tbody>
            <?php foreach (array_slice($backups, 0, 10) as $backup): ?>
                <tr>
                    <td class="mono"><?= e($backup) ?></td>
                    <td>
                        <form method="post" action="<?= e(url('/updates')) ?>" style="display:inline"
                              data-confirm="¿Restaurar <?= e($backup) ?>? Se hará backup previo del estado actual.">
                            <input type="hidden" name="csrf" value="<?= e($csrf) ?>">
                            <input type="hidden" name="action" value="restore">
                            <input type="hidden" name="backup" value="<?= e($backup) ?>">
                            <button type="submit">Restaurar</button>
                        </form>
                    </td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    <?php else: ?>
        <p class="muted">Sin backups todavía: se crean automáticamente antes de instalar
            o restaurar.</p>
    <?php endif; ?>
</section>
