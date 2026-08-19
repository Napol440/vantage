"""Train a side classifier (ally vs enemy) on positive patches."""
import os, glob
import cv2
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score
import pickle, json

PATCH_SIZE = 24
labels = json.loads(open("twitch_data/twitch_labels.json").read())
video = cv2.VideoCapture("twitch_data/breeze_full.mp4")
MX, MY, MW, MH = 23, 29, 256, 242

# Build labeled side patches from the video
X_side, y_side = [], []

for fi_str, points in labels.items():
    fi = int(fi_str)
    video.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, frame = video.read()
    if not ret:
        continue
    crop = frame[MY:MY+MH, MX:MX+MW]
    for p in points:
        x, y = int(p['x']), int(p['y'])
        x1, y1 = max(0, x-12), max(0, y-12)
        x2, y2 = min(MW, x+12), min(MH, y+12)
        patch = crop[y1:y2, x1:x2]
        if patch.shape[0] < PATCH_SIZE or patch.shape[1] < PATCH_SIZE:
            patch = cv2.resize(patch, (PATCH_SIZE, PATCH_SIZE))
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[:,:,0], hsv[:,:,1], hsv[:,:,2]
        ch, cs, cv_ = h[12,12]/179.0, s[12,12]/255.0, v[12,12]/255.0
        ring_mask = np.zeros((PATCH_SIZE, PATCH_SIZE), dtype=bool)
        for dy in range(-8, 9):
            for dx in range(-8, 9):
                if 3 <= (dx**2+dy**2)**0.5 <= 8:
                    ring_mask[12+dy, 12+dx] = True
        rh, rs, rv = np.mean(h[ring_mask])/179.0, np.mean(s[ring_mask])/255.0, np.mean(v[ring_mask])/255.0
        mh, ms, mv = np.mean(h)/179.0, np.mean(s)/255.0, np.mean(v)/255.0
        sh, ss, sv = np.std(h)/179.0, np.std(s)/255.0, np.std(v)/255.0
        features = [ch, cs, cv_, rh, rs, rv, mh, ms, mv, sh, ss, sv]
        X_side.append(features)
        y_side.append(0 if p['team'] == 'ally' else 1)

video.release()
X_side = np.array(X_side, dtype=np.float32)
y_side = np.array(y_side)

print(f"Side classifier: {len(X_side)} patches ({sum(y_side==0)} ally, {sum(y_side==1)} enemy)")

clf_side = RandomForestClassifier(n_estimators=200, max_depth=10, min_samples_leaf=3, random_state=42)
scores = cross_val_score(clf_side, X_side, y_side, cv=5, scoring='f1')
print(f"Cross-val F1: {scores.mean():.3f} (+/- {scores.std():.3f})")

clf_side.fit(X_side, y_side)
with open("ml_data/side_classifier.pkl", "wb") as f:
    pickle.dump(clf_side, f)
print("Saved ml_data/side_classifier.pkl")
