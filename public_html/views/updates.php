<?php
declare(strict_types=1);

/**
 * Actualizaciones del panel: SOLO informativa.
 * Variables: $instalada, $release, $error, $cacheada, $comprobada, $alDia, $repo
 */
$hayNueva = $release !== null && !$alDia;
?>
<section class="card">
    <div class="toolbar">
        <h2>Versión del panel</h2>
        <a class="btn btn-cancel" href="<?= e(url('/updates?refresh=1')) ?>">Comprobar ahora</a>
    </div>

    <table>
        <thead><tr><th>Instalada</th><th>Última en GitHub</th><th>Repositorio</th></tr></thead>
        <tbody>
        <tr>
            <td><strong>v<?= e($instalada) ?></strong></td>
            <td>
                <?php if ($release !== null): ?>
                    v<?= e((string)$release['version']) ?>
                    <?php if ($alDia): ?>
                        <span class="pill ok">al día</span>
                    <?php else: ?>
                        <span class="pill warn">nueva</span>
                    <?php endif; ?>
                <?php elseif ($error !== null): ?>
                    <span class="muted">no se pudo consultar</span>
                <?php else: ?>
                    <span class="muted">sin releases publicadas</span>
                <?php endif; ?>
            </td>
            <td class="mono"><?= e($repo) ?></td>
        </tr>
        </tbody>
    </table>

    <?php if ($error !== null): ?>
        <div class="alert-err" style="margin-top:1rem">No se pudo consultar GitHub: <?= e($error) ?></div>
    <?php endif; ?>

    <?php if ($cacheada && $comprobada !== null): ?>
        <p class="muted helper" style="margin-top:.75rem">
            Datos en caché de <?= e(date('d/m/Y H:i', (int)$comprobada)) ?> (30 min).
            «Comprobar ahora» fuerza la consulta.
        </p>
    <?php endif; ?>
</section>

<?php if ($hayNueva): ?>
    <section class="card">
        <h2>Hay una versión nueva: v<?= e((string)$release['version']) ?></h2>
        <p class="muted">
            El panel <strong>no se actualiza solo</strong>: se despliega subiendo ficheros al
            hosting. Descarga la release y sube <code>public_html/</code>.
        </p>

        <div class="form-actions" style="justify-content:flex-start">
            <a class="btn" href="<?= e((string)($release['html_url'] ?? '#')) ?>"
               target="_blank" rel="noopener">Ver release en GitHub</a>
            <a class="btn btn-cancel" href="<?= e((string)($release['zip_url'] ?? '#')) ?>"
               target="_blank" rel="noopener">Descargar ZIP</a>
        </div>

        <div class="helper" style="margin-top:1rem">
            <strong>Qué subir:</strong> todo <code>public_html/</code> (nunca
            <code>config/config.php</code> ni <code>data/</code>). El worker del LXC se
            actualiza aparte desde su propia GUI.
        </div>

        <?php if (!empty($release['notes'])): ?>
            <details style="margin-top:1rem">
                <summary class="muted">Notas de la release</summary>
                <pre class="output output-wide"><?= e((string)$release['notes']) ?></pre>
            </details>
        <?php endif; ?>
    </section>
<?php elseif ($release !== null && $alDia): ?>
    <section class="card">
        <p class="muted">Estás en la última versión publicada. No hay nada que subir.</p>
    </section>
<?php endif; ?>

<section class="card">
    <h2>Cómo se actualiza cada mitad</h2>
    <table>
        <thead><tr><th>Mitad</th><th>Actualización</th></tr></thead>
        <tbody>
        <tr>
            <td><strong>Worker</strong> (LXC)</td>
            <td>Desde su GUI: <em>Actualizaciones → Instalar última versión</em>.
                Hace backup y reinicia los servicios.</td>
        </tr>
        <tr>
            <td><strong>Panel</strong> (hosting)</td>
            <td>Subir <code>public_html/</code> por FTP/SSH. Esta pantalla solo avisa.</td>
        </tr>
        </tbody>
    </table>
</section>
