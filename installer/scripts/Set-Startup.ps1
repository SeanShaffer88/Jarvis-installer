# Per-user Startup shortcut; no scheduled task and no administrator rights.
param(
    [switch]$Enable,
    [switch]$Disable,
    [string]$AppRoot = '',
    [string]$Pythonw = ''
)

$ErrorActionPreference = 'Stop'
$startup = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startup 'JARVIS.lnk'

if ($Disable -or -not $Enable) {
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath -Force }
    exit 0
}
if (-not $AppRoot) { throw 'AppRoot is required when enabling startup.' }
if (-not $Pythonw) { $Pythonw = Join-Path $AppRoot '.venv\Scripts\pythonw.exe' }
$launcher = Join-Path $AppRoot 'jarvis_win\launcher.py'
if (-not (Test-Path -LiteralPath $Pythonw) -or -not (Test-Path -LiteralPath $launcher)) {
    throw 'JARVIS runtime files are missing; startup shortcut was not created.'
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $Pythonw
$shortcut.Arguments = '"' + $launcher + '" --app-root "' + $AppRoot + '" start'
$shortcut.WorkingDirectory = $AppRoot
$shortcut.IconLocation = "$Pythonw,0"
$shortcut.Description = 'Start JARVIS on your private Windows installation'
$shortcut.Save()
exit 0
