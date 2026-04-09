import os
import json
import socket
import logging
import sys
import time
from collections import deque
from flask import Flask, jsonify, request, send_from_directory, session, redirect, url_for, Response
from flask_cors import CORS
from functools import wraps
from werkzeug.utils import secure_filename

# Disable verbose logging to keep terminal clean
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "kiosk-smart-display-v5")
CORS(app, supports_credentials=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")



def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_FOLDER = os.path.join(BASE_DIR, "videos")
CONFIG_PATH = os.path.join(BASE_DIR, "config", "media_config.json")
ANALYTICS_PATH = os.path.join(BASE_DIR, "config", "analytics.csv")
ASSETS_FOLDER = os.path.join(BASE_DIR, "assets")
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'mkv', 'avi'}
import csv
from datetime import datetime

# Ensure config directory exists!
os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
os.makedirs(ASSETS_FOLDER, exist_ok=True)

if not os.path.exists(VIDEO_FOLDER):
    os.makedirs(VIDEO_FOLDER, exist_ok=True)

# Global states
on_update_callback = None
latest_screenshot = None
current_playing = "idle"
audio_devices = []
current_screens = []
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
                if "audio" not in config:
                    config["audio"] = {"volume": 1.0, "device": ""}
        except: pass
    return config

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)
    if on_update_callback:
        on_update_callback("")

def log_playback(slot, filename):
    try:
        exists = os.path.exists(ANALYTICS_PATH)
        with open(ANALYTICS_PATH, 'a', newline='') as f:
            writer = csv.writer(f)
            if not exists:
                writer.writerow(["Timestamp", "Slot", "Filename"])
            writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), slot, filename])
    except: pass

# --- API ENDPOINTS ---

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    u = data.get('username')
    p = data.get('password')
    if u == ADMIN_USER and p == ADMIN_PASSWORD:
        session['logged_in'] = True
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Invalid credentials"}), 401

@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(ASSETS_FOLDER, filename)

@app.route('/api/logout')
def api_logout():
    session.pop('logged_in', None)
    return redirect(url_for('login_page'))

def get_ip():
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
    files = [f for f in os.listdir(VIDEO_FOLDER) if allowed_file(f)]
    config = load_config()
    return jsonify({
        "media": files,
        "config": config,
        "current_playing": current_playing,
        "audio_devices": audio_devices,
        "screens": current_screens,
        "system": {
            "ip": get_ip(),
            "time": time.ctime()
        }
    })

# Snapshot API to fix thread exhaustion!
@app.route('/api/snapshot')
@login_required
def get_snapshot():
    if latest_screenshot:
        return Response(latest_screenshot, mimetype='image/jpeg')
    return Response(b'', status=204)

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_video():
    if 'video' not in request.files: return jsonify({"error": "No file"}), 400
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
    if is_idle: config["idle"] = filename
    else: config["mappings"][str(key)] = filename
    save_config(config)
    return jsonify({"success": True})

@app.route('/api/apply', methods=['POST'])
@login_required
def apply_config():
    if on_update_callback:
        on_update_callback("") 
        return jsonify({"success": True})
    return jsonify({"error": "GUI not connected"}), 503

@app.route('/api/trigger', methods=['POST'])
@login_required
def trigger_video():
    global current_playing
    key = request.json.get('key')
    current_playing = str(key)
    
    # Log analytics (Now handled by main.py to cover Hardware/Keyboard triggers)
    # log_playback(f"Slot {key}", filename)

    if on_update_callback:
        on_update_callback(f"TRIGGER:{key}")
        return jsonify({"success": True})
    return jsonify({"error": "GUI not connected"}), 503

@app.route('/api/analytics', methods=['GET'])
@login_required
def get_analytics():
    data = []
    if os.path.exists(ANALYTICS_PATH):
        try:
            with open(ANALYTICS_PATH, 'r') as f:
                reader = csv.DictReader(f)
                data = list(reader)[-100:] # Last 100 entries
                data.reverse()
        except: pass
    return jsonify(data)

@app.route('/api/clear-analytics', methods=['POST'])
@login_required
def clear_analytics():
    if os.path.exists(ANALYTICS_PATH):
        os.remove(ANALYTICS_PATH)
    return jsonify({"success": True})

