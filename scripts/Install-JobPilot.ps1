param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$BuildRoot = '',
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\JobPilot'),
    [string]$DataRoot = '',
    [string]$Python = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
    [switch]$SkipDependencies,
    [switch]$Launch
)
$ErrorActionPreference = 'Stop'
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
if (-not $BuildRoot) { $BuildRoot = Join-Path $SourceRoot 'build\desktop-dist\JobPilot' }
$BuildRoot = [IO.Path]::GetFullPath($BuildRoot)
if (-not $DataRoot) {
    $existingPaths = Join-Path $InstallRoot 'installed_paths.json'
    if (Test-Path -LiteralPath $existingPaths) {
        $DataRoot = (Get-Content -LiteralPath $existingPaths -Raw | ConvertFrom-Json).data
    }
    if (-not $DataRoot) { $DataRoot = Join-Path $InstallRoot 'data' }
}
if (-not (Test-Path -LiteralPath $Python)) { throw 'Python 3.13 is required. Install Python for this Windows user, then pass its executable with -Python.' }
if (-not (Test-Path -LiteralPath (Join-Path $BuildRoot 'JobPilot.exe'))) { throw 'Build JobPilot.exe with Build-JobPilot.ps1 first, or pass -BuildRoot.' }
if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot 'jobpilot\service.py'))) { throw 'The JobPilot service source is missing.' }
New-Item -ItemType Directory -Path $InstallRoot,$DataRoot -Force | Out-Null
# Resolve physical paths so MSIX file virtualization cannot split the installed
# desktop and database into different locations.
$InstallRoot = (& $Python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' $InstallRoot).Trim()
$DataRoot = (& $Python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' $DataRoot).Trim()
if ([string]::Equals($SourceRoot, $InstallRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'SourceRoot must be a checkout separate from InstallRoot so managed files can be replaced safely.'
}

function Assert-ManagedChild([string]$Parent, [string]$Child) {
    $separators = [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $parentPath = [IO.Path]::GetFullPath($Parent).TrimEnd($separators)
    $childPath = [IO.Path]::GetFullPath($Child)
    $prefix = $parentPath + [IO.Path]::DirectorySeparatorChar
    if (-not $childPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace a path outside its managed directory: $childPath"
    }
}

$runtime = Join-Path $DataRoot 'runtime'
$runtimeStage = Join-Path $DataRoot 'runtime.next'
$runtimePrevious = Join-Path $DataRoot 'runtime.previous'
foreach ($path in @($runtime,$runtimeStage,$runtimePrevious)) { Assert-ManagedChild $DataRoot $path }
$runtimeLock = Join-Path $SourceRoot 'requirements-runtime.lock'
$runtimeFingerprint = (Get-FileHash -LiteralPath $runtimeLock -Algorithm SHA256).Hash
$installedFingerprint = Join-Path $runtime 'requirements.sha256'
if ((Test-Path -LiteralPath (Join-Path $runtime 'Scripts\python.exe')) -and
    (Test-Path -LiteralPath $installedFingerprint) -and
    ((Get-Content -LiteralPath $installedFingerprint -Raw).Trim() -eq $runtimeFingerprint)) {
    $SkipDependencies = $true
}
if ($SkipDependencies) {
    $runtimePython = Join-Path $runtime 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $runtimePython)) {
        throw '-SkipDependencies requires an existing compatible JobPilot runtime.'
    }
} else {
    foreach ($path in @($runtimeStage,$runtimePrevious)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
    }
    & $Python -m venv $runtimeStage
    if ($LASTEXITCODE -ne 0) { throw 'Failed to stage the JobPilot Python runtime.' }
    $stagedPython = Join-Path $runtimeStage 'Scripts\python.exe'
    & $stagedPython -m pip install --disable-pip-version-check --progress-bar off -r (Join-Path $SourceRoot 'requirements-runtime.lock')
    if ($LASTEXITCODE -ne 0) { throw 'JobPilot runtime dependency installation failed.' }
    & $stagedPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'JobPilot runtime contains conflicting dependencies.' }
    $priorPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $SourceRoot
        & $stagedPython -c 'import pandas, pdfplumber, reportlab; from jobspy import scrape_jobs; import jobpilot.collectors; import resumeforge.engine'
        if ($LASTEXITCODE -ne 0) { throw 'JobPilot runtime import check failed.' }
    } finally {
        $env:PYTHONPATH = $priorPythonPath
    }
    Set-Content -LiteralPath (Join-Path $runtimeStage 'requirements.sha256') -Value $runtimeFingerprint
}

$desktop = Join-Path $InstallRoot 'JobPilot.exe'
if (Test-Path -LiteralPath $desktop) {
    $dashboardProcesses = @(Get-CimInstance Win32_Process -Filter "Name = 'JobPilot.exe'" |
        Where-Object { $_.ExecutablePath -eq $desktop })
    if ($dashboardProcesses | Where-Object { $_.CommandLine -match '\-\-resumeforge-child' }) {
        throw 'Save and close the open ResumeForge editor, then run the update again.'
    }
    $endpoint = 'http://127.0.0.1:8765'
    try { $health = Invoke-RestMethod "$endpoint/api/health" -TimeoutSec 2 } catch { $health = $null }
    if ($health -and $health.data_dir -eq $DataRoot -and $health.ok -eq $true) {
        $token = (Invoke-RestMethod "$endpoint/api/session" -TimeoutSec 3).token
        $deadline = [DateTime]::UtcNow.AddMinutes(2)
        do {
            try {
                $reply = Invoke-RestMethod "$endpoint/api/control" -Method Post -TimeoutSec 3 `
                    -Headers @{ 'X-JobPilot-Token' = $token } -ContentType 'application/json' `
                    -Body '{"action":"shutdown","preserve_preferences":true}'
                if ($reply.ok) { break }
            } catch { Start-Sleep -Seconds 1 }
        } while ([DateTime]::UtcNow -lt $deadline)
        if (Get-Process -Id $health.pid -ErrorAction SilentlyContinue) {
            Wait-Process -Id $health.pid -Timeout 20 -ErrorAction SilentlyContinue
            if (Get-Process -Id $health.pid -ErrorAction SilentlyContinue) {
                throw 'JobPilot is still finishing work. The existing app is intact.'
            }
        }
    }
    foreach ($process in $dashboardProcesses) {
        Stop-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
    }
}

