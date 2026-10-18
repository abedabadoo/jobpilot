param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$BuildPython = '',
    [string]$WorkRoot = ''
)
$ErrorActionPreference = 'Stop'
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
if (-not $WorkRoot) { $WorkRoot = Join-Path $SourceRoot 'build' }
if (-not $BuildPython) { $BuildPython = Join-Path $SourceRoot '.venv\Scripts\python.exe' }
$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
if (-not (Test-Path -LiteralPath $BuildPython)) { throw "Build Python missing: $BuildPython" }
$distRoot = Join-Path $WorkRoot 'desktop-dist'
$buildRoot = Join-Path $WorkRoot 'desktop-build'
$specRoot = Join-Path $WorkRoot 'desktop-spec'
New-Item -ItemType Directory -Path $distRoot,$buildRoot,$specRoot -Force | Out-Null
$env:PYINSTALLER_CONFIG_DIR = Join-Path $WorkRoot 'pyinstaller-cache'
$arguments = @('-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed','--name','JobPilot',
    '--distpath',$distRoot,'--workpath',$buildRoot,'--specpath',$specRoot,
    '--collect-all','webview','--collect-all','pystray','--collect-all','clr_loader','--collect-all','pythonnet',
    '--hidden-import','pystray._win32','--icon',(Join-Path $SourceRoot 'assets\jobpilot.ico'),(Join-Path $SourceRoot 'launcher.py'))
& $BuildPython @arguments
if ($LASTEXITCODE -ne 0) { throw "Executable build failed with exit code $LASTEXITCODE" }
$built = Join-Path $distRoot 'JobPilot'
Write-Output "Built: $(Join-Path $built 'JobPilot.exe')"
