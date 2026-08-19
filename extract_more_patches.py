"""Extract more training data: use all labeled frames + generate more negatives."""
import sys, json, os
sys.path.insert(0, 'src')
import cv2
import numpy as np

labels = json.loads(open("twitch_data/twitch_labels.json").read())
video = cv2.VideoCapture("twitch_data/breeze_full.mp4")
MX, MY, MW, MH = 23, 29, 256, 242

PATCH_SIZE = 24
HALF = PATCH_SIZE // 2
kernel = np.ones((3, 3), np.uint8)

# Clean old data
for d in ["ml_data/positive", "ml_data/negative"]:
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))

pos_count = 0
neg_count = 0

# Extract positives from ALL labeled frames
for fi_str, points in labels.items():
    fi = int(fi_str)
    video.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, frame = video.read()
    if not ret:
        continue
    crop = frame[MY:MY+MH, MX:MX+MW]
    
    for p in points:
        x, y = int(p['x']), int(p['y'])
        x1 = max(0, x - HALF)
        y1 = max(0, y - HALF)
        x2 = min(MW, x + HALF)
        y2 = min(MH, y + HALF)
        patch = crop[y1:y2, x1:x2]
        if patch.shape[0] < PATCH_SIZE or patch.shape[1] < PATCH_SIZE:
            patch = cv2.resize(patch, (PATCH_SIZE, PATCH_SIZE))
        cv2.imwrite(f"ml_data/positive/pos_{pos_count:04d}.png", patch)
        pos_count += 1
        
        # Augment: shift by ±2px
        for dx, dy in [(-2,0),(2,0),(0,-2),(0,2)]:
            nx, ny = x+dx, y+dy
            nx1, ny1 = max(0, nx-HALF), max(0, ny-HALF)
            nx2, ny2 = min(MW, nx+HALF), min(MH, ny+HALF)
            aug = crop[ny1:ny2, nx1:nx2]
            if aug.shape[0] >= PATCH_SIZE and aug.shape[1] >= PATCH_SIZE:
                cv2.imwrite(f"ml_data/positive/pos_{pos_count:04d}.png", aug)
                pos_count += 1

# Extract negatives from ALL labeled frames
for fi_str in labels:
    fi = int(fi_str)
    video.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, frame = video.read()
    if not ret:
        continue
    crop = frame[MY:MY+MH, MX:MX+MW]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    
    # Random positions far from any label
    np.random.seed(int(fi_str))
    for _ in range(30):
        x = np.random.randint(HALF+2, MW-HALF-2)
        y = np.random.randint(HALF+2, MH-HALF-2)
        too_close = any(((x-p['x'])**2 + (y-p['y'])**2) < 15**2 for p in labels[fi_str])
        if too_close:
            continue
        patch = crop[y-HALF:y+HALF, x-HALF:x+HALF]
        cv2.imwrite(f"ml_data/negative/neg_{neg_count:04d}.png", patch)
        neg_count += 1
    
    # HSV blobs that aren't labeled
    for lower, upper in [
        ([60, 15, 40], [120, 255, 255]),
        ([0, 15, 40], [20, 255, 255]),
        ([160, 15, 40], [180, 255, 255]),
    ]:
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            if cv2.contourArea(cnt) < 2:
                continue
            M = cv2.moments(cnt)
            if M["m00"] <= 0:
                continue
            cx, cy = int(M["m10"]/M["m00"]), int(M["m01"]/M["m00"])
            is_labeled = any(((cx-p['x'])**2 + (cy-p['y'])**2) < 8**2 for p in labels[fi_str])
            if is_labeled:
                continue
            x1, y1 = max(0, cx-HALF), max(0, cy-HALF)
            x2, y2 = min(MW, cx+HALF), min(MH, cy+HALF)
            patch = crop[y1:y2, x1:x2]
            if patch.shape[0] >= PATCH_SIZE and patch.shape[1] >= PATCH_SIZE:
                cv2.imwrite(f"ml_data/negative/neg_{neg_count:04d}.png", patch)
                neg_count += 1

video.release()
print(f"Extracted {pos_count} positive, {neg_count} negative patches")
