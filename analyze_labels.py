"""Analyze pixel colors at labeled player positions to build a better detector."""

import json
import cv2
import numpy as np
from pathlib import Path
from collections import defaultdict


# Load labels
labels_path = Path(__file__).parent / "data" / "labels" / "match730541_map1" / "player_labels_m1.json"
labels = json.loads(labels_path.read_text(encoding="utf-8"))

frames_dir = Path(__file__).parent / "data" / "labels" / "match730541_map1" / "frames_m1"

# Collect pixel samples at each labeled position
ally_samples = []  # (hue, sat, val) tuples
enemy_samples = []

# For each frame, sample a small patch around each labeled position
PATCH_RADIUS = 4  # sample 9x9 patch

print("Analyzing pixel colors at labeled positions...\n")

for frame_idx_str, frame_labels in labels.items():
    frame_idx = int(frame_idx_str)
    img_path = frames_dir / f"{frame_idx}.jpg"
    if not img_path.exists():
        continue
    
    minimap = cv2.imread(str(img_path))
    hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
    
    for p in frame_labels:
        x, y = p["x"], p["y"]
        team = p["team"]
        
        # Sample patch around position
        y_min = max(0, y - PATCH_RADIUS)
        y_max = min(hsv.shape[0], y + PATCH_RADIUS + 1)
        x_min = max(0, x - PATCH_RADIUS)
        x_max = min(hsv.shape[1], x + PATCH_RADIUS + 1)
        
        patch_hsv = hsv[y_min:y_max, x_min:x_max]
        
        # Get the most saturated pixels in the patch (likely the ring border)
        sat = patch_hsv[:,:,1]
        val = patch_hsv[:,:,2]
        hue = patch_hsv[:,:,0]
        
        # Sample top 5 most saturated pixels
        flat_sat = sat.flatten()
        flat_val = val.flatten()
        flat_hue = hue.flatten()
        
        top_indices = np.argsort(flat_sat)[-5:]
        
        for idx in top_indices:
            h, s, v = int(flat_hue[idx]), int(flat_sat[idx]), int(flat_val[idx])
            if s > 30 and v > 30:  # skip dark/gray pixels
                sample = (h, s, v)
                if team == "ally":
                    ally_samples.append(sample)
                else:
                    enemy_samples.append(sample)

print(f"Ally samples: {len(ally_samples)}")
print(f"Enemy samples: {len(enemy_samples)}")

# Analyze ally colors
if ally_samples:
    ally_arr = np.array(ally_samples)
    print(f"\n=== ALLY (cyan) ===")
    print(f"  Hue:     min={ally_arr[:,0].min()} max={ally_arr[:,0].max()} mean={ally_arr[:,0].mean():.1f} median={np.median(ally_arr[:,0]):.0f}")
    print(f"  Sat:     min={ally_arr[:,1].min()} max={ally_arr[:,1].max()} mean={ally_arr[:,1].mean():.1f}")
    print(f"  Val:     min={ally_arr[:,2].min()} max={ally_arr[:,2].max()} mean={ally_arr[:,2].mean():.1f}")
    
    # Histogram of hues
    hue_hist = np.bincount(ally_arr[:,0], minlength=181)
    top_hues = np.argsort(hue_hist)[-10:][::-1]
    print(f"  Top hues: {[(int(h), int(hue_hist[h])) for h in top_hues if hue_hist[h] > 0]}")

# Analyze enemy colors
if enemy_samples:
    enemy_arr = np.array(enemy_samples)
    print(f"\n=== ENEMY (red) ===")
    print(f"  Hue:     min={enemy_arr[:,0].min()} max={enemy_arr[:,0].max()} mean={enemy_arr[:,0].mean():.1f} median={np.median(enemy_arr[:,0]):.0f}")
    print(f"  Sat:     min={enemy_arr[:,1].min()} max={enemy_arr[:,1].max()} mean={enemy_arr[:,1].mean():.1f}")
    print(f"  Val:     min={enemy_arr[:,2].min()} max={enemy_arr[:,2].max()} mean={enemy_arr[:,2].mean():.1f}")
    
    hue_hist = np.bincount(enemy_arr[:,0], minlength=181)
    top_hues = np.argsort(hue_hist)[-10:][::-1]
    print(f"  Top hues: {[(int(h), int(hue_hist[h])) for h in top_hues if hue_hist[h] > 0]}")

# Also analyze what the map background looks like at known positions
print(f"\n=== MAP BACKGROUND (sample from empty areas) ===")
bg_hues = []
bg_sats = []
bg_vals = []

# Sample from areas that are NOT near any labeled player
for frame_idx_str in list(labels.keys())[:5]:
    frame_idx = int(frame_idx_str)
    img_path = frames_dir / f"{frame_idx}.jpg"
    if not img_path.exists():
        continue
    minimap = cv2.imread(str(img_path))
    hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
    
    # Sample from center of minimap (likely map content)
    for cy in range(50, 300, 25):
        for cx in range(50, 350, 25):
            # Check if far from any labeled player
            too_close = False
            for p in labels[frame_idx_str]:
                if abs(cx - p["x"]) < 20 and abs(cy - p["y"]) < 20:
                    too_close = True
                    break
            if not too_close:
                bg_hues.append(int(hsv[cy, cx, 0]))
                bg_sats.append(int(hsv[cy, cx, 1]))
                bg_vals.append(int(hsv[cy, cx, 2]))

print(f"  Hue: min={min(bg_hues)} max={max(bg_hues)} mean={np.mean(bg_hues):.1f}")
print(f"  Sat: min={min(bg_sats)} max={max(bg_sats)} mean={np.mean(bg_sats):.1f}")
print(f"  Val: min={min(bg_vals)} max={max(bg_vals)} mean={np.mean(bg_vals):.1f}")
hue_hist = np.bincount(bg_hues, minlength=181)
top_hues = np.argsort(hue_hist)[-5:][::-1]
print(f"  Top hues: {[(h, int(hue_hist[h])) for h in top_hues if hue_hist[h] > 0]}")

# Save analysis results
analysis = {
    "ally_hsv_range": {
        "hue": [int(ally_arr[:,0].min()), int(ally_arr[:,0].max())] if len(ally_samples) > 0 else [0,0],
        "sat": [int(ally_arr[:,1].min()), int(ally_arr[:,1].max())] if len(ally_samples) > 0 else [0,0],
        "val": [int(ally_arr[:,2].min()), int(ally_arr[:,2].max())] if len(ally_samples) > 0 else [0,0],
    },
    "enemy_hsv_range": {
        "hue": [int(enemy_arr[:,0].min()), int(enemy_arr[:,0].max())] if len(enemy_samples) > 0 else [0,0],
        "sat": [int(enemy_arr[:,1].min()), int(enemy_arr[:,1].max())] if len(enemy_samples) > 0 else [0,0],
        "val": [int(enemy_arr[:,2].min()), int(enemy_arr[:,2].max())] if len(enemy_samples) > 0 else [0,0],
    },
    "bg_hsv_range": {
        "hue": [min(bg_hues), max(bg_hues)],
        "sat": [min(bg_sats), max(bg_sats)],
        "val": [min(bg_vals), max(bg_vals)],
    }
}

out_path = Path(__file__).parent / "data" / "labels" / "match730541_map1" / "hsv_analysis.json"
out_path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
print(f"\nSaved analysis to {out_path}")
