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

## 5. Setup & Installation
It is highly recommended to run this project inside a Python virtual environment to isolate dependencies.
1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   ```
2. Activate the virtual environment:
   - macOS/Linux: `source .venv/bin/activate`
   - Windows: `.venv\Scripts\activate`
3. Install required libraries:
   ```bash
   pip install PySide6 pyserial pillow
   ```

## 6. How to Run the Application
Ensure your virtual environment is activated, then run the application from the root directory:

```bash
source .venv/bin/activate
python src/main.py
```

### Keyboard Controls (Simulation Mode)
Since the ESP32 integration may not be connected during software testing, you can simulate product interactions:
- **`1`, `2`, `3`, `4`**: Trigger product 1, 2, 3, or 4 video sequences.
- **`0` or `Space`**: Return to the idle screen.
- **`Esc`**: Exit the application.

## 7. Troubleshooting

### macOS: Qt Platform Plugin "cocoa" Error
While developing on macOS, you may encounter a crash upon running `main.py` that states:
> `qt.qpa.plugin: Could not find the Qt platform plugin "cocoa" in ""`
> `This application failed to start because no Qt platform plugin could be initialized.`

**Cause:** 
This is a common issue with older PySide6 distributions (e.g., version `6.6.3`) where the `libqcocoa.dylib` fails to properly load on newer macOS architectures or Apple Silicon inside an isolated virtual environment.

**The Fix:**
Forcefully reinstall/upgrade PySide6 to the latest version (e.g., `6.11.0` or higher) inside your active virtual environment. This forces pip to download the updated macOS universal binaries containing the properly linked plugins:

```bash
source .venv/bin/activate
pip install --force-reinstall PySide6
```
