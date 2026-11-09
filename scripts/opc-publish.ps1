# Default: offline build. Explicit --push publishes after verification.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:OPC_PYTHON) { $env:OPC_PYTHON } else { 'python' }
& $python (Join-Path $root 'opc_publish.py') @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
