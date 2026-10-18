param([string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\JobPilot'))
$ErrorActionPreference = 'Stop'
$toolRoot = Join-Path ([IO.Path]::GetFullPath($InstallRoot)) 'tools'
New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
$destination = Join-Path $toolRoot 'cloudflared.exe'
$expected = '86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c'
$source = 'https://github.com/cloudflare/cloudflared/releases/download/2026.10.0/cloudflared-windows-amd64.exe'
if ((Test-Path -LiteralPath $destination) -and (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expected) { return }
$temporary = Join-Path $toolRoot 'cloudflared.download.exe'
Invoke-WebRequest -Uri $source -OutFile $temporary
if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'cloudflared did not match the pinned official release digest.' }
Move-Item -LiteralPath $temporary -Destination $destination -Force
@{version='2026.10.0';sha256=$expected;source=$source} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $toolRoot 'cloudflared-release.json')
