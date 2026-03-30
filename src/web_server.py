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

# Global states
on_update_callback = None
latest_screenshot = None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except: pass
    return {"idle": "", "mappings": {}, "aliases": {}}

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
        config = load_config()
        if config["idle"] == filename: config["idle"] = ""
        config["mappings"] = {k: v for k, v in config["mappings"].items() if v != filename}
        save_config(config)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/update-mapping', methods=['POST'])
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
def apply_config():
    if on_update_callback:
        on_update_callback()
        return jsonify({"success": True, "message": "System sync initiated"})
    return jsonify({"error": "GUI not connected"}), 503

@app.route('/api/mirror', methods=['GET'])
def get_mirror():
    if latest_screenshot:
        from flask import Response
        return Response(latest_screenshot, mimetype='image/jpeg')
    # Fallback to logo if no capture yet
    return send_from_directory(os.path.join(BASE_DIR, "assets"), "logo.png")

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
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Kikos Control Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #030305;
            --surface: #0a0a0f;
            --surface-accent: #11111a;
            --accent: #00d4ff;
            --accent-glow: rgba(0, 212, 255, 0.4);
            --text-primary: #ffffff;
            --text-secondary: #8c8c9e;
            --danger: #ff3e5e;
            --success: #22c55e;
        }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body {
            background-color: var(--bg);
            color: var(--text-primary);
            font-family: 'Outfit', sans-serif;
            margin: 0;
            padding: 0;
            min-height: 100vh;
            overflow-x: hidden;
        }
        
        /* Layout Structure */
        .page-container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 20px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .logo-group { display: flex; align-items: center; gap: 12px; }
        .logo-dot { width: 12px; height: 12px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 15px var(--accent-glow); }
        h1 { margin: 0; font-size: 1.4rem; font-weight: 600; letter-spacing: -0.5px; }

        .header-actions { display: flex; align-items: center; gap: 12px; }
        
        /* Main Grid system */
        .main-content {
            display: grid;
            grid-template-columns: 1fr 380px;
            gap: 24px;
        }

        @media (max-width: 1024px) {
            .main-content { grid-template-columns: 1fr; }
            header { flex-direction: column; align-items: flex-start; }
            .header-actions { width: 100%; justify-content: space-between; }
        }

        /* Cards */
        .card { 
            background: var(--surface);
            border-radius: 20px;
            padding: 24px;
            border: 1px solid rgba(255,255,255,0.06);
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            position: relative;
        }
        .card h2 { font-size: 0.9rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 1px; margin-top: 0; margin-bottom: 20px; display: flex; align-items: center; gap: 10px; }
        
        /* Idle Section */
        .idle-banner {
            background: linear-gradient(90deg, #0a0a0f 0%, #11111a 100%);
            border-radius: 20px;
            padding: 20px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border: 1px solid rgba(0,212,255,0.2);
            margin-bottom: 20px;
        }
        .idle-info h3 { margin: 0; font-size: 0.8rem; color: var(--accent); opacity: 0.8; }
        .idle-info p { margin: 5px 0 0; font-size: 1.1rem; font-weight: 600; }

        /* Key Grid */
        .shortcut-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
            gap: 15px;
        }
        .key-slot {
            background: var(--surface-accent);
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.05);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            cursor: pointer;
            position: relative;
        }
        .key-slot:hover { transform: translateY(-5px); border-color: var(--accent); background: rgba(0,212,255,0.05); }
        .key-slot.active { border-color: var(--accent); box-shadow: 0 5px 20px var(--accent-glow); }
        .key-num { font-family: 'JetBrains Mono'; font-weight: 700; font-size: 1.5rem; color: var(--accent); display: block; }
        .key-file { font-size: 0.75rem; color: var(--text-secondary); margin-top: 10px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

        /* Library list */
        .library-list { display: flex; flex-direction: column; gap: 10px; max-height: 600px; overflow-y: auto; padding-right: 5px; }
        .library-list::-webkit-scrollbar { width: 4px; }
        .library-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 10px; }

        .media-item {
            display: flex; align-items: center; gap: 12px;
            padding: 14px; background: rgba(255,255,255,0.02); border-radius: 12px;
            border: 1px solid transparent; cursor: pointer; transition: 0.2s;
        }
        .media-item:hover { background: rgba(255,255,255,0.05); }
        .media-item.selected { border-color: var(--accent); background: rgba(0,212,255,0.05); }
        .media-meta { flex: 1; min-width: 0; }
        .media-name { font-weight: 500; font-size: 0.9rem; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .media-tag { font-size: 0.7rem; color: var(--text-secondary); }

        /* Buttons */
        .btn {
            background: rgba(255,255,255,0.05);
            color: #fff;
            border: none;
            padding: 10px 16px;
            border-radius: 10px;
            font-family: inherit; font-weight: 600; font-size: 0.85rem;
            cursor: pointer; transition: 0.2s;
            display: flex; align-items: center; gap: 8px;
        }
        .btn:hover { background: rgba(255,255,255,0.1); transform: scale(1.02); }
        .btn-accent { background: var(--accent); color: #000; box-shadow: 0 4px 15px var(--accent-glow); }
        .btn-sm { padding: 6px 10px; font-size: 0.75rem; }
        .btn-danger { color: var(--danger); background: rgba(255,62,94,0.1); }
        .btn-danger:hover { background: rgba(255,62,94,0.2); }

        /* Modals */
        .modal-overlay { 
            position: fixed; inset: 0; background: rgba(0,0,0,0.85); backdrop-filter: blur(8px);
            display: none; place-items: center; z-index: 2000; padding: 20px;
        }
        .modal-content { 
            background: var(--surface); border: 1px solid rgba(255,255,255,0.1);
            padding: 40px 30px; border-radius: 28px; width: 100%; max-width: 440px; text-align: center;
        }

        /* Responsive Mobile tweaks */
        @media (max-width: 480px) {
            .page-container { padding: 15px; }
            .shortcut-grid { grid-template-columns: repeat(2, 1fr); }
            h1 { font-size: 1.1rem; }
            .card { padding: 18px; }
        }

        /* Animations */
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.4; } 100% { opacity: 1; } }
        .sync-active { animation: pulse 1s infinite; }
    </style>
