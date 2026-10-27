<#
.SYNOPSIS
  Instala um PostgreSQL 17 + PostGIS 3.6 portátil em .runtime\ (sem serviço do Windows, sem Docker, sem admin)
  e cria os bancos logitrace e logitrace_test com a extensão PostGIS.

  Se você já tem PostgreSQL + PostGIS instalados, pule este script: crie os bancos manualmente
  e ajuste LOGITRACE_DATABASE_URL em backend\.env.
#>
param(
  [string]$PgVersion = "17.7-1",
  [string]$PostgisBundle = "postgis-bundle-pg17-3.6.2x64.zip",
  [int]$Port = 5433
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$rt = Join-Path $root ".runtime"
$dl = Join-Path $rt "downloads"
New-Item -ItemType Directory -Force $dl | Out-Null

$pgZip = Join-Path $dl "pg.zip"
$gisZip = Join-Path $dl "postgis.zip"
if (-not (Test-Path $pgZip)) {
  Write-Host "Baixando PostgreSQL $PgVersion (binários oficiais EDB)..."
  Invoke-WebRequest "https://get.enterprisedb.com/postgresql/postgresql-$PgVersion-windows-x64-binaries.zip" -OutFile $pgZip
}
if (-not (Test-Path $gisZip)) {
  Write-Host "Baixando PostGIS (OSGeo)..."
  Invoke-WebRequest "https://download.osgeo.org/postgis/windows/pg17/$PostgisBundle" -OutFile $gisZip
  $md5 = (Invoke-WebRequest "https://download.osgeo.org/postgis/windows/pg17/$PostgisBundle.md5" -UseBasicParsing).Content.Split(" ")[0].Trim()
  $got = (Get-FileHash $gisZip -Algorithm MD5).Hash.ToLower()
  if ($md5 -ne $got) { throw "MD5 do PostGIS não confere ($got <> $md5)" }
}
$pg = Join-Path $rt "pg"
if (-not (Test-Path (Join-Path $pg "pgsql\bin\postgres.exe"))) {
  Expand-Archive $pgZip -DestinationPath $pg -Force
  Remove-Item -Recurse -Force (Join-Path $pg "pgsql\pgAdmin 4"), (Join-Path $pg "pgsql\StackBuilder") -ErrorAction SilentlyContinue
  $tmp = Join-Path $rt "postgis_x"
  Expand-Archive $gisZip -DestinationPath $tmp -Force
  $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
  foreach ($d in "bin", "lib", "share", "gdal-data") {
    if (Test-Path (Join-Path $src.FullName $d)) { Copy-Item (Join-Path $src.FullName "$d\*") (Join-Path $pg "pgsql\$d") -Recurse -Force -ErrorAction SilentlyContinue }
  }
  Remove-Item -Recurse -Force $tmp
}
$bin = Join-Path $pg "pgsql\bin"
$data = Join-Path $rt "pgdata"
$superPw = Join-Path $rt "pgsuper.pw"
$appPw = Join-Path $rt "pgapp.pw"
if (-not (Test-Path $data)) {
  [IO.File]::WriteAllText($superPw, [Convert]::ToBase64String((1..18 | ForEach-Object { Get-Random -Max 256 }) -as [byte[]]).TrimEnd("="))
  [IO.File]::WriteAllText($appPw, [Convert]::ToBase64String((1..18 | ForEach-Object { Get-Random -Max 256 }) -as [byte[]]).TrimEnd("=").Replace("+", "x").Replace("/", "y"))
  & "$bin\initdb.exe" -D $data -U postgres -E UTF8 --locale=C --auth=scram-sha-256 --pwfile=$superPw | Out-Null
  (Get-Content "$data\postgresql.conf") -replace "^#port = 5432", "port = $Port" -replace "^#listen_addresses = 'localhost'", "listen_addresses = 'localhost'" |
    Set-Content "$data\postgresql.conf" -Encoding utf8
}
& (Join-Path $PSScriptRoot "db.ps1") start
$env:PGPASSWORD = (Get-Content $superPw -Raw).Trim()
$app = (Get-Content $appPw -Raw).Trim()
$exists = & "$bin\psql.exe" -h localhost -p $Port -U postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='logitrace'"
if (-not $exists) {
  & "$bin\psql.exe" -h localhost -p $Port -U postgres -c "CREATE ROLE logitrace LOGIN PASSWORD '$app'" | Out-Null
  foreach ($db in "logitrace", "logitrace_test") {
    & "$bin\psql.exe" -h localhost -p $Port -U postgres -c "CREATE DATABASE $db OWNER logitrace" | Out-Null
    & "$bin\psql.exe" -h localhost -p $Port -U postgres -d $db -c "CREATE EXTENSION IF NOT EXISTS postgis" | Out-Null
  }
}
$envFile = Join-Path $root "backend\.env"
if (-not (Test-Path $envFile)) {
  @"
LOGITRACE_DATABASE_URL=postgresql+psycopg://logitrace:$app@localhost:$Port/logitrace
LOGITRACE_TEST_DATABASE_URL=postgresql+psycopg://logitrace:$app@localhost:$Port/logitrace_test
LOGITRACE_LOG_LEVEL=INFO
"@ | Set-Content $envFile -Encoding utf8
  Write-Host "backend\.env criado."
}
Write-Host "PostgreSQL + PostGIS prontos em localhost:$Port"
