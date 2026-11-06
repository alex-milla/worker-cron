<?php
declare(strict_types=1);

/**
 * Página de error (404).
 * Variables: $mensaje
 */
?>
<section class="card">
    <h2>No encontrado</h2>
    <p class="muted"><?= e((string)($mensaje ?? 'La página que buscas no existe.')) ?></p>
    <div class="form-actions">
        <a class="btn" href="<?= e(url('/')) ?>">Volver al dashboard</a>
    </div>
</section>
