<#
    Test E2E del panel (PowerShell 7). Solo desarrollo: vive fuera de public_html.

        pwsh -File tools/panel_e2e.ps1

    Crea una config temporal con BD en %TEMP%, arranca el servidor embebido de PHP
    con el mismo enrutado que el .htaccess y comprueba login, CSRF, CRUD y rutas
    protegidas. No toca config/config.php ni data/ del proyecto.
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$port = 8099
$base = "http://127.0.0.1:$port"
$tmp = Join-Path $env:TEMP 'cronpanel_e2e'
$fallos = 0

function Check([string]$label, [bool]$ok, [string]$detalle = '') {
    if ($ok) { Write-Output "OK    $label" }
    else { $script:fallos++; Write-Output "FALLO $label  $detalle" }
}

function Get-Csrf([string]$html) {
    return [regex]::Match($html, 'name="csrf" value="([^"]+)"').Groups[1].Value
}

if (-not (Get-Command php -ErrorAction SilentlyContinue)) {
    Write-Output 'FALLO php no está en el PATH'
    exit 1
}

# --- config temporal ---
Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$hash = (& php -r "echo password_hash('test1234', PASSWORD_DEFAULT);").Trim()
$dbPath = ($tmp -replace '\\', '/') + '/panel.sqlite'
$cfg = @"
<?php
return [
    'db_path' => '$dbPath',
    'admin_user' => 'admin',
    'admin_pass_hash' => '$hash',
    'api_token' => 'test-token',
    'api_version' => 'v1',
    'base_path' => '',
    'app_name' => 'Cron Scheduler E2E',
    'timezone' => 'Europe/Madrid',
    'debug' => false,
];
"@
[IO.File]::WriteAllText("$tmp/config.php", $cfg, (New-Object Text.UTF8Encoding $false))
$env:CRONPANEL_CONFIG_FILE = "$tmp/config.php"

$srv = Start-Process -FilePath 'php' -PassThru -WindowStyle Hidden `
    -ArgumentList '-S', "127.0.0.1:$port", '-t', 'public_html', 'tools/dev_server.php' `
    -WorkingDirectory $root

