# Install missing prerequisites in the current user's profile only.
# No Node.js, no npm, no claude.cmd shim, no administrator rights.
param(
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$ManifestPath = '',
    [string]$Strategy = 'winget-user'
)

$ErrorActionPreference = 'Stop'

$config = @{
    python_package_id = 'Python.Python.3.12'
    python_min_version = '3.11'
    git_package_id = 'Git.Git'
    claude_package_id = 'Anthropic.ClaudeCode'
    claude_min_version = '2.1.224'
}
if ($ManifestPath -and (Test-Path -LiteralPath $ManifestPath)) {
    try {
        $json = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($name in @('python_package_id', 'python_min_version', 'git_package_id', 'claude_package_id', 'claude_min_version')) {
            if ($json.PSObject.Properties.Name -contains $name) { $config[$name] = [string]$json.$name }
        }
    } catch { }
}

function Write-PrereqResult {
    param([string]$Status, [string]$Python, [string]$Claude, [string]$Git, [string]$Message)
    Set-Content -LiteralPath $OutputPath -Value @(
        "Status=$Status", "Python=$Python", "Claude=$Claude", "Git=$Git", "Message=$Message"
    ) -Encoding UTF8
}

function Refresh-UserPath {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $nativeBin = Join-Path $env:USERPROFILE '.local\bin'
    $env:Path = (@($userPath, $machinePath, $nativeBin) -join ';')
}

function Find-Python {
    $probe = 'import sys; print(sys.executable); print(sys.version_info[0]); print(sys.version_info[1])'
    $commands = @(
        @{ File = 'py'; Args = @('-3', '-c', $probe) },
        @{ File = 'python'; Args = @('-c', $probe) },
        @{ File = 'python3'; Args = @('-c', $probe) }
    )
    foreach ($item in $commands) {
        $command = Get-Command $item.File -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        try {
            $arguments = [string[]]$item.Args
            $out = & $command.Source @arguments 2>$null
            if ($LASTEXITCODE -eq 0 -and $out.Count -ge 3) {
                $major = [int]$out[1]
                $minor = [int]$out[2]
                if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) { return [string]$out[0] }
            }
        } catch { }
    }
    $known = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe')
    )
    foreach ($candidate in $known) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Find-Git {
    $command = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
        (Join-Path $env:ProgramFiles 'Git\cmd\git.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe')
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    return $null
}

function Find-NativeClaude {
    $known = @(
        (Join-Path $env:USERPROFILE '.local\bin\claude.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Claude Code\claude.exe')
    )
    foreach ($candidate in $known) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    $commands = Get-Command claude -All -ErrorAction SilentlyContinue
    foreach ($command in @($commands)) {
        $source = [string]$command.Source
        if ([System.IO.Path]::GetExtension($source) -ieq '.exe' -and (Test-Path -LiteralPath $source)) {
            return $source
        }
    }
    return $null
}

function Test-ClaudeVersion {
    param([string]$Path)
    try {
        $text = (& $Path --version 2>&1) -join ' '
        if ($text -match '(\d+)\.(\d+)\.(\d+)') {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]; $patch = [int]$Matches[3]
            return ($major -gt 2) -or ($major -eq 2 -and $minor -gt 1) -or ($major -eq 2 -and $minor -eq 1 -and $patch -ge 224)
        }
    } catch { }
    return $false
}

function Invoke-WingetInstall {
    param([string]$PackageId)
    & winget.exe install --id $PackageId --scope user --exact --silent `
        --disable-interactivity --accept-package-agreements --accept-source-agreements | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "WinGet could not install $PackageId (exit code $LASTEXITCODE)."
    }
}

try {
    if ($Strategy -ne 'winget-user') { throw "Unsupported prerequisite strategy: $Strategy" }
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw 'Windows App Installer (winget) is needed for a no-admin install. Install App Installer from the Microsoft Store and run setup again.'
    }

    $python = Find-Python
    if (-not $python) {
        Invoke-WingetInstall $config.python_package_id
        Refresh-UserPath
        $python = Find-Python
    }
    if (-not $python) { throw 'Python 3.11 or newer could not be found after installation. Open a new terminal and run setup again.' }

    $git = Find-Git
    if (-not $git) {
        Invoke-WingetInstall $config.git_package_id
        Refresh-UserPath
        $git = Find-Git
    }

    $claude = Find-NativeClaude
    if (-not $claude -or -not (Test-ClaudeVersion $claude)) {
        Invoke-WingetInstall $config.claude_package_id
        Refresh-UserPath
        $claude = Find-NativeClaude
    }
    if (-not $claude) {
        throw 'Native Claude Code was not found. The npm claude.cmd shim is deliberately refused because JARVIS cannot spawn it.'
    }
    if (-not (Test-ClaudeVersion $claude)) {
        throw "Claude Code must be $($config.claude_min_version) or newer. Run 'claude update' and try again."
    }

    Write-PrereqResult -Status 'OK' -Python $python -Claude $claude -Git ([string]$git) `
        -Message 'Python, Git, and native Claude Code are ready. Node.js is not needed.'
    exit 0
}
catch {
    Write-PrereqResult -Status 'FAIL' -Python (Find-Python) -Claude (Find-NativeClaude) `
        -Git (Find-Git) -Message $_.Exception.Message
    exit 1
}
