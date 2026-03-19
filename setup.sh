#!/bin/bash
set -e

echo "========================================"
echo "  MOVAR CAPITAL — Setup Script"
echo "========================================"

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "[SETUP] Installing Redis (Linux)..."
    sudo apt-get update -qq
    sudo apt-get install -y redis-server
    sudo systemctl enable redis-server
    sudo systemctl start redis-server
    echo "[SETUP] Redis installed and running ✓"

elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo "[SETUP] Installing Redis (macOS via Homebrew)..."
    if ! command -v brew &>/dev/null; then
        echo "[ERROR] Homebrew not found. Install it first: https://brew.sh"
        exit 1
    fi
    brew install redis
    brew services start redis
    echo "[SETUP] Redis installed and running ✓"

else
    echo "[SETUP] Windows detected."
    echo "[SETUP] Install Redis for Windows via:"
    echo "        https://github.com/tporadowski/redis/releases"
    echo "        OR use WSL2 and re-run this script inside WSL"
    echo ""
    echo "[SETUP] Alternatively: install Docker and run:"
    echo "        docker run -d -p 6379:6379 redis:7-alpine"
fi

echo ""
echo "[SETUP] Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "[SETUP] Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt

echo ""
echo "[SETUP] Creating .env from template..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[SETUP] .env created — fill in your credentials before running"
else
    echo "[SETUP] .env already exists — skipping"
fi

echo ""
echo "[SETUP] Testing Redis connection..."
python3 -c "
import redis
r = redis.Redis(host='localhost', port=6379, db=0)
r.ping()
print('[SETUP] Redis connection OK ✓')
"

echo ""
echo "========================================"
echo "  Setup complete."
echo "  Next steps:"
echo "  1. Edit .env with your credentials"
echo "  2. source venv/bin/activate"
echo "  3. python main.py"
echo "========================================"
