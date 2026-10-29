# One-time Windows VM setup for winvm. `winvm init` pushes this file and the
# Mac's public key into C:\Users\Public; run it once from an administrator
# Windows PowerShell as the account that logs in to the desktop:
#   powershell -ExecutionPolicy Bypass -File C:\Users\Public\winvm-setup.ps1
# Safe to rerun. Compatible with Windows PowerShell 5.1.
$ErrorActionPreference = 'Stop'
$public = 'C:\Users\Public'
$pwsh = 'C:\Program Files\PowerShell\7\pwsh.exe'

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'Run this from PowerShell opened with "Run as administrator".'
}
$key = Get-Content -Raw "$public\winvm-mac.pub" -ErrorAction SilentlyContinue
if (-not $key) { throw "Missing $public\winvm-mac.pub; run winvm init on the Mac first." }

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }

# The Mac's proxy listens on port 7897 of the UTM gateway; use it when it answers.
$proxy = $null
$gateway = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1).NextHop
if ($gateway) {
  $tcp = New-Object Net.Sockets.TcpClient
  if ($tcp.ConnectAsync($gateway, 7897).Wait(2000) -and $tcp.Connected) { $proxy = "http://${gateway}:7897" }
  $tcp.Close()
}
$wingetProxy = @()
if ($proxy) {
  Step "Downloads go through the Mac proxy $proxy"
  $env:HTTP_PROXY = $proxy; $env:HTTPS_PROXY = $proxy; $env:NO_PROXY = 'localhost,127.0.0.1'
  netsh.exe winhttp set proxy "${gateway}:7897" '<local>' | Out-Null
  winget settings --enable ProxyCommandLineOptions *> $null
  $wingetProxy = @('--proxy', $proxy)
} else {
  Write-Warning 'The Mac proxy on port 7897 is unreachable; downloading directly.'
}
function Update-Path {
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Install-WingetPackage($id) {
  winget list --id $id -e --accept-source-agreements *> $null
  if ($LASTEXITCODE -eq 0) { Write-Host "    $id already installed"; return }
  winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements @wingetProxy
  if ($LASTEXITCODE) { throw "winget could not install $id (exit $LASTEXITCODE)" }
}

Step 'Toolchain: Git, Node LTS, Python 3, PowerShell 7'
foreach ($id in 'Git.Git', 'OpenJS.NodeJS.LTS', 'Python.Python.3.12') { Install-WingetPackage $id }
# sshd needs a machine-wide pwsh.exe. winget treats a Store copy (which services
# cannot start) as the same package, so install the release MSI directly.
if (-not (Test-Path $pwsh)) {
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  $web = @{ UseBasicParsing = $true }
  if ($proxy) { $web.Proxy = $proxy }
  # Read the stable tag from the repository file: the REST API rate-limits shared proxy exits.
  $tag = (Invoke-RestMethod @web 'https://raw.githubusercontent.com/PowerShell/PowerShell/master/tools/metadata.json').StableReleaseTag
  $name = "PowerShell-$($tag.TrimStart('v'))-win-arm64.msi"
  $msi = Join-Path $env:TEMP $name
  Write-Host "    downloading $name"
  Invoke-WebRequest @web "https://github.com/PowerShell/PowerShell/releases/download/$tag/$name" -OutFile $msi
  $install = Start-Process msiexec.exe -ArgumentList '/i', "`"$msi`"", '/quiet', '/norestart', 'ADD_PATH=1' -Wait -PassThru
  if (-not (Test-Path $pwsh)) { throw "PowerShell 7 did not install to $pwsh (msiexec exit $($install.ExitCode))" }
}
Update-Path

Step 'OpenSSH Server'
$capability = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
if ($capability.State -ne 'Installed') { Add-WindowsCapability -Online -Name $capability.Name | Out-Null }
Set-Service sshd -StartupType Automatic
Start-Service sshd
# UTM's network counts as Public, and Windows' own rule covers Private only and
# ignores a profile change, so add a rule of our own.
if (-not (Get-NetFirewallRule -Name 'winvm-sshd' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -Name 'winvm-sshd' -DisplayName 'winvm OpenSSH Server' -Enabled True -Profile Any `
    -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}
New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -Value $pwsh -PropertyType String -Force | Out-Null

# Administrators read keys from one shared file that only Administrators and
# SYSTEM may access; the SIDs keep this working on localized Windows.
Step 'Authorize the Mac key'
$keys = 'C:\ProgramData\ssh\administrators_authorized_keys'
$line = $key.Trim()
if (-not ((Test-Path $keys) -and (Get-Content $keys) -contains $line)) { Add-Content -Path $keys -Value $line -Encoding ascii }
icacls.exe $keys /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null
Restart-Service sshd

Step 'Job root and desktop task'
New-Item -ItemType Directory -Force 'C:\winvm\jobs' | Out-Null
$action = New-ScheduledTaskAction -Execute $pwsh `
  -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File C:\winvm\runner.ps1 -Mode desktop'
$user = "$env:USERDOMAIN\$env:USERNAME"
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'winvm-interactive' -Action $action -Principal $taskPrincipal -Settings $settings -Force | Out-Null

Step 'Keep the desktop awake and unlocked'
powercfg.exe /change monitor-timeout-ac 0
powercfg.exe /change standby-timeout-ac 0
New-ItemProperty -Path 'HKCU:\Control Panel\Desktop' -Name ScreenSaveActive -Value '0' -PropertyType String -Force | Out-Null
New-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' -Force | Out-Null
New-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' -Name NoLockScreen -Value 1 -PropertyType DWord -Force | Out-Null

Step 'Playwright Chromium (headless default; Edge ships with Windows)'
& npx.cmd -y playwright@latest install chromium
if ($LASTEXITCODE) { Write-Warning 'Playwright Chromium did not install; tests can still use channel msedge.' }

if ($proxy) { netsh.exe winhttp reset proxy | Out-Null }
Set-Content -Path "$public\winvm-user.txt" -Value $env:USERNAME -Encoding ascii
Write-Host ''
Write-Host "Done. Run winvm init on the Mac again to connect as $env:USERNAME." -ForegroundColor Green
Write-Host 'For desktop runs, also turn on automatic sign-in for this account (netplwiz, or Sysinternals Autologon).'
