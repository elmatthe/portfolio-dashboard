# Double-click-friendly PowerShell launcher.
# Prefers the installed app (Start Menu / NSIS install), then falls back to the
# unpacked build under release\win-unpacked\, then prints a clear error.
$installed = "$env:LOCALAPPDATA\Programs\Portfolio Dashboard\Portfolio Dashboard.exe"
$unpacked  = Join-Path $PSScriptRoot "release\win-unpacked\Portfolio Dashboard.exe"

if (Test-Path $installed) { Start-Process $installed; exit }
if (Test-Path $unpacked)  { Start-Process $unpacked;  exit }

Write-Host "Portfolio Dashboard not found." -ForegroundColor Red
Write-Host "Run the installer at release\Portfolio Dashboard Setup 0.3.0.exe first," -ForegroundColor Red
Write-Host "or build it with: pwsh scripts\build-windows.ps1" -ForegroundColor Red
