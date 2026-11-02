# Stop a running JARVIS before an over-the-top update or uninstall.
# User data, .env, certificates, and memory are never touched.
param(
    [string]$AppRoot = ''
)

$ErrorActionPreference = 'SilentlyContinue'
if (-not $AppRoot) { exit 0 }
$pythonw = Join-Path $AppRoot '.venv\Scripts\pythonw.exe'
$launcher = Join-Path $AppRoot 'jarvis_win\launcher.py'
if ((Test-Path -LiteralPath $pythonw) -and (Test-Path -LiteralPath $launcher)) {
    & $pythonw $launcher --app-root $AppRoot stop | Out-Null
}
exit 0
