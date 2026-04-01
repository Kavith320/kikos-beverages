import os
import json
import socket
import logging
from flask import Flask, jsonify, request, send_from_directory, session, redirect, url_for
from flask_cors import CORS
from functools import wraps
from werkzeug.utils import secure_filename

# Disable verbose logging to keep terminal clean
log = logging.getLogger('werkzeug')
log.setLevel(logging.INFO) # Show requests for debugging

app = Flask(__name__)
# Use a consistent secret key for sessions
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "kiosk-smart-display-v5")
CORS(app, supports_credentials=True)

# Admin credentials
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# --- DIRECTORY SETUP ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_FOLDER = os.path.join(BASE_DIR, "videos")
CONFIG_PATH = os.path.join(BASE_DIR, "config", "media_config.json")
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'mkv', 'avi'}

if not os.path.exists(VIDEO_FOLDER):
    os.makedirs(VIDEO_FOLDER)

# Global states
on_update_callback = None
latest_screenshot = None
current_playing = "idle"
audio_devices = []
current_volume = 100

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_config():
    config = {"idle": "", "mappings": {}, "aliases": {}, "audio": {"volume": 1.0, "device": ""}}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                disk_config = json.load(f)
                config.update(disk_config)
                # Ensure nested audio exists even if disk_config updated
                if "audio" not in config:
                    config["audio"] = {"volume": 1.0, "device": ""}
        except: pass
    return config

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)
    if on_update_callback:
        on_update_callback("")

# --- API ENDPOINTS ---

@app.route('/api/login', methods=['POST'])
def api_login():
    password = request.json.get('password')
    if password == ADMIN_PASSWORD:
        session['logged_in'] = True
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

@app.route('/api/logout')
def api_logout():
    session.pop('logged_in', None)
    return redirect(url_for('login_page'))