@app.route('/api/download-analytics')
@login_required
def download_analytics():
    if os.path.exists(ANALYTICS_PATH):
        return send_from_directory(os.path.dirname(ANALYTICS_PATH), os.path.basename(ANALYTICS_PATH), as_attachment=True)
    return "No logs found", 404

@app.route('/api/audio', methods=['POST'])
@login_required
def update_audio():
    data = request.json
    volume = data.get('volume')
    device = data.get('device')
    config = load_config()
    if "audio" not in config: config["audio"] = {"volume": 1.0, "device": ""}
    if volume is not None: config["audio"]["volume"] = float(volume) / 100.0
    if device is not None: config["audio"]["device"] = device
    save_config(config)
    if on_update_callback:
        if volume is not None: on_update_callback(f"TRIGGER:volume:{config['audio']['volume']}")
        if device is not None: on_update_callback(f"TRIGGER:device:{device}")
        return jsonify({"success": True})
    return jsonify({"error": "GUI not connected"}), 503

@app.route('/api/display', methods=['POST'])
@login_required
def update_display():
    name = request.json.get('name')
    config = load_config()
    config["display"] = name
    save_config(config)
    if on_update_callback:
        on_update_callback(f"TRIGGER:display:{name}")
        return jsonify({"success": True})
    return jsonify({"success": True})

@app.route('/api/reboot', methods=['POST'])
@login_required
def reboot_system():
    import subprocess
    try:
        subprocess.Popen(["sudo", "reboot"])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/update-system', methods=['POST'])
@login_required
def update_system():
    import subprocess, shutil
    # Protect config from being wiped if git tries to delete it
    temp_conf = CONFIG_PATH + ".tmp"
    has_conf = os.path.exists(CONFIG_PATH)
    if has_conf: shutil.copy2(CONFIG_PATH, temp_conf)
    
    try:
        # Pull latest code
        subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True, check=True)
        # Restore config if it was lost
        if has_conf: shutil.move(temp_conf, CONFIG_PATH)
        
        if on_update_callback:
            on_update_callback("TRIGGER:RESTART")
            return jsonify({"success": True})
        return jsonify({"success": True})
    except Exception as e:
        if os.path.exists(temp_conf): os.remove(temp_conf)
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/login')
def login_page():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "login.html"), 'r') as f:
            return f.read()
    except: return "Error loading login page", 500

@app.route('/api/restart-gui', methods=['POST'])
@login_required
def restart_gui():
    if on_update_callback:
        on_update_callback("TRIGGER:RESTART")
        return jsonify({"success": True})
    return jsonify({"error": "GUI not connected"}), 503

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(ASSETS_FOLDER, 'favicon.png')

