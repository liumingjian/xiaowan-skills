# Runs one winvm job inside the Windows VM. winvm copies this file to
# C:\winvm\runner.ps1 before every job; the winvm-interactive scheduled task
# runs it with -Mode desktop on the logged-in desktop.
param(
  [ValidateSet('exec', 'desktop', 'check')] [string] $Mode = 'exec',
  [string] $Job
)
$ErrorActionPreference = 'Stop'
$root = 'C:\winvm'

if ($Mode -eq 'check') {
  if (-not (Get-Process explorer -ErrorAction SilentlyContinue | Where-Object SessionId -ne 0)) {
    'nobody is logged in to the Windows desktop'; exit 3
  }
  if (Get-Process LogonUI -ErrorAction SilentlyContinue) { 'the Windows desktop is locked'; exit 3 }
  schtasks.exe /query /tn winvm-interactive *> $null
  if ($LASTEXITCODE) { 'the winvm-interactive scheduled task is missing; rerun setup.ps1'; exit 3 }
  exit 0
}

if ($Mode -eq 'desktop') { $Job = (Get-Content -Raw "$root\current.txt").Trim() }
$dir = Join-Path $root "jobs\$Job"
$out = Join-Path $dir 'out'
$log = Join-Path $out 'console.log'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$env:WINVM_OUT = $out

# Route the job's downloads through the Mac's proxy on the UTM gateway when it answers.
$gateway = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1).NextHop
if ($gateway) {
  $tcp = [Net.Sockets.TcpClient]::new()
  if ($tcp.ConnectAsync($gateway, 7897).Wait(2000) -and $tcp.Connected) {
    $env:HTTP_PROXY = $env:HTTPS_PROXY = "http://${gateway}:7897"
    $env:NO_PROXY = 'localhost,127.0.0.1'
  }
  $tcp.Close()
}
Set-Location (Join-Path $dir 'work')

# The job stops at its first failing command, native or cmdlet, and its
# exit status becomes the job's.
$PSNativeCommandUseErrorActionPreference = $true
$global:LASTEXITCODE = 0
$code = 0
try {
  & (Join-Path $dir 'run.ps1') *>&1 | Tee-Object -FilePath $log
  $code = $LASTEXITCODE
} catch {
  $_ | Out-String | Tee-Object -FilePath $log -Append
  $code = if ($_.Exception -is [System.Management.Automation.NativeCommandExitException]) { $_.Exception.ExitCode } else { 1 }
}

$PSNativeCommandUseErrorActionPreference = $false
tar.exe -czf (Join-Path $dir 'result.tgz') -C $out .
Set-Content -LiteralPath (Join-Path $dir 'exit_code.tmp') -Value $code
Move-Item -LiteralPath (Join-Path $dir 'exit_code.tmp') -Destination (Join-Path $dir 'exit_code')
exit $code
