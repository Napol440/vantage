"""Minimap calibration workflow (Component 3, M4 support tool).

Human-in-the-loop minimap localisation ground truth:

1. ``extract_frames`` - stream a map window, save a spread of frames (jpg)
   plus a ``manifest.csv`` the user fills in (or uses label_tool.html for).
2. ``import_labels``  - read the CSV, upsert rows into the ``labels`` table.
3. ``eval_agreement`` - re-run ``localize_minimap`` over the labelled frames
   and report per-kind agreement (the M7 validation-gate precursor).

The CSV columns are: ``frame_index,file,kind,x,y,w,h`` where ``kind`` is
``overview`` | ``corner`` | ``none`` and x..h are the minimap bbox (empty for
``none``). Coordinates are in working-height display space.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Optional

import numpy as np

from ..config import CvConfig
from ..models import Vod
from ..storage import Storage
from .ingest import stream_vod_window
from .localize import MinimapRegion, localize_minimap
from .profiles import Profile

MANIFEST_COLS = ["frame_index", "file", "kind", "x", "y", "w", "h"]


def extract_frames(vod: Vod, cfg: CvConfig, out_dir: Path,
                   step: int = 6, max_frames: int = 40,
                   duration_s: Optional[int] = None,
                   save: bool = True) -> list[dict]:
    """Save a spread of frames from ``vod`` and return the manifest rows.

    ``step`` samples every Nth frame (default 6 -> one/second at 6fps).
    Rows are keyed by ``frame_index``; subsequent runs overwrite in place.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stream, frames = stream_vod_window(vod, cfg, duration_s=duration_s)
    rows: list[dict] = []
    for frame in frames:
        if frame.index % step != 0:
            continue
        if len(rows) >= max_frames:
            break
        file = f"frame_{frame.index:05d}.jpg"
        if save:
            frame.save(out_dir / file)
        rows.append({"frame_index": frame.index, "file": file,
                     "img_w": frame.image.shape[1], "img_h": frame.image.shape[0],
                     "kind": "", "x": "", "y": "", "w": "", "h": ""})
    _write_manifest(out_dir, rows)
    return rows


