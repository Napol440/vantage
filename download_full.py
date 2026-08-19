"""Download full Breeze map from Twitch in 5-minute chunks."""
import subprocess, sys, os, time
from pathlib import Path

TWITCH_URL = "https://www.twitch.tv/videos/2847663252"
START = 924      # 15:24 - Breeze map start
CHUNK_SIZE = 300  # 5 minutes per chunk
NUM_CHUNKS = 6    # 30 minutes total
FFMPEG = r"C:\Users\Napol\ffmpeg.exe"
OUT_DIR = Path("twitch_data/chunks")
OUT_DIR.mkdir(parents=True, exist_ok=True)

for i in range(NUM_CHUNKS):
    chunk_start = START + i * CHUNK_SIZE
    chunk_end = chunk_start + CHUNK_SIZE
    out_file = OUT_DIR / f"chunk_{i:02d}.mp4"

    if out_file.exists() and out_file.stat().st_size > 100000:
        sz = out_file.stat().st_size / (1024*1024)
        print(f"Chunk {i} already exists ({sz:.1f} MB), skipping")
        continue

    print(f"\n=== Chunk {i}: {chunk_start}s - {chunk_end}s ({chunk_start//60}:{chunk_start%60:02d} - {chunk_end//60}:{chunk_end%60:02d}) ===")
    t0 = time.time()

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "720p60",
        "-o", str(out_file),
        "--force-keyframes-at-cuts",
        "--download-sections", f"*{chunk_start}-{chunk_end}",
        "--ffmpeg-location", str(Path(FFMPEG).parent),
        TWITCH_URL,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if out_file.exists():
        elapsed = time.time() - t0
        size_mb = out_file.stat().st_size / (1024*1024)
        print(f"  Done: {size_mb:.1f} MB in {elapsed:.0f}s")
    else:
        print(f"  FAILED: {result.stderr[-500:]}")

print("\n=== All chunks downloaded ===")
for f in sorted(OUT_DIR.glob("chunk_*.mp4")):
    print(f"  {f.name}: {f.stat().st_size / (1024*1024):.1f} MB")
