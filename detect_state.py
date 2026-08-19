"""Detect round state from player positions on minimap."""
import sys, json
sys.path.insert(0, 'src')
import cv2
import numpy as np
from vantage.cv.detect import detect_markers_ml
from vantage.cv.profiles import SLIGGY_720

video = cv2.VideoCapture("twitch_data/breeze_full.mp4")
MX, MY, MW, MH = 23, 29, 256, 242
labels = json.loads(open("twitch_data/twitch_labels.json").read())

def estimate_round_state(ally_dets, enemy_dets):
    """Estimate round state from player positions.
    
    Buy phase: allies clustered at spawn (bottom area), few/no enemies visible.
    Round active: players spread across the map, both teams visible.
    Post-plant: fewer visible players, possible spike dot.
    """
    n_ally = len(ally_dets)
    n_enemy = len(enemy_dets)
    n_total = n_ally + n_enemy
    
    if n_total == 0:
        return "unknown"
    
    # Check if allies are clustered at spawn (bottom of minimap)
    if n_ally >= 3:
        ally_ys = [d["y"] for d in ally_dets]
        mean_ally_y = np.mean(ally_ys)
        ally_std_y = np.std(ally_ys)
        
        # Spawn is typically at bottom (y > 180 on 242-high minimap)
        if mean_ally_y > 160 and ally_std_y < 30:
            return "buy_phase"
    
    # Both teams visible and spread = round active
    if n_ally >= 2 and n_enemy >= 2:
        return "round_active"
    
    # Only allies visible, spread across map
    if n_ally >= 3 and n_enemy == 0:
        return "round_active"  # might be early round before contact
    
    # Few players visible
    if n_total <= 2:
        return "late_round"
    
    return "round_active"

# Test on labeled frames
print("Round state estimation:")
for fi_str in sorted(labels.keys(), key=int):
    fi = int(fi_str)
    video.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, frame = video.read()
    if not ret:
        continue
    crop = frame[MY:MY+MH, MX:MX+MW]
    result = detect_markers_ml(crop, SLIGGY_720)
    
    state = estimate_round_state(result.ally, result.enemy)
    gt = labels[fi_str]
    gt_ally = [p for p in gt if p["team"] == "ally"]
    gt_enemy = [p for p in gt if p["team"] == "enemy"]
    
    print(f"  Frame {fi:>5} ({fi/30:6.1f}s): {state:12s} | "
          f"det={len(result.ally)}+{len(result.enemy)} | "
          f"gt={len(gt_ally)}+{len(gt_enemy)}")

video.release()
