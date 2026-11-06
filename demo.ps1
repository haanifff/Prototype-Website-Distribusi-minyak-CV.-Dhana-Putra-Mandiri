$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:DEMO_MODE = '1'
$env:APP_ENV = 'local'
$pythonApp = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonApp)) { throw 'Siapkan virtual environment sesuai README.md dahulu.' }
& $pythonApp manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonApp manage.py demo_seed
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Demo lokal: http://127.0.0.1:18765/'
& $pythonApp -m waitress --listen=127.0.0.1:18765 portal.wsgi:application