@app.route('/')
@login_required
def dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Kiosk Control Center</title>
    <link rel="icon" type="image/png" href="/favicon.ico?v=1">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #010103; --surface: rgba(10, 10, 15, 0.85); --accent: #00d4ff; --accent-glow: rgba(0, 212, 255, 0.3); --text-primary: #ffffff; --text-secondary: #8c8c9e; --danger: #ff3e5e; --glass-border: rgba(255, 255, 255, 0.06); }
        * { box-sizing: border-box; }
        body { height: 100vh; margin: 0; background: var(--bg); color: var(--text-primary); font-family: 'Outfit', sans-serif; display: flex; flex-direction: column; overflow: hidden; padding: 16px; gap: 16px; }
        header { display: flex; justify-content: space-between; align-items: center; padding: 12px 24px; background: var(--surface); border: 1px solid var(--glass-border); border-radius: 16px; flex-shrink: 0; }
        .logo-dot { width: 10px; height: 10px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 15px var(--accent-glow); animation: pulse 2s infinite; display: inline-block; margin-right: 10px; }
        .btn { background: rgba(255,255,255,0.05); color: #fff; border: none; padding: 10px; border-radius: 8px; cursor: pointer; font-size: 0.8rem; font-weight: 600; transition: all 0.2s; display: flex; align-items: center; gap: 8px; }
        .btn:hover { background: rgba(255,255,255,0.12); transform: translateY(-1px); }
        .btn:active { transform: translateY(0); opacity: 0.8; }
        .btn-accent { background: var(--accent); color: #000; box-shadow: 0 4px 15px var(--accent-glow); }
        .btn-accent:hover { background: #00e5ff; box-shadow: 0 6px 20px var(--accent-glow); }
        .btn-danger { color: var(--danger); background: rgba(255, 62, 94, 0.1); }
        .btn-danger:hover { background: rgba(255, 62, 94, 0.2); }
        .grid { flex: 1; display: grid; grid-template-columns: 2fr 1fr; gap: 16px; min-height: 0; }
        .col { display: flex; flex-direction: column; gap: 16px; min-height: 0; }
        .card { background: var(--surface); border: 1px solid var(--glass-border); border-radius: 16px; padding: 16px; display: flex; flex-direction: column; min-height: 0; }
        .card h2 { font-size: 0.8rem; color: var(--text-secondary); text-transform: uppercase; margin: 0 0 12px 0; }
        .monitor-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; flex: 1; min-height: 0; }
        .screen-box { background: #000; border-radius: 10px; position: relative; overflow: hidden; border: 1px solid var(--glass-border); }
        .screen-box img { width: 100%; height: 100%; object-fit: contain; }
        .live-tag { position: absolute; top: 8px; left: 8px; background: rgba(255, 62, 94, 0.8); padding: 4px 8px; font-size: 0.6rem; border-radius: 4px; font-weight: bold; z-index: 10; }
        

        
        /* Matrix */
        .matrix { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; flex: 1; }
        .slot { background: rgba(255,255,255,0.03); border: 1px solid var(--glass-border); border-radius: 10px; padding: 10px; text-align: center; cursor: pointer; transition: 0.2s; }
        .slot.playing { border-color: var(--accent); background: rgba(0, 212, 255, 0.1); }
        .slot-num { font-size: 1.2rem; font-weight: bold; color: var(--accent); display: block; }
        .slot-file { font-size: 0.7rem; color: var(--text-secondary); word-break: break-all; margin-top:4px; display:block; }
        .slot-clear { position: absolute; top: 4px; right: 4px; width: 18px; height: 18px; border-radius: 50%; background: rgba(255,255,255,0.05); color: var(--danger); display: grid; place-items: center; font-size: 10px; opacity: 0.5; transition: 0.2s; }
        .slot-clear:hover { opacity: 1; background: rgba(255, 62, 94, 0.2); }
        
        /* Media List */
        .media-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
        .media-item { display: flex; align-items: center; gap: 10px; padding: 8px; background: rgba(255,255,255,0.02); border: 1px solid transparent; border-radius: 8px; cursor: pointer; position: relative; }
        .media-item:hover { background: rgba(255,255,255,0.05); }
        .media-item.selected { border-color: var(--accent); background: rgba(0,212,255,0.15); box-shadow: 0 0 15px var(--accent-glow); animation: breathe 2s infinite ease-in-out; }
        .media-item.is-idle { border-left: 4px solid #a855f7; background: rgba(168, 85, 247, 0.05); }
        .media-item.is-mapped { border-left: 4px solid #22c55e; background: rgba(34, 197, 94, 0.05); }
        
        @keyframes breathe { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.8; transform: scale(0.99); } }
        
        .ctx-menu { position: absolute; background: #1a1a24; border: 1px solid var(--glass-border); border-radius: 8px; padding: 8px; z-index: 1000; display: none; box-shadow: 0 10px 30px rgba(0,0,0,0.5); width: 150px; }
        .ctx-item { padding: 8px 12px; font-size: 0.75rem; border-radius: 4px; cursor: pointer; transition: 0.2s; display: flex; align-items: center; gap: 8px; }
        .ctx-item:hover { background: rgba(255,255,255,0.08); color: var(--accent); }
        
        .modal { position: fixed; inset: 0; background: rgba(0,0,0,0.8); display: none; place-items: center; z-index: 100; backdrop-filter: blur(5px); }
        .modal-c { background: var(--surface); border: 1px solid var(--glass-border); padding: 24px; border-radius: 16px; width: 300px; text-align: center; }
        
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        @keyframes slideIn { to { opacity: 1; transform: translateX(0); } }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
        
        /* Progress Bar */
        .progress-box { background: rgba(255,255,255,0.02); border: 1px solid var(--glass-border); border-radius: 8px; padding: 12px; margin-bottom: 12px; display: none; }
        .progress-bar-bg { background: rgba(0,0,0,0.3); height: 8px; border-radius: 4px; overflow: hidden; margin-top: 8px; }
        .progress-bar-fill { background: var(--accent); height: 100%; width: 0%; box-shadow: 0 0 10px var(--accent-glow); transition: width 0.1s; }

        /* Responsive Design */
        @media (max-width: 900px) {
            body { height: auto; overflow-y: auto; padding: 12px; }
            header { padding: 12px 16px; border-radius: 12px; }
            header strong { font-size: 0.9rem; }
            .btn span { display: none; } /* Hide text, keep icons */
            .btn { padding: 8px; }
            .logo-dot { margin-right: 5px; }

            .grid { grid-template-columns: 1fr; display: flex; flex-direction: column; }
            .col { min-height: auto; }
            .card { min-height: 400px; }
            .monitor-grid { grid-template-columns: 1fr; }
            
            #analytics-page table { display: block; overflow-x: auto; white-space: nowrap; }
        }
    </style>
</head>
<body>
    <header>
        <div style="display:flex; align-items:center; gap:12px;">
            <div style="width:32px; height:32px; background:var(--accent); border-radius:8px; display:grid; place-items:center; mask: url(/favicon.ico) center/contain no-repeat; -webkit-mask: url(/favicon.ico) center/contain no-repeat;"></div>
            <strong style="font-size: 1.1rem; letter-spacing:-0.5px;">Control Center</strong>
        </div>
        <div style="display: flex; gap: 8px; align-items: center;">
            <span style="font-size: 0.7rem; color: var(--text-secondary); display: none;" id="ip-lbl">HOST: <span id="ip-addr" style="color: var(--accent);">--</span></span>
            <button class="btn" style="background:rgba(255,255,255,0.08)" onclick="if(confirm('Pull latest code from Cloud and Restart?')) xFetch('/api/update-system')" title="Update from Cloud">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                <span>GIT UPDATE</span>
            </button>
            <button class="btn" style="background:rgba(168, 85, 247, 0.1); color:#d8b4fe" onclick="showAnalytics()" title="View Analytics">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>
                <span>ANALYTICS</span>
            </button>
            <button class="btn btn-accent" onclick="xFetch('/api/restart-gui')" title="Apply & Restart">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"></path><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M3 22v-6h6"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path></svg>
                <span>APPLY & RESTART</span>
            </button>
            <button class="btn btn-danger" style="background:rgba(255, 62, 94, 0.1);" onclick="if(confirm('FULL HARDWARE RESTART? System will be offline for 1-2 mins.')) xFetch('/api/reboot')" title="Reboot Entire PC">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path><line x1="12" y1="2" x2="12" y2="12"></line></svg>
                <span>REBOOT HW</span>
            </button>
            <a href="/api/logout" class="btn btn-danger" title="Exit to Login" style="background:transparent; border:1px solid rgba(255, 62, 94, 0.3)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
            </a>
        </div>
    </header>

    <div class="grid" id="main-dash">
        <div class="col">
            <div class="card" style="flex: 1.5;">
                <h2>System Monitors</h2>
                <div class="monitor-grid" style="grid-template-columns: 1fr;">
                    <div class="screen-box">
                        <div class="live-tag">PLAYBACK</div>
                        <img id="live-img" src="">
                    </div>
                </div>
            </div>
            
            <div class="card" style="flex: 1;">
                <div style="display: flex; justify-content: space-between;">
                    <h2>Trigger Matrix</h2>
                    <span style="font-size: 0.7rem; color: var(--accent);">IDLE: <span id="idle-lbl"></span></span>
                </div>
                <div class="matrix" id="matrix"></div>
            </div>
        </div>
        
        <div class="col card">
            <h2>Media & Audio</h2>
            <div style="display:flex; gap:8px; margin-bottom:12px;">
                <button class="btn btn-accent" style="flex:1;" id="up-btn" onclick="document.getElementById('uf').click()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                    UPLOAD MEDIA
                </button>
                <input type="file" id="uf" style="display:none;" onchange="upload(this.files[0])">
            </div>

            <div id="up-progress" class="progress-box">
                <div style="display:flex; justify-content:space-between; font-size:0.7rem;">
                    <span id="up-filename" style="color:var(--text-secondary); overflow:hidden; text-overflow:ellipsis;">video.mp4</span>
                    <span id="up-pc" style="color:var(--accent); font-weight:bold;">0%</span>
                </div>
                <div class="progress-bar-bg">
                    <div id="up-fill" class="progress-bar-fill"></div>
                </div>
            </div>

            <div class="media-list" id="mlist" oncontextmenu="return false;"></div>
            <div id="ctx-menu" class="ctx-menu">
                <div class="ctx-item" onclick="setIdleFromCtx()">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"></path></svg>
                    Set as Idle
                </div>
                <div class="ctx-item" style="color:var(--danger)" onclick="delFromCtx()">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                    Delete
                </div>
            </div>
            
            <div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--glass-border);">
                <div style="display: flex; flex-direction: column; gap: 12px;">
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem;">
                        <span>Volume <span id="vol-lbl">100%</span></span>
                    </div>
                    <input type="range" id="vol" min="0" max="100" style="width: 100%;" onchange="setAudio({volume: this.value})">
                    
                    <div style="margin-top:8px;">
                        <span style="font-size:0.7rem; color:var(--text-secondary); text-transform:uppercase;">Audio Output</span>
                        <select id="audio-out" style="width:100%; margin-top:4px; padding:8px; background:#000; color:#fff; border:1px solid var(--glass-border); border-radius:8px;" onchange="setAudio({device: this.value})"></select>
                    </div>

                    <div style="margin-top:8px;">
                        <span style="font-size:0.7rem; color:var(--text-secondary); text-transform:uppercase;">Display Monitor</span>
                        <select id="disp-out" style="width:100%; margin-top:4px; padding:8px; background:#000; color:#fff; border:1px solid var(--glass-border); border-radius:8px;" onchange="setDisplay(this.value)"></select>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Analytics Page -->
    <div id="analytics-page" class="card" style="display:none; flex:1; overflow:hidden;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
            <button class="btn" onclick="showMain()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 18 9 12 15 6"></polyline></svg>
                BACK
            </button>
            <h2 style="margin:0">Playback Analytics</h2>
            <div style="display:flex; gap:8px;">
                <a href="/api/download-analytics" class="btn btn-accent" style="padding:6px 12px; font-size:0.7rem;">DOWNLOAD CSV</a>
                <button class="btn btn-danger" onclick="clearAnalytics()" style="padding:6px 12px; font-size:0.7rem;">CLEAR LOGS</button>
            </div>
        </div>
        <div style="flex:1; overflow-y:auto; background:rgba(0,0,0,0.2); border-radius:12px;">
            <table style="width:100%; border-collapse:collapse; font-size:0.8rem; text-align:left;">
                <thead style="position:sticky; top:0; background:var(--surface); box-shadow:0 1px 0 var(--glass-border);">
                    <tr>
                        <th style="padding:12px;">Time</th>
                        <th style="padding:12px;">Trigger</th>
                        <th style="padding:12px;">File</th>
                    </tr>
                </thead>
                <tbody id="analytics-body" style="color:var(--text-secondary)">
                    <!-- Loaded dynamically -->
                </tbody>
            </table>
        </div>
    </div>

    <div id="modal" class="modal">
        <div class="modal-c">
            <h1 id="mkey" style="color:var(--accent); font-family:'JetBrains Mono'; margin:0 0 10px 0;">1</h1>
            <p id="mfile" style="font-size:0.8rem; word-break:break-all; margin-bottom:20px;">file.mp4</p>
            <div style="display:flex; gap:10px;">
                <button class="btn" style="flex:1;" onclick="modal.style.display='none'">CANCEL</button>
                <button class="btn btn-accent" style="flex:1;" onclick="mapConf()">CONFIRM</button>
            </div>
        </div>
    </div>

    <script>
        let selFile = null;
        let pKey = null;
        let lastState_str = "";

        async function fetchStatus() {
            try {
                const r = await fetch('/api/status');
                if(!r.ok) throw 1;
                const d = await r.json();
                
                const curState = JSON.stringify({
                    media: d.media.join(','),
                    mappings: JSON.stringify(d.config.mappings),
                    idle: d.config.idle,
                    playing: d.current_playing
                });

                if (curState !== lastState_str) {
                    lastState_str = curState;
                    updateUI(d);
                }

                document.getElementById('ip-addr').innerText = d.system.ip;
            } catch(e) {}
        }
        
        function updateUI(cur) {
            document.getElementById('idle-lbl').innerText = cur.config.idle || "None";
            
            // Mappings (Matrix Grid)
            const m = document.getElementById('matrix');
            m.innerHTML = '';
            for(let i=1; i<=9; i++) {
                const f = cur.config.mappings[i] || cur.config.mappings[String(i)] || '';
                const play = String(cur.current_playing) === String(i) ? 'playing' : '';
                m.innerHTML += `
                    <div class="slot ${play}" onclick="mapReq(${i})" style="position:relative;">
                        ${f ? `<div class="slot-clear" onclick="clearMap(event, ${i})">✕</div>` : ''}
                        <span class="slot-num">${i}</span>
                        <span class="slot-file">${f||'—'}</span>
                    </div>
                `;
            }

            // Library (Media List)
            const l = document.getElementById('mlist');
            const mappedFiles = Object.values(cur.config.mappings).filter(v => typeof v === 'string' && v.length > 0);
            l.innerHTML = cur.media.map(f => {
                const isIdle = cur.config.idle === f;
                const isMapped = mappedFiles.includes(f);
                let color = isIdle ? '#a855f7' : (isMapped ? '#22c55e' : 'var(--accent)');
                let borderClass = isIdle ? 'is-idle' : (isMapped ? 'is-mapped' : '');
                
                return `
                    <div class="media-item ${selFile===f?'selected':''} ${borderClass}" 
                         onclick="sel('${f}')" 
                         oncontextmenu="showCtx(event, '${f}')">
                        <div style="width:34px; height:34px; background:rgba(255,255,255,0.05); border-radius:4px; display:grid; place-items:center; color:${color};">
                            ${isIdle ? 
                                '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"></path></svg>' : 
                                (isMapped ? 
                                    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path><rect x="8" y="2" width="8" height="4" rx="1" ry="1"></rect></svg>' :
                                    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>')
                            }
                        </div>
                        <div style="display:flex; flex-direction:column; flex:1; overflow:hidden;">
                            <span style="font-size:0.8rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#fff">${f}</span>
                            <div style="display:flex; gap:8px;">
                                ${isIdle ? '<span style="font-size:0.6rem; color:#a855f7; font-weight:bold;">IDLE</span>' : ''}
                                ${isMapped ? '<span style="font-size:0.6rem; color:#22c55e; font-weight:bold;">MAPPED</span>' : ''}
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

            // Audio
            document.getElementById('vol').value = (cur.config.audio?.volume || 1) * 100;
            document.getElementById('vol-lbl').innerText = Math.round((cur.config.audio?.volume || 1) * 100) + "%";
            
            if(cur.audio_devices) {
                const sel = document.getElementById('audio-out');
                const oldVal = sel.value;
                sel.innerHTML = cur.audio_devices.map(d => `<option value="${d}">${d}</option>`).join('');
                sel.value = cur.config.audio?.device || oldVal;
            }
            
            if(cur.screens) {
                const sel = document.getElementById('disp-out');
                const oldVal = sel.value;
                sel.innerHTML = `<option value="">Default Display</option>` + cur.screens.map(s => `<option value="${s}">${s}</option>`).join('');
                sel.value = cur.config.display || oldVal;
            }
        }

        // SMOOTH SNAPSHOT: Use an off-screen buffer to prevent flickering
        const bufferImg = new Image();
        let isFetching = false;
        function fetchSnap() {
            return new Promise((resolve) => {
                if (isFetching) return resolve();
                isFetching = true;
                const newSrc = "/api/snapshot?_t=" + Date.now();
                bufferImg.src = newSrc;
                bufferImg.onload = () => {
                    document.getElementById('live-img').src = newSrc;
                    isFetching = false;
                    resolve();
                };
                bufferImg.onerror = () => { isFetching = false; resolve(); };
            });
        }

        function sel(f) { selFile = f; fetchStatus(); }
        
        function mapReq(k) {
            if(!selFile) return alert("Select media first");
            pKey = k;
            document.getElementById('mkey').innerText = k;
            document.getElementById('mfile').innerText = selFile;
            document.getElementById('modal').style.display = 'grid';
        }

        async function mapConf() {
            await xFetch('/api/update-mapping', {key: pKey, filename: selFile});
            document.getElementById('modal').style.display = 'none';
            fetchStatus();
        }

        async function clearMap(e, k) {
            e.stopPropagation();
            if(confirm('Clear slot '+k+'?')) {
                await xFetch('/api/update-mapping', {key: k, filename: ""});
                fetchStatus();
            }
        }

        function sel(f) { selFile = f; fetchStatus(); }
        
        // Context Menu Logic
        const ctx = document.getElementById('ctx-menu');
        let ctxFile = null;
        function showCtx(e, f) {
            e.preventDefault();
            ctxFile = f;
            ctx.style.display = 'block';
            ctx.style.left = e.pageX + 'px';
            ctx.style.top = e.pageY + 'px';
        }
        window.onclick = () => ctx.style.display = 'none';

        async function setIdleFromCtx() {
            if(!ctxFile) return;
            await xFetch('/api/update-mapping', {is_idle: true, filename: ctxFile});
            fetchStatus();
        }

        async function delFromCtx() {
            if(!ctxFile) return;
            if(confirm('Delete '+ctxFile+'?')) {
                await xFetch('/api/delete', {filename: ctxFile});
                fetchStatus();
            }
        }

        async function upload(f) {
            if(!f) return;
            const upBox = document.getElementById('up-progress');
            const upFill = document.getElementById('up-fill');
            const upPc = document.getElementById('up-pc');
            const upName = document.getElementById('up-filename');
            const upBtn = document.getElementById('up-btn');

            upName.innerText = f.name;
            upBox.style.display = 'block';
            upBtn.disabled = true;
            upBtn.style.opacity = 0.5;

            const formData = new FormData();
            formData.append('video', f);

            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/upload', true);

            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    const pc = Math.round((e.loaded / e.total) * 100);
                    upFill.style.width = pc + '%';
                    upPc.innerText = pc + '%';
                }
            };

            xhr.onload = () => {
                upBox.style.display = 'none';
                upBtn.disabled = false;
                upBtn.style.opacity = 1;
                fetchStatus();
                if(xhr.status !== 200) alert("Upload failed");
            };

            xhr.onerror = () => {
                alert("Network error");
                upBox.style.display = 'none';
                upBtn.disabled = false;
                upBtn.style.opacity = 1;
            };

            xhr.send(formData);
        }

        async function setAudio(payload) {
            await xFetch('/api/audio', payload);
            fetchStatus();
        }

        async function setDisplay(name) {
            await xFetch('/api/display', {name: name});
            fetchStatus();
        }

        // Navigation
        function showAnalytics() {
            document.getElementById('main-dash').style.display = 'none';
            document.getElementById('analytics-page').style.display = 'flex';
            loadAnalytics();
        }
        function showMain() {
            document.getElementById('main-dash').style.display = 'flex';
            document.getElementById('analytics-page').style.display = 'none';
        }

        async function loadAnalytics() {
            const r = await fetch('/api/analytics');
            const d = await r.json();
            const b = document.getElementById('analytics-body');
            b.innerHTML = d.map(row => `
                <tr style="border-bottom:1px solid rgba(255,255,255,0.02)">
                    <td style="padding:10px;">${row.Timestamp}</td>
                    <td style="padding:10px;"><span style="color:var(--accent)">${row.Slot}</span></td>
                    <td style="padding:10px; font-family:'JetBrains Mono';">${row.Filename}</td>
                </tr>
            `).join('') || '<tr><td colspan="3" style="padding:20px; text-align:center;">No data recorded yet</td></tr>';
        }

        async function clearAnalytics() {
            if(confirm('Clear all analytics logs?')) {
                await xFetch('/api/clear-analytics');
                loadAnalytics();
            }
        }

        async function xFetch(url, body={}) {
            return fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        }

        // Initial status pull
        fetchStatus();
        
        // AUTO MONITOR: Recursive fetch for highest achievable framerate.
        // As soon as one frame finishes loading, we pull the next one.
        function monitorLoop() {
            fetchSnap().then(() => setTimeout(monitorLoop, 16)); // ~60fps cap if fast enough
        }
        monitorLoop();
    </script>
</body>
</html>"""

def run_server(update_callback=None, port=3000):
    global on_update_callback
    on_update_callback = update_callback
    # default single process, multi-thread dispatcher inside Werkzeug handles /api/snapshot cleanly
    app.run(host='0.0.0.0', port=port, use_reloader=False)

if __name__ == "__main__":
    run_server()
