#!/bin/bash
source .venv/bin/activate

# 1. Clear Port 3000 to avoid "Address in use" error
echo "[SYSTEM] Clearing Port 3000..."
lsof -ti:3000 | xargs kill -9 2>/dev/null

# 2. Cleanup System Qt paths
unset QT_PLUGIN_PATH
unset QT_QPA_PLATFORM_PLUGIN_PATH

echo "--- Direct Launch: Display & Kiosk Console ---"
python src/main.py
