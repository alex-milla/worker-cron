<?php
declare(strict_types=1);

/**
 * Perfil: usuario y contraseña.
 * Variables: $user, $values, $error, $csrf
 */
?>
<section class="card card-form">
    <h2>Perfil y contraseña</h2>

    <?php if (!empty($error)): ?>
        <div class="alert-err"><?= e($error) ?></div>
    <?php endif; ?>

    <p class="muted">
        Último acceso: <?= e((string)($user['last_login_at'] ?? '—')) ?>
        · cuenta creada: <?= e((string)($user['created_at'] ?? '—')) ?>
        <?php if (!empty($user['password_changed_at'])): ?>
            · contraseña cambiada: <?= e((string)$user['password_changed_at']) ?>
        <?php endif; ?>
    </p>

    <form method="post" action="<?= e(url('/perfil')) ?>">
        <input type="hidden" name="csrf" value="<?= e($csrf) ?>">

        <div class="field">
            <label for="username">Nombre de usuario</label>
            <input id="username" name="username" type="text" required minlength="3"
                   maxlength="64" autocomplete="username"
                   value="<?= e((string)($values['username'] ?? '')) ?>">
            <div class="helper">Con esto entrarás la próxima vez.</div>
        </div>

        <div class="field">
            <label for="current_password">Contraseña actual</label>
            <input id="current_password" name="current_password" type="password"
                   required autocomplete="current-password">
            <div class="helper">Necesaria para guardar cualquier cambio.</div>
        </div>

        <div class="grid-2">
            <div class="field">
                <label for="new_password">Nueva contraseña</label>
                <input id="new_password" name="new_password" type="password"
                       minlength="8" autocomplete="new-password">
            </div>
            <div class="field">
                <label for="new_password2">Repite la nueva contraseña</label>
                <input id="new_password2" name="new_password2" type="password"
                       minlength="8" autocomplete="new-password">
            </div>
        </div>
        <div class="helper">
            Déjalas vacías si solo quieres cambiar el nombre de usuario.
            Mínimo 8 caracteres. Al cambiarla se cierran las demás sesiones.
        </div>

        <div class="form-actions">
            <a class="btn btn-cancel" href="<?= e(url('/')) ?>">Cancelar</a>
            <button type="submit" class="btn">Guardar</button>
        </div>
    </form>
</section>
