# Windows equivalent of build-backend.sh. Bundles the FastAPI backend with PyInstaller.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

py -m pip install --upgrade pip
py -m pip install -r backend/requirements.txt
py -m pip install pyinstaller

if (Test-Path "backend-dist") { Remove-Item -Recurse -Force backend-dist }
if (Test-Path "build") { Remove-Item -Recurse -Force build }

py -m PyInstaller backend/main.py `
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
  --distpath backend-dist/ `
  --workpath build/

Write-Host "Backend bundled at backend-dist\backend.exe"
