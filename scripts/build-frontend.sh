#!/usr/bin/env bash
# Build the React frontend into ../dist/ via Vite.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"

npm install
npm run build

mkdir -p "$ROOT/dist"
rm -rf "$ROOT/dist"/*
cp -R dist/* "$ROOT/dist/"

echo "Frontend bundled at: $ROOT/dist"