</head>
<body>
    <div class="page-container">
        <header>
            <div class="logo-group">
                <div class="logo-dot"></div>
                <h1>Kikos Beverages Console</h1>
            </div>
            <div class="header-actions">
                <button class="btn btn-accent" id="sync-btn" onclick="applyChanges()">
                    <span>Apply Changes</span>
                </button>
                <div style="font-size: 0.85rem; color: var(--text-secondary); background: var(--surface-accent); padding: 8px 16px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05);">
                    <span id="ip-addr">--</span>
                </div>
            </div>
        </header>

        <main class="main-content">
            <section class="config-view">
                <div class="idle-banner">
                    <div class="idle-info">
                        <h3>ACTIVE IDLE SCREEN</h3>
                        <p id="idle-display">Loading...</p>
                    </div>
                    <button class="btn btn-sm" style="border: 1px solid var(--accent); color: var(--accent);" onclick="setIdleFromSelected()">Set Selected</button>
                </div>

                <div class="card" style="padding: 10px; border-color: var(--accent); overflow: hidden;">
                    <div style="position: relative; width: 100%; aspect-ratio: 16/9; background: #000; border-radius: 12px; overflow: hidden;">
                        <img id="live-monitor" src="/api/mirror" style="width: 100%; height: 100%; object-fit: contain;">
                        <div style="position: absolute; top: 10px; left: 10px; background: rgba(255,0,0,0.8); color: #fff; padding: 4px 8px; border-radius: 6px; font-size: 0.6rem; font-weight: bold; letter-spacing: 1px;">LIVE MONITOR</div>
                    </div>
                </div>

                <div class="card">
                    <h2>Keyboard Matrix Assignments</h2>
                    <div class="shortcut-grid" id="key-grid">
                        <!-- slots -->
                    </div>
                </div>
            </section>

            <aside class="library-view">
                <div class="card" style="display: flex; flex-direction: column; gap: 20px;">
                    <h2>Media Library</h2>
                    <button class="btn btn-accent" style="width: 100%; justify-content: center;" onclick="document.getElementById('file-input').click()">+ Upload Video</button>
                    <input type="file" id="file-input" style="display:none;" onchange="uploadMedia(this.files[0])">
                    
                    <div class="library-list" id="library">
                        <!-- items -->
                    </div>
                </div>
            </aside>
        </main>
    </div>

    <div id="assign-modal" class="modal-overlay">
        <div class="modal-content">
            <div class="key-num" id="target-key-display" style="font-size: 4rem; margin-bottom: 10px;">1</div>
            <div style="color: var(--text-secondary); margin-bottom: 25px;">Mapping to Video</div>
            <div id="target-file-name" style="font-size: 1.2rem; font-weight: 600; color: var(--accent);">--</div>
            <div style="display: flex; gap: 12px; margin-top: 40px;">
                <button class="btn" style="flex:1; justify-content: center;" onclick="closeModal()">Cancel</button>
                <button class="btn btn-accent" style="flex:1; justify-content: center;" id="confirm-map">Confirm</button>
            </div>
        </div>
    </div>

    <script>
        let selectedFile = null;

        async function refresh() {
            const res = await fetch('/api/status');
            const data = await res.json();
            
            document.getElementById('ip-addr').innerText = data.system.ip;
            document.getElementById('idle-display').innerText = data.config.idle || "Not Assigned";
            
            renderGrid(data.config);
            renderLibrary(data.media);
        }

        function renderGrid(config) {
            const grid = document.getElementById('key-grid');
            grid.innerHTML = '';
            for (let i = 1; i <= 9; i++) {
                const file = config.mappings[i];
                const div = document.createElement('div');
                div.className = `key-slot ${file ? 'active' : ''}`;
                div.innerHTML = `
                    <span class="key-num">${i}</span>
                    <span class="key-file">${file || '—'}</span>
                `;
                div.onclick = () => startMapping(i);
                grid.appendChild(div);
            }
        }

        function renderLibrary(media) {
            const lib = document.getElementById('library');
            lib.innerHTML = media.map(file => `
                <div class="media-item ${selectedFile === file ? 'selected' : ''}" onclick="selectFile('${file}')">
                    <div class="media-meta">
                        <span class="media-name">${file}</span>
                        <span class="media-tag">Video Content</span>
                    </div>
                    <button class="btn btn-sm btn-danger" onclick="deleteVideo('${file}', event)">&times;</button>
                </div>
            `).join('');
        }

        function selectFile(file) {
            selectedFile = file;
            document.querySelectorAll('.media-item').forEach(e => {
                e.classList.toggle('selected', e.innerText.includes(file));
            });
            renderLibrary(currentState.media); // simple hack
        }

        async function applyChanges() {
            const btn = document.getElementById('sync-btn');
            btn.classList.add('sync-active');
            btn.innerText = "Syncing...";
            
            await fetch('/api/apply', { method: 'POST' });
            
            setTimeout(() => {
                btn.classList.remove('sync-active');
                btn.innerText = "Apply Changes";
                refresh();
            }, 800);
        }

        // Live Mirror Heartbeat
        setInterval(() => {
            const img = document.getElementById('live-monitor');
            if (img) img.src = "/api/mirror?t=" + Date.now();
        }, 2000);

        function startMapping(key) {
            if (!selectedFile) {
                alert("Please select a video from the library first!");
                return;
            }
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

        function closeModal() { document.getElementById('assign-modal').style.display = 'none'; }
        
        let currentState = { media: [] };
        async function init() {
            const res = await fetch('/api/status');
            currentState = await res.json();
            refresh();
        }
        init();
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
