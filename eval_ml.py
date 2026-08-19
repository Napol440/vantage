"""Full evaluation of detect_markers_ml on all labeled frames."""
import sys, json
sys.path.insert(0, 'src')
import cv2
import numpy as np
from vantage.cv.detect import detect_markers_ml, detect_markers
from vantage.cv.profiles import SLIGGY_720

video = cv2.VideoCapture("twitch_data/breeze_full.mp4")
MX, MY, MW, MH = 23, 29, 256, 242
labels = json.loads(open("twitch_data/twitch_labels.json").read())

def match_dets(dets, gt, threshold=12):
    matched, used = 0, set()
    for d in dets:
        best, best_j = 999, -1
        for j, p in enumerate(gt):
            if j in used:
                continue
            dist = ((d["x"] - p["x"])**2 + (d["y"] - p["y"])**2)**0.5
            if dist < best:
                best, best_j = dist, j
        if best < threshold and best_j >= 0:
            matched += 1
            used.add(best_j)
    return matched, len(gt) - len(used), len(dets) - matched

print("=== ML Detection (detect_markers_ml) ===\n")
total_tp, total_fp, total_fn = 0, 0, 0

for fi_str in sorted(labels.keys(), key=int):
    fi = int(fi_str)
    video.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, frame = video.read()
    if not ret:
        continue
    crop = frame[MY:MY+MH, MX:MX+MW]
    result = detect_markers_ml(crop, SLIGGY_720, prob_threshold=0.6)

    gt = labels[fi_str]
    gt_ally = [p for p in gt if p["team"] == "ally"]
    gt_enemy = [p for p in gt if p["team"] == "enemy"]

    tp_a, fn_a, fp_a = match_dets(result.ally, gt_ally)
    tp_e, fn_e, fp_e = match_dets(result.enemy, gt_enemy)
    tp, fn, fp = tp_a+tp_e, fn_a+fn_e, fp_a+fp_e
    total_tp += tp; total_fp += fp; total_fn += fn

    status = "OK" if fn <= 2 and fp <= 2 else "MISS"
    print(f"Frame {fi:>5}: {len(result.ally)} ally + {len(result.enemy)} enemy | "
          f"GT {len(gt_ally)} ally + {len(gt_enemy)} enemy | "
          f"TP={tp} FP={fp} FN={fn} [{status}]")

p = total_tp/(total_tp+total_fp) if (total_tp+total_fp) else 0
r = total_tp/(total_tp+total_fn) if (total_tp+total_fn) else 0
f1 = 2*p*r/(p+r) if (p+r) else 0
print(f"\nTOTALS: P={p:.3f} R={r:.3f} F1={f1:.3f}")
print(f"  Matched: {total_tp}/{total_tp+total_fp} detections, {total_fn} missed ground truth")

video.release()
