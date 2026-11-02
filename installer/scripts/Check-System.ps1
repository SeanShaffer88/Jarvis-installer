# Phase 5 checks page. Writes simple Status=OK/FAIL lines for Inno Setup.
param(
    [Parameter(Mandatory = $true)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'

function Write-CheckResult {
    param(
        [string]$Status, [string]$Windows, [string]$Chrome,
        [string]$ChromePath, [string]$DiskGB, [string]$Message
    )
    $lines = @(
        "Status=$Status",
        "Windows=$Windows",
        "Chrome=$Chrome",
        "ChromePath=$ChromePath",
        "DiskGB=$DiskGB",
        "Message=$Message"
    )
    Set-Content -LiteralPath $OutputPath -Value $lines -Encoding UTF8
}

try {
    $os = Get-CimInstance Win32_OperatingSystem
    $build = [int]$os.BuildNumber
    $windowsOK = $build -ge 17763  # Windows 10 1809 / Windows Server 2019

    $chromePath = $null
    $appPathKeys = @(
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe'
    )
    foreach ($key in $appPathKeys) {
        if (Test-Path -LiteralPath $key) {
            $value = (Get-ItemProperty -LiteralPath $key).'(default)'
            if ($value -and (Test-Path -LiteralPath $value)) { $chromePath = $value; break }
        }
    }
    if (-not $chromePath) {
        $command = Get-Command chrome.exe -ErrorAction SilentlyContinue
        if ($command) { $chromePath = $command.Source }
    }
    if (-not $chromePath) {
        $candidates = @(
            (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
            (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
        )
        foreach ($candidate in $candidates) {
            if ($candidate -and (Test-Path -LiteralPath $candidate)) { $chromePath = $candidate; break }
        }
    }

    $driveRoot = [System.IO.Path]::GetPathRoot($env:LOCALAPPDATA)
    $drive = [System.IO.DriveInfo]::new($driveRoot)
    $freeGB = [math]::Round($drive.AvailableFreeSpace / 1GB, 2)
    $diskOK = $freeGB -ge 1.0

    $messages = @()
    if ($windowsOK) { $messages += 'Windows 10 version 1809 or newer: OK.' }
    else { $messages += 'JARVIS needs Windows 10 version 1809 or Windows 11.' }
    if ($chromePath) { $messages += 'Chrome, required for voice input: found.' }
    else { $messages += 'Google Chrome is required. Voice input has no fallback browser.' }
    if ($diskOK) { $messages += "Free space for the private install: $freeGB GB." }
    else { $messages += "About 1 GB of free space is needed; only $freeGB GB is available." }

    $ok = $windowsOK -and [bool]$chromePath -and $diskOK
    Write-CheckResult -Status ($(if ($ok) { 'OK' } else { 'FAIL' })) `
        -Windows ($(if ($windowsOK) { 'OK' } else { 'FAIL' })) `
        -Chrome ($(if ($chromePath) { 'OK' } else { 'FAIL' })) `
        -ChromePath ([string]$chromePath) -DiskGB ([string]$freeGB) `
        -Message ($messages -join ' ')
    exit $(if ($ok) { 0 } else { 2 })
}
catch {
    Write-CheckResult -Status 'FAIL' -Windows 'UNKNOWN' -Chrome 'UNKNOWN' `
        -ChromePath '' -DiskGB 'UNKNOWN' -Message ("The PC check could not finish: " + $_.Exception.Message)
    exit 1
}