try {
    $listo = $false
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $null = Invoke-WebRequest -Uri "$base/login" -TimeoutSec 2 -SkipHttpErrorCheck
            $listo = $true
            break
        } catch { Start-Sleep -Milliseconds 200 }
    }
    Check 'servidor arriba' $listo
    if (-not $listo) { throw 'el servidor no arrancó' }

    # 1. login
    $s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $r = Invoke-WebRequest -Uri "$base/login" -WebSession $s
    Check 'GET /login = 200' ($r.StatusCode -eq 200)
    $csrf = Get-Csrf $r.Content
    Check 'login trae csrf' ($csrf.Length -gt 0)

    # 2. guard
    $r = Invoke-WebRequest -Uri "$base/" -MaximumRedirection 5 `
        -WebSession (New-Object Microsoft.PowerShell.Commands.WebRequestSession)
    Check 'sin sesión acaba en /login' ($r.Content -match 'Iniciar sesión')

    # 3. CSRF obligatorio
    $r = Invoke-WebRequest -Uri "$base/login" -Method Post -WebSession $s `
        -Body @{ username = 'admin'; password = 'test1234' } `
        -SkipHttpErrorCheck -MaximumRedirection 0 -ErrorAction SilentlyContinue
    Check 'login sin CSRF = 400' ($r.StatusCode -eq 400) "status=$($r.StatusCode)"

    # 4. credenciales malas
    $r = Invoke-WebRequest -Uri "$base/login" -Method Post -WebSession $s `
        -Body @{ username = 'admin'; password = 'mala'; csrf = $csrf }
    Check 'login malo muestra error' ($r.Content -match 'Credenciales inválidas')

    # 5. login correcto
    $r = Invoke-WebRequest -Uri "$base/login" -Method Post -WebSession $s -MaximumRedirection 5 `
        -Body @{ username = 'admin'; password = 'test1234'; csrf = $csrf }
    Check 'login correcto -> dashboard' ($r.StatusCode -eq 200 -and $r.Content -match 'Tareas programadas')
    Check 'dashboard con shell (sidebar)' ($r.Content -match 'app-sidebar')
    Check 'dashboard sin errores PHP' (-not ($r.Content -match 'Warning:|Fatal error|Notice:'))
    $csrf = Get-Csrf $r.Content
    Check 'dashboard trae csrf' ($csrf.Length -gt 0)

    # 6. crear tarea
    $r = Invoke-WebRequest -Uri "$base/jobs/new" -Method Post -WebSession $s `
        -MaximumRedirection 0 -SkipHttpErrorCheck -ErrorAction SilentlyContinue -Body @{
            name = 'Backup diario'; cron_expr = '30 3 * * *'
            command = 'tar -czf /tmp/b.tgz /data'; timeout_sec = '600'
            comment = 'prueba'; enabled = '1'; csrf = $csrf
        }
    Check 'POST /jobs/new = 302' ($r.StatusCode -eq 302) "status=$($r.StatusCode)"
    $dash = (Invoke-WebRequest -Uri "$base/" -WebSession $s).Content
    Check 'la tarea aparece en el dashboard' ($dash -match 'Backup diario')
    Check 'flash de creación visible' ($dash -match 'Tarea creada')
    $csrf = Get-Csrf $dash

    # 7. editar
    $r = Invoke-WebRequest -Uri "$base/jobs/1/edit" -WebSession $s
    Check 'GET /jobs/1/edit = 200' ($r.StatusCode -eq 200)
    Check 'formulario con los datos' ($r.Content -match 'Backup diario')

    # 8. cron inválido
    $r = Invoke-WebRequest -Uri "$base/jobs/1/edit" -Method Post -WebSession $s -Body @{
        name = 'Backup diario'; cron_expr = '99 99 * * *'; command = 'x'
        timeout_sec = '1'; enabled = '1'; csrf = $csrf
    }
    Check 'cron inválido rechazado' ($r.StatusCode -eq 200 -and $r.Content -match 'cron inválida')
    $dash = (Invoke-WebRequest -Uri "$base/" -WebSession $s).Content
    Check 'la tarea no cambió' ($dash -match '30 3 \* \* \*')

    # 8b. API v1 (la que consumirá el worker)
    $api = @{ Authorization = 'Bearer test-token' }
    $json = 'application/json'

    $r = Invoke-WebRequest -Uri "$base/api/v1/version" -SkipHttpErrorCheck
    Check 'API sin token = 401' ($r.StatusCode -eq 401)

    $r = Invoke-WebRequest -Uri "$base/api/v1/version" -Headers @{ Authorization = 'Bearer malo' } -SkipHttpErrorCheck
    Check 'API token malo = 401' ($r.StatusCode -eq 401)

    $r = Invoke-WebRequest -Uri "$base/api/v1/version" -Headers $api
    Check 'API version = 200' ($r.StatusCode -eq 200)
    Check 'X-Revision en la respuesta' ($r.Headers.ContainsKey('X-Revision'))
    $rev = ($r.Content | ConvertFrom-Json).revision
    Check 'revision es un número' ($rev -is [int] -or $rev -is [long])

    $r = Invoke-WebRequest -Uri "$base/api/v1/jobs" -Headers $api
    $payload = $r.Content | ConvertFrom-Json
    Check 'API jobs = 200' ($r.StatusCode -eq 200)
    Check 'API jobs incluye la tarea' ($payload.count -ge 1 -and $payload.jobs[0].name -eq 'Backup diario')
    Check 'API jobs trae el comando' ($payload.jobs[0].command -match 'tar')
    Check 'API jobs no filtra hashes' (-not ($r.Content -match 'pass_hash'))

    $body = @{
        job_id = 1; started_at = '2026-11-06T23:00:00'; finished_at = '2026-11-06T23:00:05'
        status = 'ok'; exit_code = 0; output = 'linea de salida'
    } | ConvertTo-Json
    $r = Invoke-WebRequest -Uri "$base/api/v1/results" -Method Post -Headers $api -ContentType $json -Body $body -SkipHttpErrorCheck
    Check 'API results = 201' ($r.StatusCode -eq 201) "status=$($r.StatusCode)"

    $r = Invoke-WebRequest -Uri "$base/runs" -WebSession $s
    Check 'la ejecución aparece en /runs' ($r.Content -match 'linea de salida')

    $r = Invoke-WebRequest -Uri "$base/api/v1/results" -Method Post -Headers $api -ContentType $json -SkipHttpErrorCheck `
        -Body '{"job_id":999,"started_at":"2026-11-06T23:00:00","status":"ok"}'
    Check 'API results job inexistente = 404' ($r.StatusCode -eq 404)

    $r = Invoke-WebRequest -Uri "$base/api/v1/results" -Method Post -Headers $api -ContentType $json -SkipHttpErrorCheck -Body '{}'
    Check 'API results sin datos = 400' ($r.StatusCode -eq 400)

    $r = Invoke-WebRequest -Uri "$base/api/v1/results" -Method Post -Headers $api -ContentType $json -SkipHttpErrorCheck -Body 'no-es-json'
    Check 'API results JSON inválido = 400' ($r.StatusCode -eq 400)

    $r = Invoke-WebRequest -Uri "$base/api/v1/heartbeat" -Method Post -Headers $api -ContentType $json `
        -Body (@{ name = 'lxc-e2e'; revision = $rev } | ConvertTo-Json)
    Check 'API heartbeat = 200' ($r.StatusCode -eq 200)

    $r = Invoke-WebRequest -Uri "$base/api/v1/nope" -Headers $api -SkipHttpErrorCheck
    Check 'API ruta desconocida = 404' ($r.StatusCode -eq 404)

    $r = Invoke-WebRequest -Uri "$base/api/v1/version" -Method Post -Headers $api -SkipHttpErrorCheck
    Check 'API método no permitido = 405' ($r.StatusCode -eq 405)

    # 9. pausar
    $r = Invoke-WebRequest -Uri "$base/jobs/1/toggle" -Method Post -Body @{ csrf = $csrf } `
        -WebSession $s -MaximumRedirection 0 -SkipHttpErrorCheck -ErrorAction SilentlyContinue
    Check 'toggle = 302' ($r.StatusCode -eq 302)
    $dash = (Invoke-WebRequest -Uri "$base/" -WebSession $s).Content
    Check 'tarea pausada' ($dash -match 'pausada')

    # 10. 404
    $r = Invoke-WebRequest -Uri "$base/jobs/999/edit" -WebSession $s -SkipHttpErrorCheck
    Check 'job inexistente = 404' ($r.StatusCode -eq 404) "status=$($r.StatusCode)"

    # 11. ejecuciones
    $r = Invoke-WebRequest -Uri "$base/runs" -WebSession $s
    Check 'GET /runs = 200' ($r.StatusCode -eq 200)

    # 12. rutas protegidas
    foreach ($p in @('/src/Database.php', '/data/panel.sqlite', '/views/layout.php', '/config/config.php')) {
        $r = Invoke-WebRequest -Uri "$base$p" -SkipHttpErrorCheck
        Check "bloqueado $p = 403" ($r.StatusCode -eq 403) "status=$($r.StatusCode)"
    }

    # 13. estáticos
    $r = Invoke-WebRequest -Uri "$base/assets/css/app.css"
    Check 'CSS servido y con tokens' ($r.StatusCode -eq 200 -and $r.Content -match '(?m)^\s*--brand:\s*#f97316')

    # 14. borrar
    $r = Invoke-WebRequest -Uri "$base/jobs/1/delete" -Method Post -Body @{ csrf = $csrf } `
        -WebSession $s -MaximumRedirection 0 -SkipHttpErrorCheck -ErrorAction SilentlyContinue
    Check 'delete = 302' ($r.StatusCode -eq 302)
    $dash = (Invoke-WebRequest -Uri "$base/" -WebSession $s).Content
    Check 'dashboard vacío' ($dash -match 'Todavía no hay tareas')

    # 15. perfil
    $r = Invoke-WebRequest -Uri "$base/perfil" -WebSession $s
    Check 'GET /perfil = 200' ($r.StatusCode -eq 200)
    Check 'perfil en el sidebar' ($r.Content -match 'Perfil y contraseña')
    $csrf = Get-Csrf $r.Content

    # 15a. contraseña actual incorrecta
    $r = Invoke-WebRequest -Uri "$base/perfil" -Method Post -WebSession $s -Body @{
        username = 'admin'; current_password = 'mala'; csrf = $csrf
    }
    Check 'perfil: actual incorrecta' ($r.StatusCode -eq 200 -and $r.Content -match 'contraseña actual no es correcta')

    # 15b. segunda sesión (para probar la invalidación)
    $s2 = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $r = Invoke-WebRequest -Uri "$base/login" -WebSession $s2
    $csrf2 = Get-Csrf $r.Content
    $r = Invoke-WebRequest -Uri "$base/login" -Method Post -WebSession $s2 -MaximumRedirection 5 `
        -Body @{ username = 'admin'; password = 'test1234'; csrf = $csrf2 }
    Check 'segunda sesión abierta' ($r.Content -match 'Tareas programadas')

    # 15c. cambiar contraseña
    $r = Invoke-WebRequest -Uri "$base/perfil" -Method Post -WebSession $s -MaximumRedirection 5 -Body @{
        username = 'admin'; current_password = 'test1234'
        new_password = 'nueva-clave-9'; new_password2 = 'nueva-clave-9'; csrf = $csrf
    }
    Check 'contraseña cambiada' ($r.Content -match 'Contraseña actualizada')
    $csrf = Get-Csrf $r.Content

    # 15d. la otra sesión queda invalidada
    $r = Invoke-WebRequest -Uri "$base/" -WebSession $s2 -MaximumRedirection 5
    Check 'sesión paralela invalidada' ($r.Content -match 'Iniciar sesión')

    # 15e. cambiar usuario
    $r = Invoke-WebRequest -Uri "$base/perfil" -Method Post -WebSession $s -MaximumRedirection 5 -Body @{
        username = 'gestor'; current_password = 'nueva-clave-9'; csrf = $csrf
    }
    Check 'usuario cambiado' ($r.Content -match 'Usuario actualizado')
    Check 'el nombre nuevo sale en el shell' ($r.Content -match 'gestor')
    $csrf = Get-Csrf $r.Content

    # 16. logout y login con las credenciales nuevas
    $r = Invoke-WebRequest -Uri "$base/logout" -Method Post -Body @{ csrf = $csrf } `
        -WebSession $s -MaximumRedirection 5
    Check 'logout vuelve al login' ($r.Content -match 'Iniciar sesión')

    $s3 = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $r = Invoke-WebRequest -Uri "$base/login" -WebSession $s3
    $csrf3 = Get-Csrf $r.Content
    $r = Invoke-WebRequest -Uri "$base/login" -Method Post -WebSession $s3 -MaximumRedirection 5 `
        -Body @{ username = 'gestor'; password = 'nueva-clave-9'; csrf = $csrf3 }
    Check 'login con usuario y clave nuevos' ($r.Content -match 'Tareas programadas')

    $s4 = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $r = Invoke-WebRequest -Uri "$base/login" -WebSession $s4
    $csrf4 = Get-Csrf $r.Content
    $r = Invoke-WebRequest -Uri "$base/login" -Method Post -WebSession $s4 `
        -Body @{ username = 'admin'; password = 'test1234'; csrf = $csrf4 }
    Check 'las credenciales viejas ya no valen' ($r.Content -match 'Credenciales inválidas')
} catch {
    $fallos++
    Write-Output "EXCEPCIÓN: $($_.Exception.Message)"
} finally {
    if ($srv -and -not $srv.HasExited) { Stop-Process -Id $srv.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

Write-Output ''
if ($fallos -gt 0) {
    Write-Output "E2E PANEL: $fallos FALLO(S)"
    exit 1
}
Write-Output 'E2E PANEL: TODO OK'
