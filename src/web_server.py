import os
import json
import socket
import logging
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

# Disable verbose logging to keep terminal clean
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
CORS(app)

# --- DIRECTORY SETUP ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_FOLDER = os.path.join(BASE_DIR, "videos")
CONFIG_PATH = os.path.join(BASE_DIR, "config", "media_config.json")
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'mkv', 'avi'}

if not os.path.exists(VIDEO_FOLDER):
    os.makedirs(VIDEO_FOLDER)

# Global callback to signal the GUI app
on_update_callback = None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except: pass
    return {"idle": "", "mappings": {}}

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)
    if on_update_callback:
        on_update_callback()

# --- API ENDPOINTS ---

@app.route('/api/status', methods=['GET'])
def get_status():
    config = load_config()
    all_files = [f for f in os.listdir(VIDEO_FOLDER) if allowed_file(f)]
    return jsonify({
        "config": config,
        "media": all_files,
        "system": {
            "os": os.uname().sysname,
            "ip": socket.gethostbyname(socket.gethostname())
        }
    })

@app.route('/api/upload', methods=['POST'])
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
def delete_video():
    filename = request.json.get('filename')
    path = os.path.join(VIDEO_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)
        # Cleanup config
        config = load_config()
        if config["idle"] == filename: config["idle"] = ""
        config["mappings"] = {k: v for k, v in config["mappings"].items() if v != filename}
        save_config(config)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/update-mapping', methods=['POST'])
def update_mapping():
    data = request.json
    key = data.get('key') # e.g. "1", "2"
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
def apply_config():
    if on_update_callback:
        on_update_callback()
        return jsonify({"success": True, "message": "System sync initiated"})
    return jsonify({"error": "GUI not connected"}), 503

@app.route('/api/remove-mapping', methods=['POST'])
def remove_mapping():
    key = request.json.get('key')
    config = load_config()
    if str(key) in config["mappings"]:
        del config["mappings"][str(key)]
        save_config(config)
        return jsonify({"success": True})
    return jsonify({"error": "Not mapped"}), 400

# --- STATIC CONTENT ---

