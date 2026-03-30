import sys
import os
import json
import socket
import threading
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QStackedWidget, QGraphicsOpacityEffect, QFrame
from PySide6.QtCore import Qt, QUrl, QTimer, QPropertyAnimation, QPoint, QEasingCurve, Signal, Slot
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget

# Import our web server logic
from web_server import run_server

class SmartDisplayApp(QMainWindow):
    # Signal to handle UI updates from the Flask thread safely
    config_updated = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Retail Display - Web Admin Integrated")
        self.resize(1024, 768)
        
        # Paths
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.video_folder = os.path.join(base_dir, "videos")
        self.assets_folder = os.path.join(base_dir, "assets")
        self.config_path = os.path.join(base_dir, "config", "media_config.json")
        
        # Audio/State Consistency
        self.current_volume = 1.0 # 0.0 to 1.0
        self.target_audio_device = ""
        
        self.stacked_widget = QStackedWidget(self)
        self.setCentralWidget(self.stacked_widget)
        
        # IP Notification Widget (OSD)
        self.ip_box = QFrame(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.ip_box.setObjectName("ip_notification")
        self.ip_box.setFixedSize(400, 80)
        self.ip_box.setStyleSheet("""
            #ip_notification {
                background-color: rgba(10, 10, 10, 240);
                border: 3px solid #00d4ff;
                border-radius: 15px;
            }
        """)
        self.ip_box.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        ip_layout = QVBoxLayout(self.ip_box)
        self.ip_label = QLabel("Detecting Network...")
        self.ip_label.setStyleSheet("color: #00d4ff; font-family: 'Courier New'; font-weight: bold; font-size: 20px;")
        self.ip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ip_layout.addWidget(self.ip_label)
        self.ip_box.hide()
        
        # Black Overlay for Transitions
        self.black_overlay = QWidget(self)
        self.black_overlay.setStyleSheet("background-color: #000000;")
        self.black_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay_opacity = QGraphicsOpacityEffect(self.black_overlay)
        self.black_overlay.setGraphicsEffect(self.overlay_opacity)
        self.black_overlay.hide()
        
        # App State
        self.screens = {}
        self.players = {}
        self.current_screen_id = None
        self.pending_screen_id = None
        self.mappings = {} # Key -> Filename
        
        # Load Initial Config and Setup UI
        self._load_and_setup_media()
        
        # Setup reload signal
        self.config_updated.connect(self._on_remote_config_update)
        # Refresh current hardware to server
        self._refresh_audio_devices()
        
        # Setup Live Mirror Heartbeat (Capture every 100ms = 10fps)
        self.mirror_timer = QTimer(self)
        self.mirror_timer.timeout.connect(self.capture_frame)
        self.mirror_timer.start(100)
        
        # Boot sequence: Show logo
        if "logo" in self.screens:
            self.stacked_widget.setCurrentWidget(self.screens["logo"])
            self.current_screen_id = "logo"
            QTimer.singleShot(2500, self._start_logo_fade)

    def _load_and_setup_media(self):
        """Loads configuration and populates the stacked widget."""
        print("[INIT] Loading media configuration...")
        
        # Clear existing
        for player in self.players.values():
            player.stop()
        
        while self.stacked_widget.count() > 0:
            widget = self.stacked_widget.widget(0)
            self.stacked_widget.removeWidget(widget)
            widget.deleteLater()
            
        self.screens = {}
        self.players = {}
        
        # Load Config
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                config = json.load(f)
        else:
            config = {"idle": "idle.mp4", "mappings": {}}
        
        # Save to self for global access
        self.config = config
        self.mappings = config.get("mappings", {})
        idle_file = config.get("idle", "idle.mp4")
        
        # Apply Base Audio State from Config
        audio_conf = self.config.get("audio", {})
        self.current_volume = audio_conf.get("volume", 1.0)
        self.target_audio_device = audio_conf.get("device", "")
        
        # 0. Always create/re-create Logo screen
        self._create_logo_screen()
        
        # 1. Setup Idle Screen
        self._add_video_screen("idle", idle_file, "Idle Screen\n(No idle video assigned)", "#1a1a1a", loop=True)
        
        # 2. Setup Mapped Screens
        for key, filename in self.mappings.items():
            screen_id = f"custom_{key}"
            self._add_video_screen(screen_id, filename, f"Video: {filename}\nBound to: {key}", "#002244", loop=False)

        # 3. Synchronize Web Server Visuals
        import web_server
        web_server.current_volume = int(self.current_volume * 100)
        web_server.audio_devices = [d.description() for d in QMediaDevices.audioOutputs()]

    @Slot(str)
    def _on_remote_config_update(self, signal_data=""):
        """Called when web signals a config change, manual trigger, or audio update."""
        if signal_data.startswith("TRIGGER:"):
            parts = signal_data.split(":")
            cmd = parts[1]
            val = parts[2] if len(parts) > 2 else None
            
            if cmd == "idle": self.switch_to_screen("idle")
            elif cmd == "volume" and val: self._set_global_volume(float(val))
            elif cmd == "device" and val: self._set_audio_device(val)
            elif cmd == "RESTART": 
                print("[SYSTEM] Full process restart signal received.")
                QApplication.exit(8) # Signal code 8 for bash restart
                return
            else: self.switch_to_screen(f"custom_{cmd}")
            return

        print("[REMOTE] Configuration reload requested...")
        self._load_and_setup_media()
        if self.current_screen_id != "logo":
            self.switch_to_screen("idle")

    def _refresh_audio_devices(self):
        """Broadcasts available audio hardware to the web console."""
        import web_server
        devices = QMediaDevices.audioOutputs()
        web_server.audio_devices = [d.description() for d in devices]
        
    def _set_global_volume(self, level):
        """Sets the volume (0.0 to 1.0) across all players."""
        self.current_volume = level
        print(f"[AUDIO] Volume sync: {int(level*100)}%")
        for player in self.players.values():
            if hasattr(player, 'audioOutput'):
                player.audioOutput().setVolume(level)
        import web_server
        web_server.current_volume = int(level * 100)

    def _set_audio_device(self, device_name):
        """Switches the output hardware for all active media players."""
        self.target_audio_device = device_name
        target_device = None
        for d in QMediaDevices.audioOutputs():
            if d.description() == device_name:
                target_device = d
                break
        
        if target_device:
            print(f"[AUDIO] Speaker Switch: {device_name}")
            for player in self.players.values():
                if hasattr(player, 'audioOutput'):
                    player.audioOutput().setDevice(target_device)

    def _create_logo_screen(self):
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setStyleSheet("background-color: #000000;")
        
        label = QLabel("FUTURE TECH LOGO\n(booting...)")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #ffffff; font-size: 40px; font-weight: bold;")
        
        logo_path = os.path.join(self.assets_folder, "logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            label.setPixmap(pixmap.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            label.setText("") 
            
        layout.addWidget(label)
        widget.setLayout(layout)
        self.screens["logo"] = widget
        self.stacked_widget.addWidget(widget)

    def _start_logo_fade(self):
        self._perform_dip_to_black("idle")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.black_overlay.setGeometry(0, 0, self.width(), self.height())

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except: return "No Network"

    def show_ip_notification(self):
        ip_addr = self._get_local_ip()
        self.ip_label.setText(f"ADMIN PORT: 3000\nURL: {ip_addr}:3000")
        screen_geo = self.screen().geometry()
        target_x = screen_geo.center().x() - (self.ip_box.width() // 2)
        start_pos = QPoint(target_x, -100)
        end_pos = QPoint(target_x, 60)
        self.ip_box.move(start_pos)
        self.ip_box.show()
        self.ip_anim = QPropertyAnimation(self.ip_box, b"pos")
        self.ip_anim.setDuration(1000)
        self.ip_anim.setStartValue(start_pos)
        self.ip_anim.setEndValue(end_pos)
        self.ip_anim.setEasingCurve(QEasingCurve.Type.OutBounce)
        self.ip_anim.start()
        QTimer.singleShot(10000, self.hide_ip_notification)

    def hide_ip_notification(self):
        start_pos = self.ip_box.pos()
        end_pos = QPoint(start_pos.x(), -100)
        self.ip_anim = QPropertyAnimation(self.ip_box, b"pos")
        self.ip_anim.setDuration(800)
        self.ip_anim.setStartValue(start_pos)
        self.ip_anim.setEndValue(end_pos)
        self.ip_anim.setEasingCurve(QEasingCurve.Type.InBack)
        self.ip_anim.finished.connect(self.ip_box.hide)
        self.ip_anim.start()

    def _add_video_screen(self, screen_id, filename, fallback_text, bg_color, loop):
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setStyleSheet(f"background-color: {bg_color};")
        
        video_path = os.path.join(self.video_folder, filename) if filename else ""
        if filename and os.path.exists(video_path):
            video_widget = QVideoWidget()
            audio_output = QAudioOutput(widget)
            player = QMediaPlayer(widget)
            player.setVideoOutput(video_widget)
            player.setAudioOutput(audio_output)
            audio_output.setVolume(1.0)
            player.setSource(QUrl.fromLocalFile(video_path))
            
            # Apply Persistent Audio settings to the new player
            audio_output.setVolume(self.current_volume)
            if self.target_audio_device:
                for d in QMediaDevices.audioOutputs():
                    if d.description() == self.target_audio_device:
                        audio_output.setDevice(d)
                        break
            
            if loop:
                player.setLoops(-1)
            else:
                player.mediaStatusChanged.connect(lambda status, s_id=screen_id: self._on_media_status_changed(status, s_id))
                
            layout.addWidget(video_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            self.players[screen_id] = player
        else:
            label = QLabel(fallback_text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: #ffffff; font-size: 24px; font-weight: bold;")
            layout.addWidget(label)
        
        widget.setLayout(layout)
        self.screens[screen_id] = widget
        self.stacked_widget.addWidget(widget)

    def switch_to_screen(self, screen_id):
        if screen_id not in self.screens: return
        if self.current_screen_id == "logo" and screen_id != "idle": return
        if self.current_screen_id == screen_id: return 
        self._perform_dip_to_black(screen_id)

    def _perform_dip_to_black(self, new_screen_id):
        self.pending_screen_id = new_screen_id
        self.black_overlay.show()
        self.black_overlay.raise_()
        self.fade_anim = QPropertyAnimation(self.overlay_opacity, b"opacity")
        self.fade_anim.setDuration(400)
        self.fade_anim.setStartValue(self.overlay_opacity.opacity())
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.finished.connect(self._on_black_overlay_solid)
        self.fade_anim.start()

    def _on_black_overlay_solid(self):
        if self.current_screen_id in self.players:
            self.players[self.current_screen_id].pause()
            
        self.stacked_widget.setCurrentWidget(self.screens[self.pending_screen_id])
        self.current_screen_id = self.pending_screen_id
        
        if self.current_screen_id in self.players:
            if self.current_screen_id != "idle":
                self.players[self.current_screen_id].setPosition(0)
            self.players[self.current_screen_id].play()
            
        # Update Web Server State
        import web_server
        # Strip prefixes for cross-system syncing
        clean_id = self.current_screen_id.replace("custom_", "")
        web_server.current_playing = clean_id
            
        self.fade_anim = QPropertyAnimation(self.overlay_opacity, b"opacity")
        self.fade_anim.setDuration(400)
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.finished.connect(self.black_overlay.hide)
        
        if self.current_screen_id == "idle" and not hasattr(self, "_ip_shown"):
            self._ip_shown = True
            self.fade_anim.finished.connect(lambda: QTimer.singleShot(500, self.show_ip_notification))
            
        self.fade_anim.start()

    def capture_frame(self):
        """Robustly captures the entire physical screen for the mirror."""
        try:
            # Capture the absolute physical screen (captures hardware video overlays)
            screen = QApplication.primaryScreen()
            if not screen: return
            
            pixmap = screen.grabWindow(0) # 0 = entire screen
            # Downscale for low-latency web playback
            pixmap = pixmap.scaled(480, 270, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
            
            from PySide6.QtCore import QBuffer, QIODevice
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buffer, "JPG", 50)
            
            import web_server
            web_server.latest_screenshot = buffer.data().data()
        except Exception as e:
            print(f"[MIRROR] Capture error: {e}")

    def _on_media_status_changed(self, status, screen_id):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.current_screen_id == screen_id and screen_id != "idle":
                self.switch_to_screen("idle")

    def keyPressEvent(self, event):
        if self.current_screen_id == "logo": return
            
        key_text = event.text()
        if key_text in self.mappings:
            self.switch_to_screen(f"custom_{key_text}")
        elif event.key() == Qt.Key.Key_0 or event.key() == Qt.Key.Key_Space:
            self.switch_to_screen("idle")
        elif event.key() == Qt.Key.Key_Escape:
            self.close()

if __name__ == "__main__":
    # 1. Configuration Check
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "media_config.json")
    
    # 2. Start Web Server Thread IMMEDIATELY
    # This ensures the control panel works even if the GUI hasn't started yet
    def dummy_callback(): print("[REMOTE] Signal received, but GUI not ready.")
    web_thread = threading.Thread(target=run_server, args=(dummy_callback,), daemon=True)
    web_thread.start()
    
    print("--- [SURVIVOR MODE] Web Server Started on Port 3000 ---")
    
    # 3. Attempt GUI Launch
    app = QApplication(sys.argv)
    app.setOverrideCursor(Qt.CursorShape.BlankCursor)
    window = SmartDisplayApp()
    
    # Update the web server's callback to the real one now that GUI is ready
    import web_server
    web_server.on_update_callback = window.config_updated.emit
    
    window.showFullScreen()
    sys.exit(app.exec())
