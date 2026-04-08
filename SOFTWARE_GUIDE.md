# Smart Retail Display - Software Features & Operation Guide

## 1. Core Software Features

### 📡 Real-time Display Engine (PySide6)
- **Fullscreen Mode:** Automatically runs in a borderless, fullscreen kiosk mode on Linux/macOS.
- **Dynamic Transition System:** Features smooth "dip-to-black" transitions between idle states and product videos.
- **Multi-Media Support:** Optimized for 4K H.264 video playback using GPU-accelerated hardware decoders.
- **Hardware Agnostic:** Automatically handles audio output switching and multi-monitor setups.

### 🎮 Smart Trigger Mapping
- **Input System:** Responds to signals from the Hardware (Reed Sensors + ESP32) to trigger specific media.
- **Software Slots:** Supports 9 distinct trigger slots (1-9) that can be dynamically mapped to any uploaded media file.
- **Idle State:** Features a persistent looping idle video (e.g., branding or "Lift to Learn" instructions) that plays when no product is picked up.

### 🌐 Centralized Web Control Panel
- **Remote Access:** Manage the kiosk system via a web browser at `http://<Kiosk_IP>:3000`.
- **Integrated Live Mirror:** Watch the kiosk playback in real-time from anywhere on the local network using a low-latency screenshot engine.
- **Remote Configuration:** Instantly change video assignments, adjust volume, and switch display monitors without touching the hardware.

### 📂 Media Management & Assets
- **Drag-and-Drop Uploads:** Easily upload new product videos directly through the web dashboard.
- **Video Library:** Cloud-to-local synchronization and simple media deletion.
- **Branding Assets:** Customizable boot logo and splash screen during system initialization.

### 📊 Playback Analytics
- **Activity Logging:** Automatically logs every product pickup event with a timestamp and filename.
- **Data Export:** View the last 100 events in the browser or download a full `.csv` report for marketing analysis.

### 🛠️ Remote System Maintenance
- **GIT Cloud Sync:** Update the kiosk software to the latest version directly from GitHub via the dashboard.
- **Hardware Maintenance:** Remote "Soft-Restart" (GUI Only) and "Fixed-Reboot" (Full OS Hardware Restart) capabilities.
- **IP OSD:** On boot, the system briefly displays its local IP address on the screen for easy admin discovery.

---

## 2. Operation Guide

### 🚀 Starting the System
1. **Linux (Production):** Ensure all dependencies are installed using `setup_linux.sh`. The app is configured to start automatically on boot. To manual start, run:
   ```bash
   ./run_linux.sh
   ```
2. **First Boot:** On initial launch, note the IP address shown in the floating notification at the top of the screen.

### 🔐 Accessing the Admin Dashboard
1. Open a web browser on any computer connected to the same network.
2. Navigate to `http://<KIOSK_IP>:3000`.
3. Log in using the default credentials:
   - **Username:** `admin`
   - **Password:** `admin123`

### 📤 Uploading & Mapping Media
1. **Upload:** Click the **UPLOAD MEDIA** button in the dashboard and select your video files (`.mp4` recommended).
2. **IDLE Setup:** Right-click any video in the library and select **"Set as Idle"**.
3. **Trigger Mapping:**
   - Select a video from the media library (it will glow with an accent color).
   - Click one of the slots (1-9) in the **Trigger Matrix**.
   - Confirm the mapping in the pop-up modal.

### 🔊 Adjusting Volume & Audio Output
1. Use the **Volume Slider** in the "Media & Audio" section to adjust levels.
2. Select the correct **Audio Output** (e.g., HDMI or Headphones) from the dropdown list.
3. The changes are applied instantly across all active media players.

### ⚙️ Performing Updates & Restarts
- **GIT UPDATE:** Downloads the latest software version and reloads the application.
- **APPLY & RESTART:** If the GUI appears stuck or settings aren't syncing, use this button for a soft reload.
- **REBOOT HW:** Performs a full system restart. Essential if the hardware (ESP32 or Display) is disconnected.

### 📈 Exporting Analytics
1. Click the **ANALYTICS** button in the header.
2. To download the data for Excel, click **DOWNLOAD CSV**.
3. To reset logs for a new month or campaign, click **CLEAR LOGS**.

---

## 3. Hardware Integration (Lift-and-Learn)
- **Serial Connection:** Ensure the ESP32 is plugged into the PC via USB.
- **Signal Logic:** The system listens for the following serial inputs (or keyboard presses for manual testing):
  - `1-9`: Triggers the corresponding mapped slot.
  - `0` or `SPACEBAR`: Forces the system back to the **Idle Screen**.
  - `ESC`: Exits the application (for administrative use only).
