#!/bin/bash

# Exit on any error
set -e

echo "Setting up Smart Interactive Retail Display for Linux Mint (Debian/Ubuntu based)..."

# 1. Update and install required system dependencies
echo "Installing necessary system packages (Python, venv, and Qt6 dependencies)..."
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg \
    libgl1 libglx-mesa0 libegl1 libxkbcommon-x11-0 \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-sync1 \
    libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 \
    qt6-wayland qt6-base-dev

# 2. Setup Virtual Environment
if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
else
    echo "Virtual environment already exists."
fi

# 3. Activate Virtual Environment and Install Python Dependencies
echo "Activating virtual environment..."
source .venv/bin/activate

echo "Installing Python dependencies..."
# Upgrade pip first
pip install --upgrade pip

# Install Python dependencies including the new Web Admin Server
pip install PySide6==6.7.3 pyserial pillow Flask Flask-Cors Flask-SocketIO

chmod +x run_linux.sh

echo "========================================="
echo "Configuring Full Kiosk Automation..."
echo "========================================="

# 1. Automate Autostart
APP_DIR=$(pwd)
echo "Creating Autostart entry pointing to: $APP_DIR/run_linux.sh"
mkdir -p ~/.config/autostart
cat << EOF > ~/.config/autostart/smart-display.desktop
[Desktop Entry]
Type=Application
Name=Smart Retail Display
Exec=bash -c "cd $APP_DIR && ./run_linux.sh"
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF

# 2. Automate Desktop Appearance Configs (For Linux Mint / Cinnamon)
if command -v gsettings >/dev/null 2>&1; then
    echo "Hiding desktop icons, taskbar, and setting a solid black background..."
    
    # Set background to pitch black
    gsettings set org.cinnamon.desktop.background picture-uri 'file://' || true
    gsettings set org.cinnamon.desktop.background primary-color '#000000' || true
    gsettings set org.cinnamon.desktop.background secondary-color '#000000' || true
    gsettings set org.cinnamon.desktop.background color-shading-type 'solid' || true
    
    # Disable all desktop icons
    gsettings set org.nemo.desktop computer-icon-visible false || true
    gsettings set org.nemo.desktop home-icon-visible false || true
    gsettings set org.nemo.desktop trash-icon-visible false || true
    gsettings set org.nemo.desktop volumes-visible false || true
    gsettings set org.nemo.desktop network-icon-visible false || true
    
    # Auto-hide the Cinnamon taskbar/panel
    gsettings set org.cinnamon panel-autohide "['1:true']" || true
    gsettings set org.cinnamon panels-autohide "['1:true']" || true
fi

# 3. Allow Reboot Without Password (CRITICAL for Remote Management)
echo "Adding passwordless reboot permission for current user: $USER..."
sudo bash -c "echo '$USER ALL=(ALL) NOPASSWD: /sbin/reboot, /sbin/shutdown, /usr/bin/systemctl reboot' > /etc/sudoers.d/smart-display-reboot"
sudo chmod 0440 /etc/sudoers.d/smart-display-reboot

echo "========================================="
echo "Setup & Kiosk Automation Complete!"
echo "Please make sure 'Auto-Login' is enabled for your user in the Linux settings."
echo "You can manually test the app now by running:"
echo "  ./run_linux.sh"
echo "Or just reboot the PC and it will start automatically!"
echo "========================================="
