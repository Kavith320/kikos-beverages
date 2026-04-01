# Smart Interactive Retail Display

This project is a Linux-based interactive smart display software system. It receives product pickup signals from an ESP32 microcontroller and seamlessly displays corresponding media on a fullscreen, branded application.

## 1. Objective
To build a "lift-and-learn" retail display system. When a product is lifted from its stand, a sensor detects the action, signals the PC via an ESP32, and the PySide6 fullscreen application immediately shows a corresponding video, image, or product information.

## 2. Hardware Architecture
- **Input Side (Sensing):** Product stand, Reed switch + magnet (sensor), ESP32.
- **Output Side (Display):** Linux PC (running as a kiosk application) / macOS for development.
- **Communication Flow:** Sensor &rarr; ESP32 &rarr; USB/Serial &rarr; PC &rarr; Fullscreen PySide6 App.

## 3. Software Stack
- **Language:** Python 3
- **GUI Framework:** PySide6 (professional, flexible, excellent multimedia support)
- **Serial Communication:** `pyserial` (to communicate with the ESP32)
- **Media Support:** `pillow` (for images), PySide6 built-in multimedia capabilities for videos.

## 4. Directory Structure
```text
smart-display/
├── src/             # Application source code
│   └── main.py      # Main PySide6 entry point
├── assets/          # Static images (logo, etc.)
├── videos/          # Video media for products
└── config/          # Configuration files (mappings, device settings)
```

## 5. Linux Kiosk Setup (Mini PC)
This project is built for **Linux Mint / Debian** environments. The automated setup script handles everything:
1.  **System Preparation:** Installs Qt6, Python, and GPU acceleration drivers.
2.  **Kiosk Mode:** Hides desktop icons, taskbars, and sets a pitch-black background.
3.  **Autostart:** Configures the system to launch the app immediately on boot.
4.  **Remote Reboot:** Configures passwordless `sudo reboot` so you can restart from the web panel.

**Run the installer:**
```bash
chmod +x setup_linux.sh
./setup_linux.sh
```

## 6. Remote Management (Web Dashboard)
Once running, you can manage the display from any computer on the same network:
*   **URL:** `http://<KIOSK_IP>:3000`
*   **Default Password:** `admin123`
*   **Features:** Live console mirror, real-time trigger assignments, remote hardware reboot, and cloud-to-local sync.

### Level-Zero Control:
- **APPLY SYNC:** Instant soft reload (new media config).
- **UPDATE & RESTART:** Pulls from GitHub and reloads app.
- **REBOOT HW:** Fully restarts the Mini PC hardware.

## 7. Development (macOS)
The app is compatible with macOS for development.
1. Create venv: `python3 -m venv .venv`
2. Install: `pip install -r requirements.txt`
3. If you get a "Qt platform plugin" error, run:
   `pip install --force-reinstall PySide6`
4. Launch: `./run_app.sh`
