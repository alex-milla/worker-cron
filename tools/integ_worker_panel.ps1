<#
    Integración panel (PHP) <-> worker (Python).

        pwsh -File tools/integ_worker_panel.ps1

    Levanta el panel con el servidor embebido y una BD temporal, crea una
    tarea desde la GUI, ejecuta el ciclo real del worker (pull -> ejecutar ->
    reportar -> heartbeat) y comprueba que la ejecución llega a la BD del panel.

    No toca config/config.php ni data/ del proyecto.
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$port = 8098
$base = "http://127.0.0.1:$port"
$tmp = Join-Path $env:TEMP 'cronpanel_integ'
$fallos = 0

function Check([string]$label, [bool]$ok, [string]$detalle = '') {
    if ($ok) { Write-Output "OK    $label" }
    else { $script:fallos++; Write-Output "FALLO $label  $detalle" }
}

if (-not (Get-Command php -ErrorAction SilentlyContinue)) {
    Write-Output 'FALLO php no está en el PATH'; exit 1
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Output 'FALLO python no está en el PATH'; exit 1
}

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
    'api_token' => 'token-integracion',
    'api_version' => 'v1',
    'base_path' => '',
    'app_name' => 'Integración',
    'github_repo' => 'e2e/none',
    'github_api_base' => 'http://127.0.0.1:1',
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
        try { $null = Invoke-WebRequest -Uri "$base/login" -TimeoutSec 2 -SkipHttpErrorCheck; $listo = $true; break }
        catch { Start-Sleep -Milliseconds 200 }
    }
    Check 'panel arrancado' $listo
    if (-not $listo) { throw 'el panel no arrancó' }

    # 1. crear una tarea desde la GUI del panel
    $s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $r = Invoke-WebRequest -Uri "$base/login" -WebSession $s
    $csrf = [regex]::Match($r.Content, 'name="csrf" value="([^"]+)"').Groups[1].Value
    $r = Invoke-WebRequest -Uri "$base/login" -Method Post -WebSession $s -MaximumRedirection 5 `
        -Body @{ username = 'admin'; password = 'test1234'; csrf = $csrf }
    # el login regenera la sesión: hay que releer el CSRF
    $csrf = [regex]::Match($r.Content, 'name="csrf" value="([^"]+)"').Groups[1].Value
    $r = Invoke-WebRequest -Uri "$base/jobs/new" -Method Post -WebSession $s -MaximumRedirection 5 -Body @{
        name = 'Eco del worker'; cron_expr = '* * * * *'
        command = 'echo hola-desde-el-worker'; timeout_sec = '10'
        comment = 'integracion'; enabled = '1'; csrf = $csrf
    }
    Check 'tarea creada en el panel' ($r.Content -match 'Eco del worker')

    # 2. ciclo real del worker
    $env:PANEL_URL = $base
    $env:PANEL_TOKEN = 'token-integracion'
    $env:WORKER_DB = ($tmp -replace '\\', '/') + '/worker.sqlite'
    $env:REPO_ROOT = $root
    $py = @'
import os, sys
from pathlib import Path
sys.path.insert(0, os.path.join(os.environ["REPO_ROOT"], "worker"))
from cronworker import store, sync, executor

conn = store.connect(Path(os.environ["WORKER_DB"]))
client = sync.SyncClient(os.environ["PANEL_URL"], os.environ["PANEL_TOKEN"])

print("PULL", sync.pull(conn, client))
jobs = store.list_jobs(conn)
print("JOBS", [(int(j["id"]), j["name"], j["source_id"], j["source"]) for j in jobs])
if not jobs:
    raise SystemExit("el worker no recibió tareas")

job = jobs[0]
run = executor.run_job(str(job["command"]), int(job["timeout_sec"]))
print("RUN", run["status"], run["exit_code"], repr(run["output"].strip()[:40]))
store.save_run(conn, int(job["id"]), run)
print("PUSH", sync.push_pending(conn, client))
print("HEARTBEAT", sync.heartbeat(conn, client, "lxc-integracion"))
print("PENDING", store.count_pending(conn))
'@
    $pyPath = Join-Path $tmp 'worker_e2e.py'
    [IO.File]::WriteAllText($pyPath, $py, (New-Object Text.UTF8Encoding $false))
    $out = & python $pyPath 2>&1
    $out | ForEach-Object { Write-Output "   $_" }
    $texto = ($out -join "`n")

    Check 'worker recibió la tarea (pull)' ($texto -match "PULL .*'added': 1")
    Check 'worker ejecutó el comando' ($texto -match 'RUN ok 0')
    Check 'reporte aceptado por la API' ($texto -match "PUSH .*'sent': 1")
    Check 'nada pendiente' ($texto -match 'PENDING 0')
    Check 'heartbeat enviado' ($texto -match 'HEARTBEAT')

    # 3. la ejecución llegó a la BD del panel
    $env:CHECK_DB = $dbPath
    $chk = & python -c "import os,sqlite3;c=sqlite3.connect(os.environ['CHECK_DB']);print(c.execute('select count(*) from job_runs').fetchone()[0], c.execute('select status,exit_code from job_runs').fetchone())"
    $chk = ($chk -join ' ').Trim()
    Write-Output "   panel job_runs: $chk"
    Check 'la ejecución llegó a la BD del panel' ($chk -match '^1 \(.ok., 0\)')
} catch {
    $fallos++
    Write-Output "EXCEPCIÓN: $($_.Exception.Message)"
} finally {
    if ($srv -and -not $srv.HasExited) { Stop-Process -Id $srv.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Remove-Item Env:\CRONPANEL_CONFIG_FILE -ErrorAction SilentlyContinue
}

Write-Output ''
if ($fallos -gt 0) { Write-Output "INTEGRACIÓN: $fallos FALLO(S)"; exit 1 }
Write-Output 'INTEGRACIÓN: TODO OK'
