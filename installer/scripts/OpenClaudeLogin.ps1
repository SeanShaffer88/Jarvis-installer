# Last wizard page: open one visible native Claude Code session for login.
param(
    [string]$ClaudePath = ''
)

$ErrorActionPreference = 'Stop'
if (-not $ClaudePath) {
    $candidates = @(
        (Join-Path $env:USERPROFILE '.local\bin\claude.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Claude Code\claude.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { $ClaudePath = $candidate; break }
    }
}
if (-not $ClaudePath -or -not (Test-Path -LiteralPath $ClaudePath)) {
    Write-Error 'Native claude.exe was not found; the setup cannot open the login window.'
    exit 1
}

$wt = Get-Command wt.exe -ErrorAction SilentlyContinue
if ($wt) {
    $quoted = '"' + $ClaudePath + '"'
    Start-Process -FilePath $wt.Source -ArgumentList @(
        'new-tab', '--title', 'Claude login', '--', $quoted
    ) | Out-Null
} else {
    Start-Process -FilePath $ClaudePath -WorkingDirectory $env:USERPROFILE | Out-Null
}
exit 0
