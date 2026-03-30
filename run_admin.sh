#!/bin/bash
source .venv/bin/activate
echo "[SYSTEM] Starting Standalone Admin Server on Port 3000..."
export FLASK_APP=src/web_server.py
python src/web_server.py