def _write_manifest(out_dir: Path, rows: list[dict]) -> None:
    with (out_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_COLS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def import_labels(cfg: CvConfig, manifest: Path, match_id: int,
                  map_number: int) -> int:
    """Upsert manually-labelled rows from a CSV into the ``labels`` table."""
    n = 0
    with Storage(cfg.db_path) as db:
        with manifest.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                kind = (row.get("kind") or "").strip()
                if not kind:
                    continue
                x = _to_float(row.get("x"))
                y = _to_float(row.get("y"))
                w = _to_float(row.get("w"))
                h = _to_float(row.get("h"))
                if kind == "none":
                    x = y = 0.0
                    w = h = None
                elif None in (x, y, w, h):
                    print(f"  skip frame {row.get('frame_index')}: bad bbox for kind={kind}")
                    continue
                db.upsert_label(match_id=match_id, map_number=map_number,
                                frame_index=int(row["frame_index"]), kind=kind,
                                x_px=x, y_px=y, w_px=w, h_px=h)
                n += 1
    return n


def _to_float(v: Optional[str]) -> Optional[float]:
    if v is None or str(v).strip() == "":
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def eval_agreement(vod: Vod, cfg: CvConfig, profile: Profile,
                   match_id: int, map_number: int,
                   duration_s: Optional[int] = None) -> dict:
    """Compare ``localize_minimap`` against labelled ground truth.

    Returns a dict of per-kind stats plus overall accuracy over frames that
    have exactly one label. ``none`` frames count when no region is found.
    """
    with Storage(cfg.db_path) as db:
        labels = db.get_labels(match_id, map_number)

    from collections import Counter

    counts: Counter = Counter()      # (label_kind, pred_kind)
    per_kind: dict = {}
    indexed = {}
    for lab in labels:
        indexed.setdefault(lab["frame_index"], []).append(lab)

    stream, frames = stream_vod_window(vod, cfg, duration_s=duration_s)
    for frame in frames:
        labs = indexed.get(frame.index, [])
        if not labs or len(labs) > 1:
            continue  # skip unlabelled / ambiguous frames
        lab = labs[0]
        region = localize_minimap(frame.image, profile)
        pred = region.kind if region else "none"
        counts[(lab["kind"], pred)] += 1

    kinds = ["overview", "corner", "none"]
    for k in kinds:
        tp = counts.get((k, k), 0)
        n = sum(v for (lk, _), v in counts.items() if lk == k)
        per_kind[k] = {"tp": tp, "n": n,
                       "recall": tp / n if n else None}
    total = sum(counts.values())
    agree = sum(counts.get((k, k), 0) for k in kinds)
    return {"frames": total, "accuracy": agree / total if total else None,
            "per_kind": per_kind, "confusion": dict(counts)}


def write_label_tool(out_dir: Path, rows: list[dict]) -> Path:
    """Write the self-contained HTML labeling tool (label_tool.html)."""
    files = "["
    files += ",".join(
        f'{{i:{r["frame_index"]},w:{r["img_w"]},h:{r["img_h"]},f:"{r["file"]}"}}'
        for r in rows
    )
    files += "]"
    tool = out_dir / "label_tool.html"
    tool.write_text(_LABEL_TOOL_HTML.replace("__FILES__", files), encoding="utf-8")
    return tool


_LABEL_TOOL_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Vantage minimap label tool</title>
<style>
  body{font-family:system-ui,sans-serif;margin:16px;background:#111;color:#eee}
  #img{border:1px solid #444;background:#000;touch-action:none;cursor:crosshair;
       user-select:none;-webkit-user-select:none;-webkit-user-drag:none}
  .bar{display:flex;gap:8px;align-items:center;margin:8px 0;flex-wrap:wrap}
  button{padding:6px 14px;cursor:pointer}
  .kind.overview{background:#1d5c1d}.kind.corner{background:#5c4a1d}
  .kind.none{background:#333}
  #status{font-family:monospace;font-size:13px}
  #box{position:absolute;border:2px solid #0f0;pointer-events:none;display:none}
</style></head>
<body>
<h2>Vantage minimap label tool</h2>
<p>Draw a box around the minimap, choose its kind, then Save &amp; Next.
Finished -> Export CSV, then run the CLI import.</p>
<div class="bar">
  <button id="prev">Prev</button>
  <span id="idx">0/0</span>
  <button id="next">Next</button>
  <button class="kind overview" id="k-overview">Overview</button>
  <button class="kind corner" id="k-corner">Corner</button>
  <button class="kind none" id="k-none">None (no minimap)</button>
  <button id="save">Save &amp; Next</button>
  <button id="export">Export CSV</button>
</div>
<div id="wrap" style="position:relative;display:inline-block">
  <canvas id="img" width="1920" height="1080"></canvas>
  <div id="box"></div>
</div>
<div id="status"></div>
<script>
const FILES = __FILES__;
const storageKey = "vantage_labels_v2_" + location.pathname;
let labels = {};
try { labels = JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch(e) {}
let i = 0, cur = null, start = null, drag = false;

function load() {
  cur = labels[FILES[i].f] || {kind:null,x:null,y:null,w:null,h:null};
  document.getElementById("idx").textContent = (i+1) + "/" + FILES.length;
  draw();
  const b = document.getElementById("box");
  if (cur.x !== null) { b.style.display = "block";
    const s = canvasScale(); b.style.left = cur.x*s+"px"; b.style.top = cur.y*s+"px";
    b.style.width = cur.w*s+"px"; b.style.height = cur.h*s+"px"; }
  else b.style.display = "none";
  status();
}
function canvasScale(){ const c=document.getElementById("img");
  return c.width/FILES[i].w; }
function draw(){
  const c=document.getElementById("img"), ctx=c.getContext("2d");
  const img=new Image();
  img.onload=()=>{ c.width=img.naturalWidth; c.height=img.naturalHeight;
    ctx.drawImage(img,0,0); };
  img.src=FILES[i].f;
}
function status(){
  let s = "kind=" + (cur.kind||"-");
  if(cur.x!==null) s += " box=(" + Math.round(cur.x) + "," + Math.round(cur.y) +
     " " + Math.round(cur.w) + "x" + Math.round(cur.h) + ")";
  document.getElementById("status").textContent = s;
}
function save(){
  if(cur.kind && cur.x!==null) labels[FILES[i].f] = cur;
  localStorage.setItem(storageKey, JSON.stringify(labels));
}
document.getElementById("prev").onclick=()=>{ if(i>0){i--;load();} };
document.getElementById("next").onclick=()=>{ if(i<FILES.length-1){i++;load();} };
document.getElementById("save").onclick=()=>{ save(); if(i<FILES.length-1){i++;load();} };
for (const k of ["overview","corner","none"]) {
  document.getElementById("k-"+k).onclick=()=>{
    cur.kind=k; if(k==="none"){cur.x=null;cur.w=null;}
    status(); };
}
const c=document.getElementById("img");
c.onpointerdown=e=>{ const r=c.getBoundingClientRect();
  start={x:(e.clientX-r.left)*FILES[i].w/c.width, y:(e.clientY-r.top)*FILES[i].h/c.height};
  drag=true; c.setPointerCapture(e.pointerId); };
c.onpointermove=e=>{ if(!drag)return; const r=c.getBoundingClientRect();
  const ex=(e.clientX-r.left)*FILES[i].w/c.width, ey=(e.clientY-r.top)*FILES[i].h/c.height;
  const b=document.getElementById("box"), s=canvasScale();
  b.style.display="block";
  b.style.left=Math.min(start.x,ex)*s+"px"; b.style.top=Math.min(start.y,ey)*s+"px";
  b.style.width=Math.abs(ex-start.x)*s+"px"; b.style.height=Math.abs(ey-start.y)*s+"px";
  e.preventDefault(); };
c.onpointerup=e=>{ if(!drag)return; drag=false; const r=c.getBoundingClientRect();
  const ex=(e.clientX-r.left)*FILES[i].w/c.width, ey=(e.clientY-r.top)*FILES[i].h/c.height;
  cur.x=Math.round(Math.min(start.x,ex)); cur.y=Math.round(Math.min(start.y,ey));
  cur.w=Math.round(Math.abs(ex-start.x)); cur.h=Math.round(Math.abs(ey-start.y));
  status(); };
document.getElementById("export").onclick=()=>{
  const rows=["frame_index,file,kind,x,y,w,h"];
  FILES.forEach((f,j)=>{ const L=labels[f.f]; if(L&&L.kind&&L.x!==null){
    rows.push([f.i,f.f,L.kind,L.x,L.y,L.w,L.h].join(",")); }
    else rows.push([f.i,f.f,"none","","","",""].join(",")); });
  const blob=new Blob([rows.join("\\n")],{type:"text/csv"});
  const a=document.createElement("a");
  a.href=URL.createObjectURL(blob); a.download="manifest.csv"; a.click();
};
load();
</script></body></html>
"""
