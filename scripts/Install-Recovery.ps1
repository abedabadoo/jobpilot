param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\JobPilot')
)
$ErrorActionPreference = 'Stop'
$executable = Join-Path ([IO.Path]::GetFullPath($InstallRoot)) 'JobPilot.exe'
if (-not (Test-Path -LiteralPath $executable)) { throw "JobPilot executable is missing: $executable" }
$installedPaths = Get-Content -LiteralPath (Join-Path $InstallRoot 'installed_paths.json') -Raw | ConvertFrom-Json
$runtimePython = Join-Path (Split-Path -Parent $installedPaths.python) 'pythonw.exe'
$recoveryScript = Join-Path $InstallRoot 'scripts\recover_worker.py'
if (-not (Test-Path -LiteralPath $runtimePython)) { throw "JobPilot runtime is missing: $runtimePython" }
if (-not (Test-Path -LiteralPath $recoveryScript)) { throw "JobPilot recovery script is missing: $recoveryScript" }
$taskUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $runtimePython -Argument ('"' + $recoveryScript + '"') -WorkingDirectory $InstallRoot
$logon = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
$task = Register-ScheduledTask -TaskName 'JobPilot Worker Recovery' -Action $action -Trigger @($logon,$periodic) -Principal $principal -Settings $taskSettings -Description 'Restore JobPilot local services after sign-in or interruption. Preserve saved search and application pause settings.' -Force
$task | Select-Object TaskName, State
