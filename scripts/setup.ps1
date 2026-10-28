<#
.SYNOPSIS
  Instalação completa sem Docker: banco portátil, dependências Python e Node, migrações,
  download/importação das bases públicas e construção do grafo logístico.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot "setup-postgres.ps1")

Push-Location (Join-Path $root "backend")
if (-not (Test-Path ".venv")) { py -3.11 -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m app.cli setup     # download + ingestão + agregações + grafo
Pop-Location

Push-Location (Join-Path $root "frontend")
npm install
Pop-Location
Write-Host "Pronto. Rode .\scripts\dev.ps1 para iniciar."
