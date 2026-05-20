# Single-command Windows release build.
# Produces release\Portfolio Dashboard Setup x.y.z.exe (NSIS installer, x64).
#
# Steps:
#   1. PyInstaller        → backend-dist\backend.exe (~117 MB single-file)
#   2. Vite build         → frontend\dist\, then staged into project_root\dist\
#   3. 7za-shim install   → works around electron-builder's macOS-dylib symlink issue
#                           (electron-builder's bundled 7-Zip 21.07 tries to create
#                           symlinks for darwin dylibs in winCodeSign-2.6.0.7z; on
#                           Windows that needs admin or Developer Mode. We replace
#                           7za.exe with a tiny shim that adds -x!darwin/10.12/lib.)
#   4. electron-builder   → release\Portfolio Dashboard Setup x.y.z.exe (~187 MB)
#
# Usage from any shell:
#   pwsh scripts\build-windows.ps1
#
# Requires: Python 3.11+, Node 18+, PowerShell 5+.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (Test-Path "$env:ProgramFiles\nodejs\node.exe") {
    $env:PATH = "$env:ProgramFiles\nodejs;" + $env:PATH
}

function Step($title) {
    Write-Host ""
    Write-Host ("=" * 64) -ForegroundColor Cyan
    Write-Host "  $title" -ForegroundColor Cyan
    Write-Host ("=" * 64) -ForegroundColor Cyan
}

# ---------- 1. Backend (PyInstaller) ----------
Step "1/4  PyInstaller -> backend-dist\backend.exe"

py -m pip install --quiet -r backend\requirements.txt
py -m pip install --quiet pyinstaller

if (Test-Path "backend-dist") { Remove-Item -Recurse -Force backend-dist }
if (Test-Path "build")        { Remove-Item -Recurse -Force build }

py -m PyInstaller backend\main.py `
  --name backend `
  --onefile `
  --noconfirm `
  --clean `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols `
  --hidden-import uvicorn.protocols.http `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan `
  --hidden-import uvicorn.lifespan.on `
  --collect-all yfinance `
  --collect-all pandas `
  --collect-all openpyxl `
  --collect-all pdfplumber `
  --collect-all reportlab `
  --collect-all matplotlib `
  --distpath backend-dist\ `
  --workpath build\

if (-not (Test-Path "backend-dist\backend.exe")) {
    throw "PyInstaller failed: backend-dist\backend.exe not produced"
}
$size = [math]::Round((Get-Item "backend-dist\backend.exe").Length / 1MB, 1)
Write-Host "  OK backend.exe ($size MB)" -ForegroundColor Green

# ---------- 2. Frontend (Vite) ----------
Step "2/4  Vite -> dist\"

Set-Location "$root\frontend"
if (-not (Test-Path "node_modules")) { npm install }
npm run build
Set-Location $root

# Stage frontend\dist into project_root\dist so the electron-builder config
# (which uses ../dist/ as a relative path from electron\) resolves correctly.
if (Test-Path "$root\dist") { Remove-Item -Recurse -Force "$root\dist" }
New-Item -ItemType Directory -Force "$root\dist" | Out-Null
Copy-Item -Recurse "$root\frontend\dist\*" "$root\dist"

if (-not (Test-Path "$root\dist\index.html")) {
    throw "Vite build failed: $root\dist\index.html not produced"
}
Write-Host "  OK dist\index.html staged" -ForegroundColor Green

# ---------- 3. electron-builder install + 7za shim ----------
Step "3/4  electron deps + 7za shim"

Set-Location "$root\electron"
if (-not (Test-Path "node_modules")) { npm install }
Set-Location $root

# Install the symlink-skipping 7za shim. Only needed if the original 7za.exe
# hasn't already been replaced (i.e. on a fresh checkout).
$bin    = "$root\electron\node_modules\7zip-bin\win\x64"
$sevenz = "$bin\7za.exe"
$real   = "$bin\7za-real.exe"

if (Test-Path $sevenz) {
    $shimSize = (Get-Item $sevenz).Length
    # Real 7za is ~1.2 MB; our PyInstaller-bundled shim is ~7 MB. If size differs
    # from the real binary, assume the shim is already installed.
    if (-not (Test-Path $real)) {
        Move-Item $sevenz $real
        py -m PyInstaller scripts\_7za_shim.py `
            --name 7za --onefile --noconfirm `
            --distpath $bin `
            --workpath build-shim\ `
            --specpath build-shim\
        if (-not (Test-Path $sevenz)) { throw "Failed to install 7za shim" }
        Write-Host "  OK 7za shim installed (real preserved as 7za-real.exe)" -ForegroundColor Green
    } else {
        Write-Host "  OK 7za shim already in place" -ForegroundColor Green
    }
}

# ---------- 4. electron-builder ----------
Step "4/4  electron-builder -> release\"

if (Test-Path "$root\release") { Remove-Item -Recurse -Force "$root\release" }

Set-Location "$root\electron"
npx electron-builder --win --config electron-builder.yml
Set-Location $root

$installer = Get-ChildItem "$root\release\*.exe" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "Setup" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $installer) {
    throw "electron-builder failed: no Setup .exe found under release\"
}

Write-Host ""
Write-Host ("=" * 64) -ForegroundColor Green
Write-Host "  Build complete" -ForegroundColor Green
Write-Host ("=" * 64) -ForegroundColor Green
Write-Host "  Installer: $($installer.FullName)"
Write-Host "  Size:      $([math]::Round($installer.Length / 1MB, 1)) MB"
Write-Host ""
Write-Host "  Run the installer with:"
Write-Host "    Start-Process `"$($installer.FullName)`""
Write-Host "  Or double-click it in Explorer."