@app.route('/')
def dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Display Control Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #050508;
            --surface: #101015;
            --surface-accent: #1a1a24;
            --accent: #00d4ff;
            --accent-glow: rgba(0, 212, 255, 0.3);
            --text-primary: #ffffff;
            --text-secondary: #a0a0b0;
            --danger: #ff4d6d;
        }
        * { box-sizing: border-box; }
        body {
            background-color: var(--bg);
            color: var(--text-primary);
            font-family: 'Outfit', sans-serif;
            margin: 0;
            padding: 0;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        header {
            padding: 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .logo-group { display: flex; align-items: center; gap: 15px; }
        .logo-dot { width: 10px; height: 10px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 10px var(--accent); }
        h1 { margin: 0; font-size: 1.5rem; font-weight: 600; letter-spacing: -0.5px; }
        
        main { flex: 1; padding: 40px; max-width: 1400px; width: 100%; margin: 0 auto; display: grid; grid-template-columns: 1fr 400px; gap: 40px; }
        
        .card { 
            background: var(--surface);
            border-radius: 24px;
            padding: 32px;
            border: 1px solid rgba(255,255,255,0.05);
            box-shadow: 0 20px 40px rgba(0,0,0,0.4);
        }
        .card h2 { font-size: 1.1rem; color: var(--text-secondary); margin-top: 0; margin-bottom: 24px; display: flex; align-items: center; gap: 10px; }
        
        .shortcut-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
            gap: 16px;
        }
        .key-slot {
            background: var(--surface-accent);
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.05);
            transition: 0.2s;
            cursor: pointer;
            position: relative;
            overflow: hidden;
        }
        .key-slot:hover { border-color: var(--accent); background: rgba(0,212,255,0.05); }
        .key-slot.active { border-color: var(--accent); box-shadow: 0 0 20px var(--accent-glow); }
        .key-tag { font-family: 'JetBrains Mono'; font-weight: 700; font-size: 1.2rem; display: block; margin-bottom: 8px; color: var(--accent); }
        .key-file { font-size: 0.8rem; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
        
        .media-library { display: grid; gap: 12px; }
        .media-item {
            display: flex; align-items: center; gap: 16px;
            padding: 16px; background: var(--surface-accent); border-radius: 12px;
            border: 1px solid transparent; transition: 0.2s;
        }
        .media-item:hover { border-color: rgba(255,255,255,0.1); }
        .media-info { flex: 1; min-width: 0; }
        .media-name { font-weight: 500; display: block; overflow: hidden; text-overflow: ellipsis; }
        .media-actions { display: flex; gap: 8px; }
        
        .btn {
            background: rgba(255,255,255,0.05);
            color: white;
            border: none;
            padding: 10px 18px;
            border-radius: 8px;
            font-family: inherit;
            font-weight: 600;
            cursor: pointer;
            transition: 0.2s;
            font-size: 0.9rem;
        }
        .btn:hover { background: rgba(255,255,255,0.12); }
        .btn-accent { background: var(--accent); color: #000; }
        .btn-accent:hover { opacity: 0.9; transform: translateY(-1px); }
        .btn-danger { color: var(--danger); }
        
        .badge { background: var(--accent); color: black; font-size: 0.7rem; font-weight: 800; padding: 4px 8px; border-radius: 6px; }
        .status-pill { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 0.9rem; }
        
        #unassign-btn { 
            position: absolute; top: 5px; right: 8px; color: var(--danger); 
            font-size: 1.2rem; cursor: pointer; display: none;
        }
        .key-slot:hover #unassign-btn { display: block; }
        
        .modal { 
            position: fixed; inset: 0; background: rgba(0,0,0,0.8); backdrop-filter: blur(10px);
            display: none; place-items: center; z-index: 1000;
        }
        .modal-card { background: var(--surface); padding: 40px; border-radius: 32px; width: 400px; text-align: center; border: 1px solid rgba(255,255,255,0.1); }
        
        .idle-section { margin-bottom: 40px; padding: 24px; border-radius: 20px; background: linear-gradient(135deg, #101015 0%, #1a1a24 100%); border: 1px solid rgba(255,255,255,0.05); }
    </style>
</head>
<body>
    <header>
        <div class="logo-group">
            <div class="logo-dot"></div>
            <h1>Smart Control Console</h1>
        </div>
        <div class="status-pill">
            <button class="btn btn-accent" style="margin-right: 15px; padding: 6px 12px; font-size: 0.8rem;" onclick="applyChanges()">Apply Changes</button>
            <span id="ip-addr">--</span>
            <div style="width: 8px; height: 8px; background: #22c55e; border-radius: 50%;"></div>
        </div>
    </header>

    <main>
        <section>
            <div class="idle-section">
                <h2 style="color: var(--accent); font-size: 1rem; margin-top: 0;">Main Idle Screen</h2>
                <div style="display:flex; justify-content: space-between; align-items:center;">
                    <div id="idle-status" style="font-size: 1.2rem; font-weight: 600;">--</div>
                    <span class="badge">ALWAYS ON</span>
                </div>
            </div>

            <div class="card">
                <h2>Keyboard Mapping Hub</h2>
                <div class="shortcut-grid" id="key-grid">
                    <!-- Key slots generated here -->
                </div>
            </div>
        </section>

        <aside>
            <div class="card" style="height: 100%; display: flex; flex-direction: column;">
                <h2>Media Library</h2>
                <button class="btn btn-accent" style="width: 100%; margin-bottom: 20px;" onclick="document.getElementById('file-input').click()">+ Upload New Media</button>
                <input type="file" id="file-input" style="display:none;" onchange="uploadMedia(this.files[0])">
                
                <div class="media-library" id="library">
                    <!-- Files generated here -->
                </div>
            </div>
        </aside>
    </main>

    <div id="assign-modal" class="modal">
        <div class="modal-card">
            <div class="key-tag" id="target-key-label" style="font-size: 3rem;">1</div>
            <p style="color: var(--text-secondary); margin-bottom: 30px;">Assign video to this shortcut key?</p>
            <p id="target-file-label" style="font-weight: 500; font-size: 1.2rem; color: var(--accent);"></p>
            <div style="display: flex; gap: 10px; margin-top: 40px;">
                <button class="btn" style="flex:1" onclick="closeModal()">Cancel</button>
                <button class="btn btn-accent" style="flex:1" id="confirm-assign">Assign Key</button>
            </div>
        </div>
    </div>

    <script>
        let currentState = {};
        let selectedFile = null;

        async function refresh() {
            const res = await fetch('/api/status');
            const data = await res.json();
            currentState = data;
            
            document.getElementById('ip-addr').innerText = data.system.ip;
            document.getElementById('idle-status').innerText = data.config.idle || "No Video Assigned";
            
            renderGrid(data.config);
            renderLibrary(data.media, data.config);
        }

        function renderGrid(config) {
            const grid = document.getElementById('key-grid');
            grid.innerHTML = '';
            for (let i = 1; i <= 9; i++) {
                const file = config.mappings[i];
                const div = document.createElement('div');
                div.className = `key-slot ${file ? 'active' : ''}`;
                div.innerHTML = `
                    <span class="key-tag">${i}</span>
                    <span class="key-file">${file || 'Empty'}</span>
                    ${file ? `<span id="unassign-btn" onclick="removeMapping('${i}', event)">&times;</span>` : ''}
                `;
                div.onclick = () => startAssignment(i);
                grid.appendChild(div);
            }
        }

        function renderLibrary(media, config) {
            const lib = document.getElementById('library');
            lib.innerHTML = media.map(file => `
                <div class="media-item" onclick="selectedFile='${file}'; document.querySelectorAll('.media-item').forEach(e=>e.style.borderColor='transparent'); this.style.borderColor='var(--accent)'">
                    <div class="media-info">
                        <span class="media-name">${file}</span>
                        <span style="font-size:0.7rem; color:var(--text-secondary)">Video File</span>
                    </div>
                    <div class="media-actions">
                        <button class="btn" onclick="setIdle('${file}')" title="Set as Idle">🏠</button>
                        <button class="btn btn-danger" onclick="deleteVideo('${file}')">&times;</button>
                    </div>
                </div>
            `).join('');
        }

        function startAssignment(key) {
            if (!selectedFile) return alert("Select a video from the library first!");
            document.getElementById('target-key-label').innerText = key;
            document.getElementById('target-file-label').innerText = selectedFile;
            document.getElementById('assign-modal').style.display = 'grid';
            document.getElementById('confirm-assign').onclick = () => doAssign(key, selectedFile);
        }

        async function doAssign(key, filename) {
            await fetch('/api/update-mapping', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({key, filename})
            });
            closeModal();
            refresh();
        }

        async function removeMapping(key, e) {
            e.stopPropagation();
            await fetch('/api/remove-mapping', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({key})
            });
            refresh();
        }

        async function setIdle(filename) {
            await fetch('/api/update-mapping', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({filename, is_idle: true})
            });
            refresh();
        }

        async function deleteVideo(filename) {
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

        function closeModal() { document.getElementById('assign-modal').style.display = 'none'; }

        async function applyChanges() {
            await fetch('/api/apply', { method: 'POST' });
            alert("App Refreshed Successfully!");
            refresh();
        }

        refresh();
    </script>
</body>
</html>
    """

def run_server(update_callback=None, port=3000):
    global on_update_callback
    on_update_callback = update_callback
    print(f"[SERVER] Admin Console active at http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, use_reloader=False)

if __name__ == "__main__":
    run_server()
