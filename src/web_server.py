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
    if request.json.get('password') == ADMIN_PASSWORD:
        session['logged_in'] = True
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

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
    all_files = sorted([f for f in os.listdir(VIDEO_FOLDER) if allowed_file(f)])
    return jsonify({
        "config": load_config(),
        "media": all_files,
        "current_playing": current_playing,
        "audio": {"devices": audio_devices, "volume": current_volume},
        "system": {"os": "Linux" if os.name != 'nt' else "Windows", "ip": get_ip()}
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
    if on_update_callback:
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
    if volume is not None: config["audio"]["volume"] = float(volume) / 100.0
    if device is not None: config["audio"]["device"] = device
    save_config(config)
    if on_update_callback:
        if volume is not None: on_update_callback(f"TRIGGER:volume:{config['audio']['volume']}")
        if device is not None: on_update_callback(f"TRIGGER:device:{device}")
        return jsonify({"success": True})
    return jsonify({"error": "GUI not connected"}), 503

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
    import subprocess
    try:
        pull_res = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True, check=True)
        if on_update_callback:
            on_update_callback("TRIGGER:RESTART")
            return jsonify({"success": True})
        return jsonify({"success": True, "message": "Updated, but GUI not connected"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/login')
def login_page():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "login.html"), 'r') as f:
            return f.read()
    except: return "Error loading login page", 500

@app.route('/api/thumbnail/<filename>')
@login_required
def get_thumbnail(filename):
    import subprocess
    thumb_dir = os.path.join(VIDEO_FOLDER, ".thumbnails")
    try:
        os.makedirs(thumb_dir, exist_ok=True)
    except: pass
    thumb_path = os.path.join(thumb_dir, f"{filename}.jpg")
    if not os.path.exists(thumb_path):
        try:
            subprocess.run(["ffmpeg", "-y", "-i", os.path.join(VIDEO_FOLDER, filename), "-ss", "00:00:01", "-vframes", "1", "-vf", "scale=120:-1", thumb_path], capture_output=True, timeout=2)
        except: pass
    if os.path.exists(thumb_path): return send_from_directory(thumb_dir, f"{filename}.jpg")
    return "<svg viewBox='0 0 120 68'><rect width='100%' height='100%' fill='#111'/></svg>", 200, {'Content-Type': 'image/svg+xml'}

@app.route('/')
@login_required
def dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Kiosk Control Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #010103; --surface: rgba(10, 10, 15, 0.85); --accent: #00d4ff; --accent-glow: rgba(0, 212, 255, 0.3); --text-primary: #ffffff; --text-secondary: #8c8c9e; --danger: #ff3e5e; --glass-border: rgba(255, 255, 255, 0.06); }
        * { box-sizing: border-box; }
        body { height: 100vh; margin: 0; background: var(--bg); color: var(--text-primary); font-family: 'Outfit', sans-serif; display: flex; flex-direction: column; overflow: hidden; padding: 16px; gap: 16px; }
        header { display: flex; justify-content: space-between; align-items: center; padding: 12px 24px; background: var(--surface); border: 1px solid var(--glass-border); border-radius: 16px; flex-shrink: 0; }
        .logo-dot { width: 10px; height: 10px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 15px var(--accent-glow); animation: pulse 2s infinite; display: inline-block; margin-right: 10px; }
        .btn { background: rgba(255,255,255,0.05); color: #fff; border: none; padding: 10px; border-radius: 8px; cursor: pointer; font-size: 0.8rem; font-weight: 600; }
        .btn-accent { background: var(--accent); color: #000; box-shadow: 0 4px 15px var(--accent-glow); }
        .btn-danger { color: var(--danger); background: rgba(255, 62, 94, 0.1); }
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
        .slot-file { font-size: 0.7rem; color: var(--text-secondary); word-break: break-all; }
        
        /* Media List */
        .media-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
        .media-item { display: flex; align-items: center; gap: 10px; padding: 8px; background: rgba(255,255,255,0.02); border: 1px solid transparent; border-radius: 8px; cursor: pointer; }
        .media-item.selected { border-color: var(--accent); background: rgba(0,212,255,0.05); }
        .media-item img { width: 60px; height: 34px; border-radius: 4px; object-fit: cover; }
        
        .modal { position: fixed; inset: 0; background: rgba(0,0,0,0.8); display: none; place-items: center; z-index: 100; backdrop-filter: blur(5px); }
        .modal-c { background: var(--surface); border: 1px solid var(--glass-border); padding: 24px; border-radius: 16px; width: 300px; text-align: center; }
        
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        @keyframes slideIn { to { opacity: 1; transform: translateX(0); } }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
    </style>
</head>
<body>
    <header>
        <div>
            <div class="logo-dot"></div>
            <strong style="font-size: 1.1rem;">Kiosk Control Center</strong>
        </div>
        <div style="display: flex; gap: 12px; align-items: center;">
            <span id="api-status" style="width: 8px; height: 8px; background: #22c55e; border-radius: 50%; box-shadow: 0 0 10px #22c55e;"></span>
            <span style="font-size: 0.7rem; color: var(--text-secondary);">HOST: <span id="ip-addr" style="color: var(--accent);">--</span></span>
            <button class="btn btn-danger" onclick="xFetch('/api/reboot')">REBOOT</button>
            <button class="btn" onclick="xFetch('/api/update-system')">UPDATE SRC</button>
            <a href="/api/logout" class="btn btn-danger">ESC</a>
        </div>
    </header>

    <div class="grid">
        <div class="col">
            <div class="card" style="flex: 1.5;">
                <h2>System Monitors</h2>
                <div class="monitor-grid" style="grid-template-columns: 1fr;">
                    <div class="screen-box">
                        <div class="live-tag">VIEW TX</div>
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
                <button class="btn btn-accent" style="flex:1;" onclick="document.getElementById('uf').click()">+ UPLOAD</button>
                <input type="file" id="uf" style="display:none;" onchange="upload(this.files[0])">
                <button class="btn" onclick="setIdle()">SET IDLE</button>
            </div>
            <div class="media-list" id="mlist"></div>
            
            <div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--glass-border);">
                <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 8px;">
                    <span>Volume <span id="vol-lbl">100%</span></span>
                </div>
                <input type="range" id="vol" min="0" max="100" style="width: 100%;" onchange="setAudio({volume: this.value})">
                <select id="audio-out" style="width:100%; margin-top:12px; padding:8px; background:#000; color:#fff; border:1px solid var(--glass-border); border-radius:8px;" onchange="setAudio({device: this.value})"></select>
            </div>
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
        let lastLogCount = 0;

        async function fetchStatus() {
            fetchSnap();
            try {
                const r = await fetch('/api/status');
                if(!r.ok) throw 1;
                const d = await r.json();
                document.getElementById('api-status').style.background = "#22c55e";
                document.getElementById('ip-addr').innerText = d.system.ip;
                document.getElementById('idle-lbl').innerText = d.config.idle || "None";
                
                // Mappings
                const m = document.getElementById('matrix');
                m.innerHTML = '';
                for(let i=1; i<=9; i++) {
                    const f = d.config.mappings[i] || d.config.mappings[String(i)] || '';
                    const play = String(d.current_playing) === String(i) ? 'playing' : '';
                    m.innerHTML += `<div class="slot ${play}" onclick="mapReq(${i})"><span class="slot-num">${i}</span><span class="slot-file">${f||'—'}</span></div>`;
                }

                // Library
                const l = document.getElementById('mlist');
                l.innerHTML = d.media.map(f => `
                    <div class="media-item ${selFile===f?'selected':''}" onclick="sel('${f}')">
                        <img src="/api/thumbnail/${f}">
                        <span style="font-size:0.8rem; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${f}</span>
                        <button class="btn btn-danger" style="padding:4px 8px;" onclick="del('${f}', event)">X</button>
                    </div>
                `).join('');

                // Audio
                document.getElementById('vol').value = d.audio.volume || 100;
                document.getElementById('vol-lbl').innerText = Math.round(d.audio.volume||100) + "%";
                const selDev = document.getElementById('audio-out');
                if (d.audio.devices.length > 0 && selDev.options.length === 0) {
                    selDev.innerHTML = d.audio.devices.map(dev => `<option value="${dev}" ${dev===d.config.audio.device?'selected':''}>${dev}</option>`).join('');
                }
                

                
            } catch(e) {
                document.getElementById('api-status').style.background = "#ff3e5e";
            }
        }

        async function fetchSnap() {
            document.getElementById('live-img').src = "/api/snapshot?_t=" + Date.now();
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

        async function setIdle() {
            if(!selFile) return;
            await xFetch('/api/update-mapping', {is_idle: true, filename: selFile});
            fetchStatus();
        }

        async function del(f, e) {
            e.stopPropagation();
            if(confirm('Delete '+f+'?')) {
                await xFetch('/api/delete', {filename: f});
                fetchStatus();
            }
        }

        async function upload(f) {
            const formData = new FormData(); formData.append('video', f);
            await fetch('/api/upload', {method:'POST', body:formData});
            fetchStatus();
        }

        async function setAudio(payload) {
            await xFetch('/api/audio', payload);
            fetchStatus();
        }

        async function xFetch(url, body={}) {
            return fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        }

        // DELETED AUTO-POLLING: Dashboard only refreshes snapshot and status after user actions.
        // fetchStatus() now handles the monitor mirror too.
        fetchStatus();
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