def get_ip():
    """Robust local IP detection without external dependencies"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

@app.route('/api/status', methods=['GET'])
@login_required
def get_status():
    try:
        config = load_config()
        all_files = sorted([f for f in os.listdir(VIDEO_FOLDER) if allowed_file(f)])
        return jsonify({
            "config": config,
            "media": all_files,
            "current_playing": current_playing,
            "audio": {
                "devices": audio_devices,
                "volume": current_volume
            },
            "system": {
                "os": "Linux" if os.name != 'nt' else "Windows",
                "ip": get_ip()
            }
        })
    except Exception as e:
        print(f"[API ERROR] Status: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_video():
    if 'video' not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files['video']
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(VIDEO_FOLDER, filename))
        return jsonify({"success": True, "filename": filename})
    return jsonify({"error": "Invalid format"}), 400

@app.route('/api/delete', methods=['POST'])
@login_required
def delete_video():
    filename = request.json.get('filename')
    path = os.path.join(VIDEO_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)
        config = load_config()
        if config["idle"] == filename: config["idle"] = ""
        config["mappings"] = {k: v for k, v in config["mappings"].items() if v != filename}
        save_config(config)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/update-mapping', methods=['POST'])
@login_required
def update_mapping():
    data = request.json
    key = data.get('key')
    filename = data.get('filename')
    is_idle = data.get('is_idle', False)
    
    config = load_config()
    if is_idle:
        config["idle"] = filename
    else:
        config["mappings"][str(key)] = filename
    
    save_config(config)
    return jsonify({"success": True})

@app.route('/api/apply', methods=['POST'])
@login_required
def apply_config():
    if on_update_callback:
        # Send empty string for "Soft Reload" (config only)
        # To do a hard restart, use /api/update-system or similar
        on_update_callback("") 
        return jsonify({"success": True, "message": "GUI config reloaded"})
    return jsonify({"error": "GUI not connected"}), 503

def gen_frames():
    """MJPEG Streaming Generator"""
    import time
    while True:
        try:
            if latest_screenshot:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + latest_screenshot + b'\r\n')
            time.sleep(0.08) # ~12fps max
        except GeneratorExit:
            break
        except Exception:
            break

@app.route('/api/stream')
@login_required
def get_stream():
    from flask import Response
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/trigger', methods=['POST'])
@login_required
def trigger_video():
    global current_playing
    key = request.json.get('key')
    
    # Update state immediately for UI feedback
    current_playing = str(key)
    
    if on_update_callback:
        # We'll hijack the callback to pass a key trigger
        # The main app needs to handle this specific string format
        on_update_callback(f"TRIGGER:{key}")
        return jsonify({"success": True})
    return jsonify({"error": "GUI not connected"}), 503

@app.route('/api/audio', methods=['POST'])
@login_required
def update_audio():
    data = request.json
    volume = data.get('volume')
    device = data.get('device')
    
    config = load_config()
    if "audio" not in config: config["audio"] = {"volume": 1.0, "device": ""}
    
    if volume is not None:
        config["audio"]["volume"] = float(volume) / 100.0
    if device is not None:
        config["audio"]["device"] = device
    save_config(config)

    if on_update_callback:
        if volume is not None:
            on_update_callback(f"TRIGGER:volume:{config['audio']['volume']}")
        if device is not None:
            on_update_callback(f"TRIGGER:device:{device}")
        return jsonify({"success": True})
    return jsonify({"error": "GUI not connected"}), 503

@app.route('/api/remove-mapping', methods=['POST'])
@login_required
def remove_mapping():
    key = request.json.get('key')
    config = load_config()
    if str(key) in config["mappings"]:
        del config["mappings"][str(key)]
        save_config(config)
        return jsonify({"success": True})
    return jsonify({"error": "Not mapped"}), 400

@app.route('/api/reboot', methods=['POST'])
@login_required
def reboot_system():
    import subprocess
    try:
        # Try different reboot methods known to work on various Linux flavors
        # and Mac dev environments
        print("[SYSTEM] Attempting Hardware Reboot...")
        # Path 1: standard systemd
        subprocess.Popen(["systemctl", "reboot"])
        # Path 2: legacy sudo reboot (often with NOPASSWD)
        subprocess.Popen(["sudo", "reboot"])
        # Path 3: direct reboot
        subprocess.Popen(["reboot"])
        return jsonify({"success": True, "message": "System reboot sequence initiated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/update-system', methods=['POST'])
@login_required
def update_system():
    import subprocess
    try:
        # 1. Pull latest code
        pull_res = subprocess.run(["git", "pull", "origin", "main"], 
                                 capture_output=True, text=True, check=True)
        
        # 2. Trigger restart via the main app callback
        # This will exit the python process, and run_linux.sh will restart it.
        if on_update_callback:
            on_update_callback("TRIGGER:RESTART")
            return jsonify({
                "success": True, 
                "message": "System updated & restarting...",
                "git_output": pull_res.stdout
            })
        return jsonify({"success": True, "message": "Updated, but GUI not connected to restart."})
        
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "error": f"Git pull failed: {e.stderr}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- STATIC CONTENT ---

@app.route('/login')
def login_page():
    try:
        login_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "login.html")
        with open(login_path, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error loading login page: {str(e)}", 500

@app.route('/api/thumbnail/<filename>')
@login_required
def get_thumbnail(filename):
    """
    Attempts to generate a thumbnail using ffmpeg if available.
    Falls back to a colored placeholder if it fails or ffmpeg is missing.
    """
    import subprocess
    thumb_dir = os.path.join(VIDEO_FOLDER, ".thumbnails")
    if not os.path.exists(thumb_dir):
        os.makedirs(thumb_dir)
    
    thumb_path = os.path.join(thumb_dir, f"{filename}.jpg")
    
    # Try using ffmpeg if the thumbnail doesn't exist
    if not os.path.exists(thumb_path):
        video_path = os.path.join(VIDEO_FOLDER, filename)
        try:
            # Capture the 1st second frame
            res = subprocess.run([
                "ffmpeg", "-y", "-i", video_path, 
                "-ss", "00:00:01", "-vframes", "1", 
                "-vf", "scale=120:-1", # Small preview
                thumb_path
            ], capture_output=True, timeout=2)
            
            if res.returncode != 0:
                # ffmpeg failed or command doesn't exist
                return send_from_directory(VIDEO_FOLDER, filename) # Return something at least
        except:
            # ffmpgeg probably not installed
            pass

    if os.path.exists(thumb_path):
        return send_from_directory(thumb_dir, f"{filename}.jpg")
    else:
        # Final fallback: SVG placeholder
        return """<svg width="120" height="68" viewBox="0 0 120 68" xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" fill="#111"/><text x="50%" y="50%" font-family="Arial" font-size="10" fill="#333" text-anchor="middle">NO THUMB</text></svg>""", 200, {'Content-Type': 'image/svg+xml'}

