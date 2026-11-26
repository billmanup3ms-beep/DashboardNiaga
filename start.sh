#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8080}"
echo "Starting Dashboard Piutang UP3 Makassar Selatan on http://localhost:${PORT}"
python3 server.py --port "${PORT}"
