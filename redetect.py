"""Re-run detection with forced correct minimap bbox."""
import sys, json, time
sys.path.insert(0, 'src')

import cv2
import numpy as np
from pathlib import Path
from vantage.cv.profiles import VCT_OFFICIAL
from vantage.cv.detect import detect_markers

profile = VCT_OFFICIAL
video = cv2.VideoCapture("twitch_data/breeze_full.mp4")

# Force the correct minimap bbox for Sliggy 720p
MX, MY, MW, MH = 23, 29, 256, 242

total = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
print(f"Processing {total} frames with forced bbox ({MX},{MY},{MW},{MH})...")

t0 = time.time()
results = []
detected_count = 0

for i in range(total):
    ret, frame = video.read()
    if not ret:
        break

    crop = frame[MY:MY+MH, MX:MX+MW]
    det = detect_markers(crop, profile)
    ally = len(det.ally)
    enemy = len(det.enemy)

    entry = {
        'frame': i,
        'pts_s': round(i / 6.0, 2),
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

    if i % 600 == 0:
        elapsed = time.time() - t0
        print(f"  Frame {i}/{total} ({100*i/total:.0f}%) - {detected_count} detected ({elapsed:.0f}s)")

video.release()
elapsed = time.time() - t0

detected = [r for r in results if r['total'] > 0]
print(f"\nDone in {elapsed:.0f}s")
print(f"Frames with detections: {len(detected)}/{len(results)} ({100*len(detected)/len(results):.1f}%)")
if detected:
    print(f"Avg per frame: {sum(r['ally'] for r in detected)/len(detected):.1f} ally, {sum(r['enemy'] for r in detected)/len(detected):.1f} enemy")
    print(f"Max: {max(r['total'] for r in detected)}")
    print(f"10/10: {sum(1 for r in detected if r['total'] >= 10)}")

with open("twitch_data/detections_full.json", "w") as f:
    json.dump(results, f)
print("Saved detections_full.json")