# Application-owned code and binaries are replaced, never merged, so upgrades
# cannot retain removed generators or legacy frozen modules. DataRoot is outside
# this allowlist and is preserved in full.
$managedFolders = @('web','docs','scripts','assets','jobpilot','resumeforge','_internal','remote_web')
foreach ($folder in $managedFolders) {
    $target = Join-Path $InstallRoot $folder
    Assert-ManagedChild $InstallRoot $target
    $separators = [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $targetPrefix = [IO.Path]::GetFullPath($target).TrimEnd($separators) + [IO.Path]::DirectorySeparatorChar
    if ([string]::Equals($DataRoot, [IO.Path]::GetFullPath($target), [StringComparison]::OrdinalIgnoreCase) -or
        $DataRoot.StartsWith($targetPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "DataRoot cannot be inside an application-owned folder: $target"
    }
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
}
foreach ($folder in @('web','docs','scripts','assets')) {
    $from = Join-Path $SourceRoot $folder
    if (Test-Path -LiteralPath $from) { Copy-Item -LiteralPath $from -Destination $InstallRoot -Recurse -Force }
}
$packageRoot = Join-Path $InstallRoot 'jobpilot'
New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $SourceRoot 'jobpilot') -File -Filter '*.py' | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $packageRoot -Force
}
Copy-Item -LiteralPath (Join-Path $SourceRoot 'jobpilot\candidate.json') -Destination $packageRoot -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'jobpilot\greenhouse_boards.json') -Destination $packageRoot -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'resumeforge') -Destination $InstallRoot -Recurse -Force
foreach ($filename in @('launcher.py','requirements.lock','requirements-runtime.lock','README.md','LICENSE','THIRD_PARTY_NOTICES.md')) {
    $from = Join-Path $SourceRoot $filename
    if (Test-Path -LiteralPath $from) { Copy-Item -LiteralPath $from -Destination (Join-Path $InstallRoot $filename) -Force }
}
Copy-Item -LiteralPath (Join-Path $BuildRoot 'JobPilot.exe') -Destination (Join-Path $InstallRoot 'JobPilot.exe') -Force
Copy-Item -LiteralPath (Join-Path $BuildRoot '_internal') -Destination $InstallRoot -Recurse -Force
if (-not $SkipDependencies) {
    if (Test-Path -LiteralPath $runtime) { Move-Item -LiteralPath $runtime -Destination $runtimePrevious }
    try {
        Move-Item -LiteralPath $runtimeStage -Destination $runtime
    } catch {
        if (Test-Path -LiteralPath $runtimePrevious) {
            Move-Item -LiteralPath $runtimePrevious -Destination $runtime
        }
        throw
    }
    if (Test-Path -LiteralPath $runtimePrevious) { Remove-Item -LiteralPath $runtimePrevious -Recurse -Force }
    $runtimePython = Join-Path $runtime 'Scripts\python.exe'
}
$webviewRoot = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\EdgeWebView\Application'
if (-not (Test-Path -LiteralPath $webviewRoot)) {
    $setupRoot = Join-Path $DataRoot 'setup'
    New-Item -ItemType Directory -Path $setupRoot -Force | Out-Null
    $webviewInstaller = Join-Path $setupRoot 'MicrosoftEdgeWebview2Setup.exe'
    Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $webviewInstaller
    $webviewSetup = Start-Process -FilePath $webviewInstaller -ArgumentList '/silent','/install' -WindowStyle Hidden -Wait -PassThru
    if ($webviewSetup.ExitCode -ne 0) { throw "WebView2 setup failed: $($webviewSetup.ExitCode)" }
}
$installedPaths = [ordered]@{
    source = $InstallRoot
    python = $runtimePython
    desktop_exe = (Join-Path $InstallRoot 'JobPilot.exe')
    data = $DataRoot
    service_url = 'http://127.0.0.1:8765'
}
$installedPaths | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $InstallRoot 'installed_paths.json') -Encoding utf8
$shell = New-Object -ComObject WScript.Shell
$desktop = $shell.SpecialFolders.Item('Desktop')
$startMenu = Join-Path $shell.SpecialFolders.Item('Programs') 'JobPilot'
New-Item -ItemType Directory -Path $startMenu -Force | Out-Null
foreach ($shortcutPath in @((Join-Path $desktop 'JobPilot.lnk'),(Join-Path $startMenu 'JobPilot.lnk'))) {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $installedPaths.desktop_exe
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.Description = 'Private local job search and application assistant'
    $shortcut.IconLocation = "$($installedPaths.desktop_exe),0"
    $shortcut.Save()
}
Write-Output ($installedPaths | ConvertTo-Json -Depth 3)
& (Join-Path $InstallRoot 'scripts\Install-Recovery.ps1') -InstallRoot $InstallRoot
if ($Launch) { Start-Process -FilePath $installedPaths.desktop_exe -WindowStyle Hidden | Out-Null }
