#!/bin/bash
set -e

cd "$(dirname "$0")/.."

if [ ! -d "venv" ]; then
  echo "[DASHBOARD] venv not found — run ./setup.sh first"
  exit 1
fi

source venv/bin/activate

echo ""
echo "========================================"
echo "  MOVAR CAPITAL — Dashboard"
echo "  http://localhost:8000"
echo "========================================"
echo ""

python3 -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8000 --reload
