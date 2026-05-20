#!/usr/bin/env bash
# Bundle the FastAPI backend into a single executable via PyInstaller.
# Output: ../backend-dist/backend (or backend.exe on Windows)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
python -m pip install pyinstaller

rm -rf build backend-dist
pyinstaller backend/main.py \
  --name backend \
  --onefile \
  --noconfirm \
  --clean \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols \
  --hidden-import uvicorn.protocols.http \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan \
  --hidden-import uvicorn.lifespan.on \
  --collect-all yfinance \
  --collect-all pandas \
  --collect-all openpyxl \
  --collect-all pdfplumber \
  --distpath backend-dist/ \
  --workpath build/

echo "Backend bundled at: backend-dist/"
