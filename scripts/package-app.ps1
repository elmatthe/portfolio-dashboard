$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

& "$root\scripts\build-backend.ps1"
& "$root\scripts\build-frontend.ps1"

Set-Location "$root\electron"
npm install
npm run pack:win

Write-Host "Installer(s) at $root\release"
