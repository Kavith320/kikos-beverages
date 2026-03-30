#!/bin/bash
source .venv/bin/activate

# 1. Clear Port 3000 for the Control Panel
echo "[SYSTEM] Clearing Port 3000..."
lsof -ti:3000 | xargs kill -9 2>/dev/null || true

# 2. Cleanup System Qt paths
unset QT_PLUGIN_PATH
unset QT_QPA_PLATFORM_PLUGIN_PATH

# 3. Handle Display Environment & Hardware Acceleration Fix
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/$USER/.Xauthority}

# Fix for Intel iHD_drv_video.so init failed: Fallback to stable software drivers
export LIBVA_DRIVER_NAME=i965
export QT_VIDEO_BACKEND=ffmpeg

# FFmpeg analytical depth for H.264 stability
export FFMPEG_ANALYZEDURATION=10000000
export FFMPEG_PROBESIZE=50000000

# Automatically use the best platform (xcb or wayland)
unset QT_QPA_PLATFORM

echo "--- Unified Bootstrap: Display & Web Console ---"

while true; do
    echo "[SYSTEM] Launching Display Engine..."
    python src/main.py
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo "[CLOSED] Application closed normally. Exiting loop."
        break
    elif [ $EXIT_CODE -eq 8 ]; then
        echo "[RESTART] Remote Reboot Signal Received. Hot-restarting..."
    else
        echo "[CRASH] App exited with code $EXIT_CODE. Attempting recovery in 2s..."
        sleep 2
    fi
done
