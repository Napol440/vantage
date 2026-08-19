"""Run full detection pipeline on Breeze 720p."""
import sys, json, time
sys.path.insert(0, 'src')

import cv2
import numpy as np
from pathlib import Path
from vantage.cv.profiles import VCT_OFFICIAL
from vantage.cv.detect import detect_markers
from vantage.cv.localize import localize_minimap
from vantage.cv.ingest import FrameStream
from vantage.config import CvConfig

cfg = CvConfig()
profile = VCT_OFFICIAL
video = Path("twitch_data/breeze_full.mp4")

print("Extracting frames at 6 fps from 720p...")
t0 = time.time()
frames = list(FrameStream(video, cfg))
elapsed = time.time() - t0
print(f"Got {len(frames)} frames in {elapsed:.0f}s ({len(frames)/elapsed:.1f} fps)")

print("\nRunning detection on all frames...")
t1 = time.time()
results = []
detected_count = 0

for i, frame in enumerate(frames):
    region = localize_minimap(frame.image, profile, use_calibration=True)
    if not region:
        results.append({'frame': i, 'pts_s': round(frame.pts_s, 2), 'ally': 0, 'enemy': 0})
        continue

    crop = region.crop(frame.image)
    det = detect_markers(crop, profile)
    ally = len(det.ally)
    enemy = len(det.enemy)

    entry = {
        'frame': i,
        'pts_s': round(frame.pts_s, 2),
        'bbox': f"({region.x},{region.y},{region.w},{region.h})",
        'kind': region.kind,
        'ally': ally,
        'enemy': enemy,
        'total': ally + enemy,
        'positions': {
            'ally': [{'x': round(d['x'], 1), 'y': round(d['y'], 1), 'area': round(d['area'], 0)} for d in det.ally],
            'enemy': [{'x': round(d['x'], 1), 'y': round(d['y'], 1), 'area': round(d['area'], 0)} for d in det.enemy],
        }
    }
    results.append(entry)

    if ally + enemy > 0:
        detected_count += 1

    if i % 300 == 0:
        pct = 100 * i / len(frames)
        print(f"  Frame {i}/{len(frames)} ({pct:.0f}%) - detected so far: {detected_count}")

elapsed2 = time.time() - t1
print(f"\nDetection complete in {elapsed2:.0f}s ({len(frames)/elapsed2:.1f} frames/s)")

# Summary
detected = [r for r in results if r.get('total', 0) > 0]
print(f"\n=== Summary ===")
print(f"Total frames: {len(results)}")
print(f"Frames with detections: {len(detected)} ({100*len(detected)/len(results):.1f}%)")
if detected:
    ally_counts = [r['ally'] for r in detected]
    enemy_counts = [r['enemy'] for r in detected]
    total_counts = [r['total'] for r in detected]
    print(f"Avg per frame: {sum(ally_counts)/len(ally_counts):.1f} ally, {sum(enemy_counts)/len(enemy_counts):.1f} enemy = {sum(total_counts)/len(total_counts):.1f} total")
    print(f"Max in a frame: {max(total_counts)}")
    print(f"Frames with 10/10: {sum(1 for t in total_counts if t >= 10)}")

# Save
out = Path("twitch_data/detections_full.json")
with open(out, "w") as f:
    json.dump(results, f)
print(f"\nSaved {len(results)} frames to {out}")
