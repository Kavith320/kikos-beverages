#!/bin/bash
source .venv/bin/activate

# 1. Clear Port 3000 to avoid "Address in use" error
echo "[SYSTEM] Clearing Port 3000..."
lsof -ti:3000 | xargs kill -9 2>/dev/null

# 2. Cleanup System Qt paths
unset QT_PLUGIN_PATH
unset QT_QPA_PLATFORM_PLUGIN_PATH

# 3. Use the MIL-Spec location for plugins (inside your src folder)
# This forces macOS to bypass the venv lookup and use the local copy
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
export QT_QPA_PLATFORM_PLUGIN_PATH="$SCRIPT_DIR/src/plugins"
export QT_DEBUG_PLUGINS=1

echo "--- Direct Launch: Display & Web Console ---"
echo "[SYSTEM] Plugin Search Path: $QT_QPA_PLATFORM_PLUGIN_PATH"

python src/main.py