@app.route('/')
@login_required
def dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Kiosk Control Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #010103;
            --surface: rgba(10, 10, 15, 0.85);
            --surface-accent: rgba(20, 20, 30, 0.95);
            --accent: #00d4ff;
            --accent-glow: rgba(0, 212, 255, 0.3);
            --text-primary: #ffffff;
            --text-secondary: #8c8c9e;
            --danger: #ff3e5e;
            --success: #22c55e;
            --glass-border: rgba(255, 255, 255, 0.06);
            --card-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.8);
        }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        
        html, body { 
            height: 100%; 
            margin: 0; 
            padding: 0; 
            overflow: hidden; /* NO GLOBAL SCROLL */
            background-color: var(--bg);
            background-image: 
                radial-gradient(circle at 10% 10%, rgba(0, 212, 255, 0.05) 0%, transparent 40%),
                radial-gradient(circle at 90% 90%, rgba(212, 0, 255, 0.03) 0%, transparent 40%);
            color: var(--text-primary);
            font-family: 'Outfit', sans-serif;
        }

        .page-container {
            height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 16px;
            gap: 16px;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 24px;
            background: var(--surface);
            backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            box-shadow: var(--card-shadow);
            flex-shrink: 0;
        }
        
        .logo-group { display: flex; align-items: center; gap: 12px; }
        .logo-dot { width: 10px; height: 10px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 15px var(--accent-glow); animation: pulse 2s infinite; }
        h1 { margin: 0; font-size: 1.1rem; font-weight: 600; letter-spacing: -0.5px; opacity: 0.9; }

        .header-actions { display: flex; align-items: center; gap: 12px; }
        
        /* Main Dashboard Grid */
        .dashboard-grid {
            flex: 1;
            display: grid;
            grid-template-columns: repeat(12, 1fr);
            grid-template-rows: 1fr 1fr; /* Two equal rows */
            gap: 16px;
            overflow: hidden; /* Container doesn't scroll */
        }

        /* Card Base */
        .card { 
            background: var(--surface);
            backdrop-filter: blur(16px);
            border-radius: 20px;
            padding: 20px;
            border: 1px solid var(--glass-border);
            box-shadow: var(--card-shadow);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .card h2 { 
            font-size: 0.75rem; 
            color: var(--text-secondary); 
            text-transform: uppercase; 
            letter-spacing: 1.5px; 
            margin-top: 0; 
            margin-bottom: 16px; 
            opacity: 0.7;
            flex-shrink: 0;
        }
        
        /* Grid Placement */
        .monitor-sect { grid-column: span 8; grid-row: 1; }
        .matrix-sect { grid-column: span 8; grid-row: 2; }
        .library-sect { grid-column: span 4; grid-row: 1 / 3; } /* Spans entire right height */

        @media (max-width: 1200px) {
            .dashboard-grid { 
                grid-template-rows: repeat(4, auto); 
                overflow-y: auto; 
            }
            .monitor-sect, .library-sect, .matrix-sect { grid-column: span 12; grid-row: auto; }
            .page-container { height: auto; }
            html, body { overflow: auto; }
        }

        /* Monitor View */
        .monitor-wrapper { display: flex; gap: 16px; flex: 1; align-items: stretch; min-height: 0; }
        .monitor-screen {
            position: relative; flex: 1; background: #000; border-radius: 12px; overflow: hidden;
            border: 1px solid rgba(255,255,255,0.05);
        }
        .monitor-screen img { width: 100%; height: 100%; object-fit: contain; }
        .live-tag {
            position: absolute; top: 12px; left: 12px;
            background: rgba(255, 62, 94, 0.85); color: #fff;
            padding: 4px 10px; border-radius: 6px; font-size: 0.6rem;
            font-weight: 700; letter-spacing: 0.5px; display: flex; align-items: center; gap: 4px;
        }
        .live-dot { width: 6px; height: 6px; background: #fff; border-radius: 50%; opacity: 1; }

        /* Multi-Media Scroller Header */
        .library-controls { flex-shrink: 0; margin-bottom: 12px; }
        
        /* THE SEPARATE SCROLLER */
        .library-scroll {
            flex: 1;
            overflow-y: auto;
            padding-right: 8px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .library-scroll::-webkit-scrollbar { width: 6px; }
        .library-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 10px; }
        
        .media-card {
            background: rgba(255,255,255,0.02);
            border: 1px solid var(--glass-border);
            border-radius: 14px;
            padding: 10px;
            display: flex; align-items: center; gap: 12px;
            cursor: pointer; transition: 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .media-card:hover { transform: scale(1.02); background: rgba(255,255,255,0.05); }
        .media-card.selected { border-color: var(--accent); background: rgba(0, 212, 255, 0.05); }
        
        /* SNAPSHOT / PREVIEW STYLE */
        .media-preview {
            width: 80px; height: 45px; background: #000; border-radius: 6px; 
            overflow: hidden; flex-shrink: 0; position: relative;
            border: 1px solid rgba(255,255,255,0.05);
        }
        .media-preview img { width: 100%; height: 100%; object-fit: cover; }
        .play-icon { position: absolute; inset:0; display: grid; place-items: center; opacity: 0.4; }

        .media-info { flex: 1; min-width: 0; }
        .media-title { font-weight: 600; font-size: 0.85rem; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .media-meta { font-size: 0.65rem; color: var(--text-secondary); margin-top: 2px; }

        /* Matrix Grid Adjustments */
        .matrix-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            flex: 1;
            min-height: 0;
        }
        .key-slot {
            background: var(--surface-accent);
            border-radius: 16px;
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            border: 1px solid var(--glass-border);
            transition: 0.3s;
            cursor: pointer;
            padding: 12px;
        }
        .key-slot.is-playing { background: rgba(0, 212, 255, 0.1); border-color: var(--accent); box-shadow: 0 0 20px var(--accent-glow); }
        .key-num { font-family: 'JetBrains Mono'; font-weight: 700; font-size: 1.6rem; color: var(--accent); }
        .key-file { font-size: 0.7rem; color: var(--text-secondary); margin-top: 4px; text-align: center; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }

        /* Audio Section (Integrated in Sidebar Bottom) */
        .audio-mini {
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--glass-border);
            flex-shrink: 0;
        }
        
        /* Buttons */
        .btn {
            background: rgba(255,255,255,0.05); color: #fff; border: none; padding: 10px 16px; border-radius: 12px;
            font-family: inherit; font-weight: 600; cursor: pointer; transition: 0.2s; display: flex; align-items: center; gap: 8px;
            font-size: 0.8rem;
        }
        .btn-accent { background: var(--accent); color: #000; box-shadow: 0 4px 15px var(--accent-glow); }
        .btn-danger { color: #ff3e5e; background: rgba(255, 62, 94, 0.1); }

        .slider { -webkit-appearance: none; width: 100%; height: 4px; border-radius: 4px; background: #1a1a25; outline: none; }
        .slider::-webkit-slider-thumb { -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%; background: #fff; cursor: pointer; border: 3px solid var(--accent); }

        @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.9); } }
        
        .vu-slot { flex: 1; background: #222; border-radius: 1px; transition: 0.1s; }
        
        .modal { position: fixed; inset: 0; background: rgba(0,0,0,0.9); backdrop-filter: blur(10px); display: none; place-items: center; z-index: 10000; }
        .modal-body { background: var(--surface); border: 1px solid var(--glass-border); padding: 32px; border-radius: 20px; text-align: center; max-width: 360px; }

    </style>
</head>
<body>
    <div class="page-container">
        <header>
            <div class="logo-group">
                <div class="logo-dot"></div>
                <h1>Kiosk Control Center</h1>
            </div>
            <div class="header-actions">
                <span id="api-status" style="width: 8px; height: 8px; background: #22c55e; border-radius: 50%; box-shadow: 0 0 10px #22c55e; margin-right: 8px;"></span>
                <span style="font-size: 0.7rem; color: var(--text-secondary); margin-right: 12px;">HOST: <span id="ip-addr" style="color: var(--accent);">--</span></span>
                <button class="btn btn-danger" style="background: rgba(255, 62, 94, 0.05); color: #ff3e5e; font-size: 0.65rem;" onclick="rebootSystem()">REBOOT HW</button>
                <button class="btn" style="background: rgba(255,255,255,0.03); border: 1px solid var(--glass-border);" onclick="updateSystem()">UPDATE & RESTART</button>
                <button class="btn btn-accent" id="sync-btn" onclick="applyChanges()">APPLY SYNC</button>
                <a href="/api/logout" class="btn btn-danger" style="padding: 10px;">ESC</a>
            </div>
        </header>

        <main class="dashboard-grid">
            <!-- Top Left: Monitor -->
            <div class="card monitor-sect">
                <h2>Live Console Mirror</h2>
                <div class="monitor-wrapper">
                    <div class="monitor-screen">
                        <div class="live-tag">LIVE_TX</div>
                        <img id="live-monitor" src="/api/stream">
                    </div>
                </div>
            </div>

            <!-- Bottom Left: Matrix -->
            <div class="card matrix-sect">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                    <h2>Trigger Matrix Assignments</h2>
                    <div style="text-align: right;">
                        <div style="font-size: 0.6rem; color: var(--accent); text-transform: uppercase;">Idle State</div>
                        <div id="idle-display" style="font-size: 0.9rem; font-weight: 600;">...</div>
                    </div>
                </div>
                <div class="matrix-grid" id="key-grid"></div>
            </div>

            <!-- Full Right: Library + Audio -->
            <div class="card library-sect">
                <h2>Media Management</h2>
                <div class="library-controls">
                    <button class="btn btn-accent" style="width: 100%; border-radius: 12px; justify-content: center;" onclick="document.getElementById('file-input').click()">
                        + UPLOAD CONTENT
                    </button>
                    <input type="file" id="file-input" style="display:none;" onchange="uploadMedia(this.files[0])">
                    <button class="btn" style="width: 100%; margin-top: 8px; justify-content: center; font-size: 0.7rem;" onclick="setIdleFromSelected()">SET AS IDLE</button>
                </div>
                
                <!-- SEPARATE SCROLL LIST -->
                <div class="library-scroll" id="library"></div>
                
                <div class="audio-mini">
                    <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px;">
                        <span style="font-size: 0.75rem; opacity: 0.6; display: flex; align-items: center; gap: 8px;">
                            <span id="mute-icon" onclick="toggleMute()" style="cursor:pointer; font-size: 1rem;">🔊</span>
                            Output Gain
                        </span>
                        <span id="vol-value" style="font-family: 'JetBrains Mono'; font-weight: 700; color: var(--accent); font-size: 0.9rem;">100%</span>
                    </div>
                    
                    <!-- NEW: VU Meter Segmented -->
                    <div style="height: 12px; background: rgba(0,0,0,0.5); border-radius: 4px; overflow: hidden; display: flex; gap: 2px; margin-bottom: 12px; padding: 2px;">
                        <div class="vu-slot"></div><div class="vu-slot"></div><div class="vu-slot"></div><div class="vu-slot"></div>
                        <div class="vu-slot"></div><div class="vu-slot"></div><div class="vu-slot"></div><div class="vu-slot"></div>
                        <div class="vu-slot"></div><div class="vu-slot"></div><div class="vu-slot"></div><div class="vu-slot"></div>
                        <div class="vu-slot"></div><div class="vu-slot"></div><div class="vu-slot"></div><div class="vu-slot"></div>
                    </div>

                    <input type="range" min="0" max="100" value="100" class="slider" id="vol-slider" oninput="changeVolume(this.value)">
                    <select id="audio-out" style="background:#000; color:#fff; border:1px solid var(--glass-border); padding:8px; border-radius:8px; width:100%; margin-top:10px; font-size:0.75rem;" onchange="changeAudioDevice(this.value)"></select>
                </div>
            </div>
        </main>
    </div>

    <div id="assign-modal" class="modal">
        <div class="modal-body">
            <div id="target-key-display" style="font-size: 4rem; color: var(--accent); font-family: 'JetBrains Mono';">1</div>
            <p style="color: var(--text-secondary); margin: 16px 0; font-size: 0.9rem;">Mapping file to slot</p>
            <div id="target-file-name" style="background: rgba(0,0,0,0.3); padding: 12px; border-radius: 10px; font-weight: 600; font-size: 0.8rem; overflow-wrap: break-word;">--</div>
            <div style="display: flex; gap: 10px; margin-top: 24px;">
                <button class="btn" style="flex:1; justify-content: center;" onclick="closeModal()">CANCEL</button>
                <button class="btn btn-accent" style="flex:1; justify-content: center;" id="confirm-map">CONFIRM</button>
            </div>
        </div>
    </div>

    <script>
        let selectedFile = null;

        async function refresh() {
            try {
                const res = await fetch('/api/status');
                if (!res.ok) throw new Error("API_DOWN");
                const data = await res.json();
                
                document.getElementById('api-status').style.background = "#22c55e";
                document.getElementById('api-status').style.boxShadow = "0 0 10px #22c55e";

                if (data.system && data.system.ip) {
                    document.getElementById('ip-addr').innerText = data.system.ip;
                } else {
                    document.getElementById('ip-addr').innerText = "DISCONNECTED";
                }
                
                if (data.config) {
                    document.getElementById('idle-display').innerText = data.config.idle || "NOT_SET";
                    renderGrid(data.config, data.current_playing || "idle");
                }

                if (data.audio) {
                    document.getElementById('vol-slider').value = data.audio.volume || 100;
                    document.getElementById('vol-value').innerText = Math.round(data.audio.volume || 100) + "%";
                    const select = document.getElementById('audio-out');
                    if (select && data.audio.devices && data.audio.devices.length > 0) {
                        const currentVal = select.value || (data.config && data.config.audio ? data.config.audio.device : "");
                        select.innerHTML = data.audio.devices.map(d => `<option value="${d}" ${d === currentVal ? 'selected' : ''}>${d}</option>`).join('');
                    }
                    updateVUMeter(data.audio.volume || 0);
                }
                
                if (data.media) {
                    renderLibrary(data.media);
                }
            } catch(e) {
                console.error("Refresh Error:", e);
                document.getElementById('api-status').style.background = "#ff3e5e";
                document.getElementById('api-status').style.boxShadow = "0 0 10px #ff3e5e";
            }
        }

        function renderGrid(config, currentPlaying) {
            const grid = document.getElementById('key-grid');
            if (!grid) return;
            let html = '';
            for (let i = 1; i <= 9; i++) {
                // Ensure we check for BOTH number and string keys
                const file = config.mappings[i] || config.mappings[String(i)];
                const isPlaying = String(currentPlaying) === String(i);
                html += `
                    <div class="key-slot ${file ? 'active' : ''} ${isPlaying ? 'is-playing' : ''}" onclick="startMapping(${i})">
                        <span class="key-num">${i}</span>
                        <span class="key-file">${file || '—'}</span>
                    </div>
                `;
            }
            grid.innerHTML = html;
        }

        function renderLibrary(media) {
            const lib = document.getElementById('library');
            lib.innerHTML = media.map(file => `
                <div class="media-card ${selectedFile === file ? 'selected' : ''}" onclick="selectFile('${file}')">
                    <div class="media-preview">
                        <img src="/api/thumbnail/${file}" onerror="this.src='/static/video-placeholder.png'; this.onerror=null;">
                        <div class="play-icon">▶</div>
                    </div>
                    <div class="media-info">
                        <span class="media-title">${file}</span>
                        <span class="media-meta">MP4 / VIDEO</span>
                    </div>
                    <button class="btn btn-danger" style="padding: 4px; background: transparent; border:none;" onclick="deleteVideo('${file}', event)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                    </button>
                </div>
            `).join('');
        }

        function selectFile(file) { selectedFile = file; refresh(); }

        async function applyChanges() {
            const btn = document.getElementById('sync-btn');
            btn.innerText = "WAITING...";
            await fetch('/api/apply', { method: 'POST' });
            
            // Force Mirror Reconnect
            const monitor = document.getElementById('live-monitor');
            if (monitor) monitor.src = "/api/stream?sync=" + Date.now();
            
            setTimeout(() => { btn.innerText = "APPLY SYNC"; refresh(); }, 1200);
        }

        function startMapping(key) {
            if (!selectedFile) return alert("Select a video from the library first!");
            document.getElementById('target-key-display').innerText = key;
            document.getElementById('target-file-name').innerText = selectedFile;
            document.getElementById('assign-modal').style.display = 'grid';
            document.getElementById('confirm-map').onclick = async () => {
                await fetch('/api/update-mapping', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({key, filename: selectedFile})
                });
                closeModal();
                refresh();
            };
        }

        async function setIdleFromSelected() {
            if (!selectedFile) return alert("Select a video first!");
            await fetch('/api/update-mapping', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({filename: selectedFile, is_idle: true})
            });
            refresh();
        }

        async function deleteVideo(filename, e) {
            e.stopPropagation();
            if (!confirm(`Delete ${filename}?`)) return;
            await fetch('/api/delete', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({filename}) });
            refresh();
        }

        async function uploadMedia(file) {
            const form = new FormData();
            form.append('video', file);
            await fetch('/api/upload', { method: 'POST', body: form });
            refresh();
        }

        async function changeVolume(val) {
            document.getElementById('vol-value').innerText = val + "%";
            await fetch('/api/audio', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({volume: val}) });
        }

        async function changeAudioDevice(val) {
            await fetch('/api/audio', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({device: val}) });
        }

        let isMuted = false;
        let lastVol = 100;
        function toggleMute() {
            const slider = document.getElementById('vol-slider');
            const icon = document.getElementById('mute-icon');
            if (!isMuted) {
                lastVol = slider.value;
                changeVolume(0);
                slider.value = 0;
                icon.innerText = "🔇";
                isMuted = true;
            } else {
                changeVolume(lastVol);
                slider.value = lastVol;
                icon.innerText = "🔊";
                isMuted = false;
            }
        }

        function updateVUMeter(vol) {
            const slots = document.querySelectorAll('.vu-slot');
            const activeCount = Math.floor((vol / 100) * slots.length);
            slots.forEach((s, i) => {
                if (i < activeCount) {
                    let color = "#22c55e"; // Green
                    if (i > slots.length * 0.6) color = "#eab308"; // Yellow
                    if (i > slots.length * 0.85) color = "#ef4444"; // Red
                    s.style.background = color;
                    s.style.boxShadow = `0 0 8px ${color}66`;
                } else {
                    s.style.background = "#222";
                    s.style.boxShadow = "none";
                }
            });
        }

        async function updateSystem() {
            if (!confirm("Confirm remote restart?")) return;
            await fetch('/api/update-system', { method: 'POST' });
        }

        async function rebootSystem() {
            if (!confirm("⚠️ CAUTION: REBOOT ENTIRE HARDWARE? \nThis will shut down the display and restart the PC.")) return;
            await fetch('/api/reboot', { method: 'POST' });
            alert("Hardware reboot sequence initiated. Please wait 60s.");
        }

        function closeModal() { document.getElementById('assign-modal').style.display = 'none'; }
        
        // Auto-Sync: Faster heartbeat
        setInterval(refresh, 1000);
        refresh();

        // Handle Mirror Errors Gracefully instead of Polling
        const liveMonitor = document.getElementById('live-monitor');
        if (liveMonitor) {
            liveMonitor.onerror = function() {
                setTimeout(() => {
                    this.src = "/api/stream?retry=" + Date.now();
                }, 4000);
            };
        }
    </script>
</body>
</html>
    """



def run_server(update_callback=None, port=3000):
    global on_update_callback
    on_update_callback = update_callback
    app.run(host='0.0.0.0', port=port, use_reloader=False)

if __name__ == "__main__":
    run_server()
