"""Interactive labeling tool for Twitch minimap frames - auto-saves to JSON."""
import cv2
import numpy as np
import json
import base64, io
from pathlib import Path

video = cv2.VideoCapture("twitch_data/breeze_full.mp4")
MX, MY, MW, MH = 23, 29, 256, 242
total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))

# Load existing labels
labels_path = Path("twitch_data/twitch_labels.json")
existing = json.loads(labels_path.read_text()) if labels_path.exists() else {}

# Generate 20 frames spread across the video, avoiding already-labeled frames
existing_fis = set(int(k) for k in existing.keys())
np.random.seed(123)
candidate_fis = sorted(set([
    int(fi) for fi in np.random.choice(range(924, total_frames - 100), 200, replace=False)
    if int(fi) not in existing_fis
]))
# Pick 20 well-spaced ones
step = max(1, len(candidate_fis) // 20)
frames_to_label = candidate_fis[::step][:20]
print(f"Labeling {len(frames_to_label)} new frames (have {len(existing_fis)} already)")

all_frames = []
for fi in frames_to_label:
    video.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, frame = video.read()
    if not ret:
        continue
    crop = frame[MY:MY+MH, MX:MX+MW]
    pil_img = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    from PIL import Image
    img = Image.fromarray(pil_img)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode()
    all_frames.append({"frame": int(fi), "b64": b64, "width": MW, "height": MH})

video.release()

frames_json = json.dumps(all_frames)
existing_json = json.dumps(existing)

html = f'''<!DOCTYPE html>
<html>
<head>
<style>
body {{ background: #111; color: #fff; font-family: monospace; margin: 20px; }}
.frame {{ display: inline-block; margin: 10px; vertical-align: top; }}
.frame canvas {{ border: 1px solid #333; cursor: crosshair; image-rendering: pixelated; }}
.frame h3 {{ margin: 5px 0; font-size: 14px; }}
.info {{ font-size: 11px; color: #888; margin: 5px 0; }}
#status {{ font-size: 14px; margin: 10px 0; padding: 10px; background: #222; border-radius: 4px; }}
button {{ padding: 8px 16px; margin: 5px; font-size: 14px; cursor: pointer; border: none; border-radius: 4px; }}
.btn-ally {{ background: #0ff; color: #000; }}
.btn-enemy {{ background: #f44; color: #fff; }}
.btn-save {{ background: #0f0; color: #000; font-weight: bold; }}
.btn-undo {{ background: #666; color: #fff; }}
.btn-nav {{ background: #448; color: #fff; }}
#grid {{ display: flex; flex-wrap: wrap; }}
</style>
</head>
<body>
<h2>Label Player Positions on Twitch Minimap</h2>
<p>1. Click <b style="color:#0ff">Ally</b> or <b style="color:#f44">Enemy</b> button to set team<br>
2. Click on each player ring/circle on the minimap<br>
3. When done, click <b style="color:#0f0">Save</b> to download JSON</p>
<div>
  <button class="btn-ally" onclick="team='ally';updateStatus()">Ally (Cyan)</button>
  <button class="btn-enemy" onclick="team='enemy';updateStatus()">Enemy (Red)</button>
  <button class="btn-undo" onclick="undoLast()">Undo Last</button>
  <button class="btn-save" onclick="saveLabels()">Save Labels (download JSON)</button>
  <button class="btn-nav" onclick="showOnlyLabeled()">Show Only Labeled</button>
  <button class="btn-nav" onclick="showAll()">Show All</button>
</div>
<div id="status">Team: <span id="teamLabel" style="color:#0ff">ally</span> | 
  Points this frame: <span id="count">0</span> | 
  Total labeled: <span id="total">{sum(len(v) for v in existing.values())}</span></div>
<div id="grid"></div>
<div id="output"></div>
<script>
const frames = {frames_json};
const existing = {existing_json};
let team = 'ally';
let allLabels = Object.assign({{}}, existing);

function teamColor(t) {{ return t === 'ally' ? '#0ff' : '#f44'; }}

function updateStatus() {{
    document.getElementById('teamLabel').textContent = team;
    document.getElementById('teamLabel').style.color = teamColor(team);
}}

frames.forEach(f => {{
    const div = document.createElement('div');
    div.className = 'frame';
    div.id = 'frame-' + f.frame;
    div.innerHTML = `<h3>Frame ${{f.frame}} (${{(f.frame/30).toFixed(0)}}s)</h3>`;
    
    const canvas = document.createElement('canvas');
    canvas.width = f.width;
    canvas.height = f.height;
    canvas.style.width = (f.width * 2) + 'px';
    canvas.style.height = (f.height * 2) + 'px';
    const ctx = canvas.getContext('2d');
    
    const img = new Image();
    img.onload = () => {{
        ctx.drawImage(img, 0, 0);
        // Draw existing labels
        if (allLabels[f.frame]) {{
            allLabels[f.frame].forEach(p => {{
                ctx.beginPath();
                ctx.arc(p.x, p.y, 5, 0, 2 * Math.PI);
                ctx.strokeStyle = teamColor(p.team);
                ctx.lineWidth = 2;
                ctx.stroke();
            }});
        }}
    }};
    img.src = 'data:image/png;base64,' + f.b64;
    
    canvas.addEventListener('click', e => {{
        const r = canvas.getBoundingClientRect();
        const scaleX = f.width / r.width;
        const scaleY = f.height / r.height;
        const x = Math.round((e.clientX - r.left) * scaleX);
        const y = Math.round((e.clientY - r.top) * scaleY);
        
        if (!allLabels[f.frame]) allLabels[f.frame] = [];
        allLabels[f.frame].push({{x, y, team}});
        
        ctx.beginPath();
        ctx.arc(x, y, 5, 0, 2 * Math.PI);
        ctx.strokeStyle = teamColor(team);
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.fillStyle = teamColor(team);
        ctx.font = '10px monospace';
        ctx.fillText(team[0].toUpperCase(), x + 7, y + 4);
        
        updateCounts();
    }});
    
    div.appendChild(canvas);
    document.getElementById('grid').appendChild(div);
}});

function updateCounts() {{
    let total = 0;
    for (const fi in allLabels) total += allLabels[fi].length;
    document.getElementById('total').textContent = total;
}}

function undoLast() {{
    // Find the last frame with labels
    const sorted = Object.keys(allLabels).map(Number).sort((a,b) => b - a);
    for (const fi of sorted) {{
        if (allLabels[fi] && allLabels[fi].length > 0) {{
            allLabels[fi].pop();
            if (allLabels[fi].length === 0) delete allLabels[fi];
            location.reload();
            return;
        }}
    }}
}}

function saveLabels() {{
    const blob = new Blob([JSON.stringify(allLabels, null, 2)], {{type: 'application/json'}});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'twitch_labels.json';
    a.click();
    URL.revokeObjectURL(url);
    document.getElementById('output').innerHTML = '<p style="color:#0f0">Saved! File downloaded as twitch_labels.json</p>';
}}

function showOnlyLabeled() {{
    frames.forEach(f => {{
        const div = document.getElementById('frame-' + f.frame);
        if (allLabels[f.frame] && allLabels[f.frame].length > 0) {{
            div.style.display = 'inline-block';
        }} else {{
            div.style.display = 'none';
        }}
    }});
}}

function showAll() {{
    frames.forEach(f => {{
        document.getElementById('frame-' + f.frame).style.display = 'inline-block';
    }});
}}
</script>
</body></html>'''

out_path = Path("twitch_data/label_twitch_new.html")
out_path.write_text(html)
print(f"\nCreated {out_path}")
print(f"Open in browser to label {len(frames_to_label)} new frames")
