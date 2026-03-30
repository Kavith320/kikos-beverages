#!/bin/bash
source .venv/bin/activate

# 1. Clear Port 3000 for the Control Panel
echo "[SYSTEM] Clearing Port 3000..."
lsof -ti:3000 | xargs kill -9 2>/dev/null || true

# 2. Cleanup System Qt paths
unset QT_PLUGIN_PATH
unset QT_QPA_PLATFORM_PLUGIN_PATH

# 3. Handle Display Environment
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/$USER/.Xauthority}

# Automatically use the best platform (xcb or wayland)
unset QT_QPA_PLATFORM

echo "--- Unified Bootstrap: Display & Web Console ---"
python src/main.py
