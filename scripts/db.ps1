<#
.SYNOPSIS
  Inicia, para ou mostra o estado do PostgreSQL portátil em .runtime\pgdata.
  Uso: .\scripts\db.ps1 start | stop | status
#>
param([ValidateSet("start", "stop", "status")][string]$Action = "status")
$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root ".runtime\pg\pgsql\bin"
$data = Join-Path $root ".runtime\pgdata"
$log = Join-Path $root ".runtime\pg.log"
if (-not (Test-Path "$bin\pg_ctl.exe")) { throw "PostgreSQL portátil não encontrado. Rode .\scripts\setup-postgres.ps1" }
switch ($Action) {
  "start" {
    & "$bin\pg_ctl.exe" -D $data status *> $null
    if ($LASTEXITCODE -eq 0) { Write-Host "PostgreSQL já está em execução."; break }
    # Start-Process desacopla o servidor deste terminal
    Start-Process -FilePath "$bin\pg_ctl.exe" -ArgumentList @("-D", "`"$data`"", "-l", "`"$log`"", "start") -WindowStyle Hidden -Wait
    Start-Sleep -Seconds 2
    & "$bin\pg_ctl.exe" -D $data status
  }
  "stop" { & "$bin\pg_ctl.exe" -D $data stop -m fast }
  "status" { & "$bin\pg_ctl.exe" -D $data status }
}
