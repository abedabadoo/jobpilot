param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$BuildRoot = '',
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\JobPilot'),
    [string]$DataRoot = '',
    [string]$Python = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
    [switch]$SkipModel,
    [switch]$SkipBrowser,
    [switch]$SkipDependencies,
    [switch]$Launch
)
$ErrorActionPreference = 'Stop'
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
if (-not $BuildRoot) { $BuildRoot = Join-Path $SourceRoot 'build\desktop-dist\JobPilot' }
$BuildRoot = [IO.Path]::GetFullPath($BuildRoot)
if (-not $DataRoot) { $DataRoot = Join-Path $InstallRoot 'data' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Python 3.13 is required. Install Python for this Windows user, then pass its executable with -Python.' }
if (-not (Test-Path -LiteralPath (Join-Path $BuildRoot 'JobPilot.exe'))) { throw 'Build JobPilot.exe with Build-JobPilot.ps1 first, or pass -BuildRoot.' }
if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot 'jobpilot\service.py'))) { throw 'The JobPilot service source is missing.' }
New-Item -ItemType Directory -Path $InstallRoot,$DataRoot -Force | Out-Null
# Resolve physical paths so MSIX file virtualization cannot split the installed
# desktop, database, model store or browser binaries into different locations.
$InstallRoot = (& $Python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' $InstallRoot).Trim()
$DataRoot = (& $Python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' $DataRoot).Trim()
foreach ($folder in @('web','remote_web','docs','scripts','assets')) {
    $from = Join-Path $SourceRoot $folder
    if (Test-Path -LiteralPath $from) { Copy-Item -LiteralPath $from -Destination $InstallRoot -Recurse -Force }
}
$packageRoot = Join-Path $InstallRoot 'jobpilot'
New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $SourceRoot 'jobpilot') -File -Filter '*.py' | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $packageRoot -Force
}
Copy-Item -LiteralPath (Join-Path $SourceRoot 'jobpilot\candidate.json') -Destination $packageRoot -Force
foreach ($filename in @('launcher.py','requirements.lock','README.md','LICENSE','THIRD_PARTY_NOTICES.md')) {
    $from = Join-Path $SourceRoot $filename
    if (Test-Path -LiteralPath $from) { Copy-Item -LiteralPath $from -Destination (Join-Path $InstallRoot $filename) -Force }
}
Copy-Item -LiteralPath (Join-Path $BuildRoot 'JobPilot.exe') -Destination (Join-Path $InstallRoot 'JobPilot.exe') -Force
Copy-Item -LiteralPath (Join-Path $BuildRoot '_internal') -Destination $InstallRoot -Recurse -Force
$runtime = Join-Path $DataRoot 'runtime'
$runtimePython = Join-Path $runtime 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) {
    & $Python -m venv $runtime
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create JobPilot Python runtime.' }
}
if (-not $SkipDependencies) {
    & $runtimePython -m pip install --disable-pip-version-check --progress-bar off -r (Join-Path $InstallRoot 'requirements.lock')
    if ($LASTEXITCODE -ne 0) { throw 'JobPilot dependency installation failed.' }
    & $runtimePython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'JobPilot runtime contains conflicting dependencies.' }
}
& (Join-Path $InstallRoot 'scripts\Install-RemoteTools.ps1') -InstallRoot (Split-Path -Parent $DataRoot)
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $DataRoot 'browsers'
if (-not $SkipBrowser) {
    & $runtimePython -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed.' }
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
$ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $ollama)) { throw 'Ollama is required. Install it from https://ollama.com/download/windows, then rerun this installer.' }
$ollama = (& $Python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' $ollama).Trim()
$installedPaths = [ordered]@{
    source = $InstallRoot
    python = $runtimePython
    ollama = $ollama
    desktop_exe = (Join-Path $InstallRoot 'JobPilot.exe')
    data = $DataRoot
    browsers = $env:PLAYWRIGHT_BROWSERS_PATH
    models = (Join-Path $DataRoot 'ollama-models')
    service_url = 'http://127.0.0.1:8765'
    ollama_url = 'http://127.0.0.1:11436'
    model = 'qwen3.5:9b'
}
$installedPaths | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $InstallRoot 'installed_paths.json') -Encoding utf8
if (-not $SkipModel) {
    $env:OLLAMA_HOST = '127.0.0.1:11436'
    $env:OLLAMA_NO_CLOUD = '1'
    $env:OLLAMA_MODELS = $installedPaths.models
    $env:OLLAMA_CONTEXT_LENGTH = '8192'
    $env:OLLAMA_FLASH_ATTENTION = '1'
    $env:OLLAMA_KV_CACHE_TYPE = 'q8_0'
    $env:OLLAMA_NUM_PARALLEL = '1'
    $env:OLLAMA_MAX_LOADED_MODELS = '1'
    $env:OLLAMA_KEEP_ALIVE = '15m'
    $logs = Join-Path $DataRoot 'logs'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:11436/api/version' -TimeoutSec 2 | Out-Null }
    catch {
        $modelServer = Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'ollama.out.log') -RedirectStandardError (Join-Path $logs 'ollama.err.log') -PassThru
        $modelServer.Id | Set-Content -LiteralPath (Join-Path $DataRoot 'ollama.pid') -Encoding ascii
        $ready = $false
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            try { Invoke-RestMethod -Uri 'http://127.0.0.1:11436/api/version' -TimeoutSec 1 | Out-Null; $ready = $true; break }
            catch { Start-Sleep -Milliseconds 250 }
        }
        if (-not $ready) { throw 'The local-only Ollama service did not start.' }
    }
    $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11436/api/tags'
    if (-not ($tags.models | Where-Object { $_.name -eq 'qwen3.5:9b' })) {
        Invoke-RestMethod -Uri 'http://127.0.0.1:11436/api/pull' -Method Post -ContentType 'application/json' -Body '{"model":"qwen3.5:9b","stream":false}' -TimeoutSec 3600 | Out-Null
    }
}
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
