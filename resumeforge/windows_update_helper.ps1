param(
    [Parameter(Mandatory = $true)][int]$WindowPid,
    [Parameter(Mandatory = $true)][int]$LauncherPid,
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$Digest,
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [Parameter(Mandatory = $true)][string]$Log
)

$ErrorActionPreference = 'Stop'
$app = Join-Path $Target 'ResumeForge.exe'
try {
    foreach ($waitId in @($WindowPid, $LauncherPid)) {
        if ($waitId -le 0) { continue }
        $deadline = (Get-Date).AddMinutes(2)
        while ((Get-Process -Id $waitId -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 250
        }
        if (Get-Process -Id $waitId -ErrorAction SilentlyContinue) {
            throw 'ResumeForge did not close before the update.'
        }
    }
    if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
        throw 'The downloaded installer is missing.'
    }
    if ((Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash -ine $Digest) {
        throw 'The downloaded installer failed SHA-256 verification.'
    }
    if ((Test-Path -LiteralPath $Target) -and
        (Get-ChildItem -LiteralPath $Target -Force | Select-Object -First 1) -and
        -not (Test-Path -LiteralPath (Join-Path $Target '.resumeforge-install'))) {
        throw 'The install folder contains another application.'
    }
    $setup = Start-Process -FilePath $Installer -ArgumentList @('/S', "/D=$Target") -PassThru -Wait -WindowStyle Hidden
    if ($setup.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $app -PathType Leaf)) {
        throw "The installer exited with code $($setup.ExitCode)."
    }
    Add-Content -LiteralPath $Log -Value "$(Get-Date -Format o) ResumeForge updated at $Target"
    Start-Process -FilePath $app -ArgumentList @('--data-dir', ('"' + $DataDir + '"')) | Out-Null
} catch {
    $message = "ResumeForge could not finish the update. Your workspace is still in $DataDir. Details: $($_.Exception.Message)"
    Add-Content -LiteralPath $Log -Value "$(Get-Date -Format o) $message"
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show($message, 'ResumeForge update') | Out-Null
    } catch { }
    if (Test-Path -LiteralPath $app -PathType Leaf) {
        Start-Process -FilePath $app -ArgumentList @('--data-dir', ('"' + $DataDir + '"')) | Out-Null
    }
    exit 1
}
