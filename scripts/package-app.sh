#!/usr/bin/env bash
# Full release pipeline: backend → frontend → electron-builder.
# Produces ../release/Portfolio Dashboard-x.y.z.dmg (mac) or Setup x.y.z.exe (win) — version comes from electron/package.json.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

bash scripts/build-backend.sh
bash scripts/build-frontend.sh

cd electron
npm install
npm run pack

echo "Installer(s) at: $ROOT/release/"
