# Create an empty secret file and remove inherited access before Inno Setup
# writes the Fish Audio key into it. The key itself is never passed on a
# command line or written to a log by this script.
param(
    [Parameter(Mandatory = $true)][string]$Path
)

$ErrorActionPreference = 'Stop'
try {
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    New-Item -ItemType File -Force -Path $Path | Out-Null

    $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $Path /inheritance:r /grant:r "$($user):(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls failed with exit code $LASTEXITCODE" }
    exit 0
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
