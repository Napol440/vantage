"""Extract training patches from labeled Twitch minimap frames."""
import sys, json, os
sys.path.insert(0, 'src')
import cv2
import numpy as np

labels = json.loads(open("twitch_data/twitch_labels.json").read())
video = cv2.VideoCapture("twitch_data/breeze_full.mp4")
MX, MY, MW, MH = 23, 29, 256, 242

PATCH_SIZE = 24
HALF = PATCH_SIZE // 2

os.makedirs("ml_data/positive", exist_ok=True)
os.makedirs("ml_data/negative", exist_ok=True)

pos_count = 0
neg_count = 0

# Extract positive patches (centered on labeled player positions)
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

print(f"Extracted {pos_count} positive patches")

# Extract negative patches (random non-player areas, HSV blob areas that aren't labeled)
for fi_str in labels:
    fi = int(fi_str)
    video.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, frame = video.read()
    if not ret:
        continue
    crop = frame[MY:MY+MH, MX:MX+MW]
    
    # Method 1: Random positions
    np.random.seed(42)
    for _ in range(20):
        x = np.random.randint(HALF, MW - HALF)
        y = np.random.randint(HALF, MH - HALF)
        # Skip if too close to any label
        too_close = False
        for p in labels[fi_str]:
            if ((x - p['x'])**2 + (y - p['y'])**2) < 20**2:
                too_close = True
                break
        if too_close:
            continue
        patch = crop[y-HALF:y+HALF, x-HALF:x+HALF]
        cv2.imwrite(f"ml_data/negative/neg_{neg_count:04d}.png", patch)
        neg_count += 1
    
    # Method 2: HSV blob positions that aren't labeled (false positives)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # Use broad ranges to find candidate blobs
    mask = cv2.bitwise_or(
        cv2.inRange(hsv, np.array([75, 40, 80]), np.array([105, 255, 255])),
        cv2.inRange(hsv, np.array([160, 30, 80]), np.array([180, 255, 255]))
    )
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 3:
            continue
        M = cv2.moments(cnt)
        if M["m00"] <= 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        
        # Check if this blob overlaps any label (if so, skip - it's a positive)
        is_labeled = False
        for p in labels[fi_str]:
            if ((cx - p['x'])**2 + (cy - p['y'])**2) < 10**2:
                is_labeled = True
                break
        if is_labeled:
            continue
        
        x1 = max(0, cx - HALF)
        y1 = max(0, cy - HALF)
        x2 = min(MW, cx + HALF)
        y2 = min(MH, cy + HALF)
        patch = crop[y1:y2, x1:x2]
        if patch.shape[0] < PATCH_SIZE or patch.shape[1] < PATCH_SIZE:
            continue
        cv2.imwrite(f"ml_data/negative/neg_{neg_count:04d}.png", patch)
        neg_count += 1

video.release()
print(f"Extracted {neg_count} negative patches")
print(f"Total: {pos_count} positive, {neg_count} negative")
