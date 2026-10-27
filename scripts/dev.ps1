<#
.SYNOPSIS
  Sobe o ambiente de desenvolvimento: PostgreSQL portátil, API FastAPI (:8000) e Next.js (:3000),
  cada um em sua própria janela. Pré-requisitos: setup-postgres.ps1 e setup inicial concluídos.
#>
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot "db.ps1") start
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; & '$py' -m uvicorn app.main:app --port 8000 --reload --reload-dir app"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"
Write-Host "API: http://localhost:8000/docs   Aplicação: http://localhost:3000"
