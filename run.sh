#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Build React frontend if Node.js is available and not yet built
if [ ! -d "frontend/dist" ] && command -v node &>/dev/null; then
  echo "==> 构建前端 (首次运行)"
  (cd frontend && npm install --silent 2>/dev/null && npm run build)
fi

PYTHONPATH=src python3 main.py
