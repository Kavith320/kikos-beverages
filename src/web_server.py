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
log.setLevel(logging.ERROR)

app = Flask(__name__)
# Use a consistent secret key for sessions
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "kikos-beverages-smart-display-v4")
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

@app.route('/api/status', methods=['GET'])
@login_required
def get_status():
    config = load_config()
    all_files = [f for f in os.listdir(VIDEO_FOLDER) if allowed_file(f)]
    return jsonify({
        "config": config,
        "media": all_files,
        "current_playing": current_playing,
        "audio": {
            "devices": audio_devices,
            "volume": current_volume
        },
        "system": {
            "os": os.uname().sysname,
            "ip": socket.gethostbyname(socket.gethostname())
        }
    })

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
        on_update_callback("TRIGGER:RESTART") # Command for a full process exit
        return jsonify({"success": True, "message": "System restart initiated"})
    return jsonify({"error": "GUI not connected"}), 503

def gen_frames():
    """MJPEG Streaming Generator"""
    import time
    while True:
        if latest_screenshot:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + latest_screenshot + b'\r\n')
        time.sleep(0.08) # ~12fps max

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

@app.route('/')
@login_required
def dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Kikos Control Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #030305;
            --surface: rgba(10, 10, 15, 0.8);
            --surface-accent: rgba(20, 20, 30, 0.9);
            --accent: #00d4ff;
            --accent-glow: rgba(0, 212, 255, 0.3);
            --text-primary: #ffffff;
            --text-secondary: #8c8c9e;
            --danger: #ff3e5e;
            --success: #22c55e;
            --glass-border: rgba(255, 255, 255, 0.08);
            --card-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.8);
        }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body {
            background-color: var(--bg);
            background-image: 
                radial-gradient(circle at 20% 20%, rgba(0, 212, 255, 0.05) 0%, transparent 40%),
                radial-gradient(circle at 80% 80%, rgba(212, 0, 255, 0.05) 0%, transparent 40%);
            color: var(--text-primary);
            font-family: 'Outfit', sans-serif;
            margin: 0;
            padding: 0;
            min-height: 100vh;
            overflow-x: hidden;
        }
        
        .page-container {
            max-width: 1600px;
            margin: 0 auto;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 24px;
            background: var(--surface);
            backdrop-filter: blur(12px);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            box-shadow: var(--card-shadow);
        }
        
        .logo-group { display: flex; align-items: center; gap: 12px; }
        .logo-dot { 
            width: 12px; height: 12px; 
            background: linear-gradient(135deg, var(--accent), #d400ff); 
            border-radius: 50%; 
            box-shadow: 0 0 15px var(--accent-glow); 
            animation: pulse 2s infinite;
        }
        h1 { margin: 0; font-size: 1.2rem; font-weight: 600; letter-spacing: -0.5px; opacity: 0.9; }

        .header-actions { display: flex; align-items: center; gap: 12px; }
        
        /* Main Dashboard Grid */
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(12, 1fr);
            gap: 24px;
        }

        /* Card Base */
        .card { 
            background: var(--surface);
            backdrop-filter: blur(16px);
            border-radius: 24px;
            padding: 24px;
            border: 1px solid var(--glass-border);
            box-shadow: var(--card-shadow);
            transition: transform 0.3s ease, border-color 0.3s ease;
        }
        .card:hover { border-color: rgba(255,255,255,0.15); }
        .card h2 { 
            font-size: 0.8rem; 
            color: var(--text-secondary); 
            text-transform: uppercase; 
            letter-spacing: 1.5px; 
            margin-top: 0; 
            margin-bottom: 24px; 
            display: flex; 
            align-items: center; 
            gap: 10px;
            opacity: 0.7;
        }
        
        /* Grid Assignments */
        .monitor-sect { grid-column: span 8; }
        .library-sect { grid-column: span 4; grid-row: span 2; }
        .matrix-sect { grid-column: span 8; }
        .audio-sect { grid-column: span 4; }

        @media (max-width: 1200px) {
            .monitor-sect, .library-sect, .matrix-sect, .audio-sect { grid-column: span 12; }
            .library-sect { grid-row: auto; }
        }

        /* Monitor View */
        .monitor-wrapper {
            display: flex; gap: 20px; align-items: stretch;
        }
        .monitor-screen {
            position: relative; flex: 1; aspect-ratio: 16/9; 
            background: #000; border-radius: 16px; overflow: hidden;
            border: 1px solid rgba(255,255,255,0.05);
        }
        .monitor-screen img { width: 100%; height: 100%; object-fit: contain; }
        .live-tag {
            position: absolute; top: 12px; left: 12px;
            background: rgba(255, 62, 94, 0.8); color: #fff;
            padding: 4px 10px; border-radius: 6px; font-size: 0.65rem;
            font-weight: 700; letter-spacing: 0.5px; display: flex; align-items: center; gap: 6px;
        }
        .live-dot { width: 6px; height: 6px; background: #fff; border-radius: 50%; animation: pulse 1s infinite; }

        /* Idle State */
        .idle-indicator {
            background: linear-gradient(90deg, rgba(0, 212, 255, 0.1), transparent);
            padding: 16px 20px; border-radius: 16px; margin-bottom: 20px;
            display: flex; justify-content: space-between; align-items: center;
            border-left: 3px solid var(--accent);
        }
        .idle-label { font-size: 0.7rem; color: var(--accent); font-weight: 600; text-transform: uppercase; }
        .idle-val { font-size: 1.1rem; font-weight: 600; margin-top: 4px; }

        /* Shortcut Matrix */
        .matrix-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
        }
        .key-slot {
            background: var(--surface-accent);
            border-radius: 20px;
            padding: 24px;
            text-align: center;
            border: 1px solid var(--glass-border);
            transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            cursor: pointer;
            position: relative;
            overflow: hidden;
        }
        .key-slot::before {
            content: ''; position: absolute; inset: 0;
            background: radial-gradient(circle at center, var(--accent-glow), transparent 70%);
            opacity: 0; transition: opacity 0.3s;
        }
        .key-slot:hover { transform: translateY(-8px); border-color: var(--accent); }
        .key-slot:hover::before { opacity: 0.4; }
        .key-slot.active { border-color: rgba(255,255,255,0.2); }
        .key-slot.is-playing { 
            border-color: var(--accent); 
            box-shadow: 0 0 30px var(--accent-glow);
            background: rgba(0, 212, 255, 0.1);
        }
        .key-num { font-family: 'JetBrains Mono'; font-weight: 700; font-size: 1.8rem; color: var(--accent); position: relative; z-index: 1; }
        .key-file { font-size: 0.75rem; color: var(--text-secondary); margin-top: 8px; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; position: relative; z-index: 1; }

        /* Library List */
        .library-container { display: flex; flex-direction: column; gap: 12px; height: calc(100% - 100px); overflow-y: auto; padding-right: 8px; }
        .library-container::-webkit-scrollbar { width: 5px; }
        .library-container::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 10px; }
        
        .media-card {
            background: rgba(255,255,255,0.03);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 16px;
            display: flex; align-items: center; gap: 16px;
            cursor: pointer; transition: 0.2s;
        }
        .media-card:hover { background: rgba(255,255,255,0.06); }
        .media-card.selected { border-color: var(--accent); background: rgba(0, 212, 255, 0.05); }
        .media-icon { width: 40px; height: 40px; background: #000; border-radius: 10px; display: grid; place-items: center; font-size: 1.2rem; }
        .media-info { flex: 1; min-width: 0; }
        .media-title { font-weight: 600; font-size: 0.9rem; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .media-meta { font-size: 0.7rem; color: var(--text-secondary); margin-top: 2px; }

        /* Audio Controls */
        .volume-panel {
            background: var(--surface-accent);
            padding: 24px; border-radius: 20px; border: 1px solid var(--glass-border);
        }
        .slider-wrap { margin: 20px 0; }
        .slider { -webkit-appearance: none; width: 100%; height: 6px; border-radius: 8px; background: #1a1a25; outline: none; }
        .slider::-webkit-slider-thumb { 
            -webkit-appearance: none; width: 22px; height: 22px; 
            border-radius: 50%; background: #fff; cursor: pointer; 
            box-shadow: 0 0 15px rgba(255,255,255,0.5); border: 4px solid var(--accent);
        }
        select { background: #000; color: #fff; border: 1px solid var(--glass-border); padding: 12px; border-radius: 12px; width: 100%; font-family: inherit; margin-top: 10px; outline: none; }

        /* Buttons */
        .btn {
            background: rgba(255,255,255,0.05); color: #fff; border: none; padding: 12px 20px; border-radius: 14px;
            font-family: inherit; font-weight: 600; cursor: pointer; transition: 0.2s; display: flex; align-items: center; gap: 10px;
        }
        .btn-accent { background: var(--accent); color: #000; box-shadow: 0 4px 20px var(--accent-glow); }
        .btn-accent:hover { transform: translateY(-2px); box-shadow: 0 6px 25px var(--accent-glow); }
        .btn-danger { color: var(--danger); background: rgba(255, 62, 94, 0.1); border: 1px solid rgba(255, 62, 94, 0.2); }
        .btn-danger:hover { background: rgba(255, 62, 94, 0.2); }
        .btn-ghost { background: transparent; border: 1px solid var(--glass-border); }
        .btn-ghost:hover { background: rgba(255,255,255,0.05); }

        /* Status VU Meter */
        .vu-meter-v { width: 12px; background: #000; border-radius: 6px; display: flex; flex-direction: column-reverse; gap: 3px; padding: 3px; overflow: hidden; border: 1px solid var(--glass-border); }
        .vu-segment { height: 6px; border-radius: 2px; background: #1a1a25; transition: 0.1s; }

        /* Animations */
        @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.9); } }
        .is-playing .key-num { animation: pulse 1.5s infinite; }
        
        .modal { 
            position: fixed; inset: 0; background: rgba(0,0,0,0.9); backdrop-filter: blur(10px);
            display: none; place-items: center; z-index: 10000;
        }
        .modal-body { background: var(--surface); border: 1px solid var(--glass-border); padding: 40px; border-radius: 32px; text-align: center; max-width: 400px; }

    </style>
</head>
<body>
    <div class="page-container">
        <header>
            <div class="logo-group">
                <div class="logo-dot"></div>
                <h1>Kikos Control Center</h1>
            </div>
            <div class="header-actions">
                <div style="font-size: 0.75rem; color: var(--text-secondary); background: rgba(0,0,0,0.3); padding: 8px 16px; border-radius: 12px; border: 1px solid var(--glass-border);">
                    SYS_IP: <span id="ip-addr" style="color: #fff; font-family: 'JetBrains Mono';">--</span>
                </div>
                <button class="btn btn-ghost" id="update-btn" onclick="updateSystem()" style="font-size: 0.8rem;">
                    Check Updates
                </button>
                <button class="btn btn-accent" id="sync-btn" onclick="applyChanges()">
                    Apply Changes
                </button>
                <a href="/api/logout" class="btn btn-danger" style="padding: 12px;">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
                </a>
            </div>
        </header>

        <main class="dashboard-grid">
            <div class="card monitor-sect">
                <h2>Live Display Monitor</h2>
                <div class="monitor-wrapper">
                    <div class="vu-meter-v" id="vu-meter-v">
                        <div class="vu-segment"></div><div class="vu-segment"></div><div class="vu-segment"></div><div class="vu-segment"></div>
                        <div class="vu-segment"></div><div class="vu-segment"></div><div class="vu-segment"></div><div class="vu-segment"></div>
                        <div class="vu-segment"></div><div class="vu-segment"></div><div class="vu-segment"></div><div class="vu-segment"></div>
                        <div class="vu-segment"></div><div class="vu-segment"></div><div class="vu-segment"></div><div class="vu-segment"></div>
                    </div>
                    <div class="monitor-screen">
                        <div class="live-tag"><div class="live-dot"></div> LIVE_TX</div>
                        <img id="live-monitor" src="/api/stream">
                    </div>
                </div>
            </div>

            <div class="card library-sect">
                <h2>Media Library</h2>
                <button class="btn btn-accent" style="width: 100%; margin-bottom: 20px; justify-content: center;" onclick="document.getElementById('file-input').click()">
                    + UPLOAD MEDIA
                </button>
                <input type="file" id="file-input" style="display:none;" onchange="uploadMedia(this.files[0])">
                
                <div class="library-container" id="library">
                    <!-- Dynamic Items -->
                </div>
                
                <button class="btn btn-ghost" style="width: 100%; margin-top: 20px; font-size: 0.75rem;" onclick="setIdleFromSelected()">
                    SET SELECTED AS IDLE
                </button>
            </div>

            <div class="card matrix-sect">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <h2>Trigger Matrix Assignments</h2>
                    <div class="idle-indicator" id="idle-banner-wrap" style="margin-top: -10px;">
                        <div>
                            <div class="idle-label">Active Idle</div>
                            <div class="idle-val" id="idle-display">...</div>
                        </div>
                    </div>
                </div>
                <div class="matrix-grid" id="key-grid">
                    <!-- 1-9 Keys -->
                </div>
            </div>

            <div class="card audio-sect">
                <h2>Audio Engine</h2>
                <div class="volume-panel">
                    <div style="display: flex; justify-content: space-between; align-items: baseline;">
                        <span style="font-size: 0.8rem; opacity: 0.6;">Output Gain</span>
                        <span id="vol-value" style="font-family: 'JetBrains Mono'; font-weight: 700; color: var(--accent);">100%</span>
                    </div>
                    <div class="slider-wrap">
                        <input type="range" min="0" max="100" value="100" class="slider" id="vol-slider" oninput="changeVolume(this.value)">
                    </div>
                    
                    <div style="margin-top: 10px;">
                        <span style="font-size: 0.75rem; opacity: 0.6;">Target Device</span>
                        <select id="audio-out" onchange="changeAudioDevice(this.value)"></select>
                    </div>
                </div>
            </div>
        </main>
    </div>

    <div id="assign-modal" class="modal">
        <div class="modal-body">
            <div id="target-key-display" style="font-size: 4rem; font-family: 'JetBrains Mono'; color: var(--accent); line-height: 1;">1</div>
            <p style="color: var(--text-secondary); margin: 20px 0;">Assigning video to this slot</p>
            <div id="target-file-name" style="background: rgba(0,0,0,0.2); padding: 16px; border-radius: 12px; font-weight: 600;">--</div>
            <div style="display: flex; gap: 12px; margin-top: 32px;">
                <button class="btn btn-ghost" style="flex:1; justify-content: center;" onclick="closeModal()">CANCEL</button>
                <button class="btn btn-accent" style="flex:1; justify-content: center;" id="confirm-map">CONFIRM</button>
            </div>
        </div>
    </div>

    <script>
        let selectedFile = null;

        async function refresh() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                document.getElementById('ip-addr').innerText = data.system.ip;
                document.getElementById('idle-display').innerText = data.config.idle || "EMPTY";
                
                if (data.audio) {
                    document.getElementById('vol-slider').value = data.audio.volume * 100;
                    document.getElementById('vol-value').innerText = Math.round(data.audio.volume * 100) + "%";
                    
                    const select = document.getElementById('audio-out');
                    if (data.audio.devices.length > 0) {
                        const currentVal = select.value || data.config.audio.device;
                        select.innerHTML = data.audio.devices.map(d => `<option value="${d}" ${d === currentVal ? 'selected' : ''}>${d}</option>`).join('');
                    }
                    updateVUMeter(data.audio.volume, data.current_playing);
                }

                const idleBanner = document.getElementById('idle-banner-wrap');
                idleBanner.style.borderColor = data.current_playing === 'idle' ? 'var(--accent)' : 'transparent';
                
                renderGrid(data.config, data.current_playing);
                renderLibrary(data.media);
            } catch(e) {}
        }

        function renderGrid(config, currentPlaying) {
            const grid = document.getElementById('key-grid');
            let html = '';
            for (let i = 1; i <= 9; i++) {
                const file = config.mappings[i];
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
                    <div class="media-icon">🎬</div>
                    <div class="media-info">
                        <span class="media-title">${file}</span>
                        <span class="media-meta">MP4 VIDEO</span>
                    </div>
                    <button class="btn btn-danger" style="padding: 6px; border-radius: 8px;" onclick="deleteVideo('${file}', event)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                    </button>
                </div>
            `).join('');
        }

        function selectFile(file) {
            selectedFile = file;
            refresh();
        }

        async function applyChanges() {
            const btn = document.getElementById('sync-btn');
            btn.innerText = "SYNCING...";
            await fetch('/api/apply', { method: 'POST' });
            setTimeout(() => { btn.innerText = "Apply Changes"; refresh(); }, 1000);
        }

        function updateVUMeter(volume, currentPlaying) {
            const vSegments = document.querySelectorAll('#vu-meter-v .vu-segment');
            const isActive = currentPlaying !== 'idle' && currentPlaying !== 'logo';
            const threshold = Math.floor(volume * vSegments.length);
            
            vSegments.forEach((s, i) => {
                if (i < threshold) {
                    const color = i < vSegments.length * 0.6 ? '#22c55e' : (i < vSegments.length * 0.85 ? '#eab308' : '#ef4444');
                    s.style.background = color;
                    s.style.boxShadow = `0 0 10px ${color}44`;
                    s.style.opacity = isActive ? "1" : "0.3";
                } else {
                    s.style.background = '#1a1a25';
                    s.style.boxShadow = 'none';
                    s.style.opacity = "1";
                }
            });
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
            await fetch('/api/delete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({filename})
            });
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
            await fetch('/api/audio', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({volume: val})
            });
        }

        async function changeAudioDevice(val) {
            await fetch('/api/audio', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({device: val})
            });
        }

        async function updateSystem() {
            if (!confirm("Pull latest code and restart?")) return;
            await fetch('/api/update-system', { method: 'POST' });
            alert("System update initiated...");
        }

        function closeModal() { document.getElementById('assign-modal').style.display = 'none'; }
        
        setInterval(refresh, 2000);
        refresh();
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
