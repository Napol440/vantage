"""Train classifier with HSV features (better generalization)."""
import os, glob
import cv2
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score
import pickle

PATCH_SIZE = 24

def load_patches_hsv():
    X, y = [], []
    for path in glob.glob("ml_data/positive/*.png"):
        img = cv2.imread(path)
        if img is None or img.shape[:2] != (PATCH_SIZE, PATCH_SIZE):
            continue
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        # Features: HSV values + center ring mean + rim mean
        h, s, v = hsv[:,:,0], hsv[:,:,1], hsv[:,:,2]
        
        # Center pixel HSV
        center_h, center_s, center_v = h[12,12]/179.0, s[12,12]/255.0, v[12,12]/255.0
        
        # Ring means (3-8 px from center)
        mask_ring = np.zeros((PATCH_SIZE, PATCH_SIZE), dtype=bool)
        for dy in range(-8, 9):
            for dx in range(-8, 9):
                if 3 <= (dx**2+dy**2)**0.5 <= 8:
                    mask_ring[12+dy, 12+dx] = True
        ring_h = np.mean(h[mask_ring]) / 179.0
        ring_s = np.mean(s[mask_ring]) / 255.0
        ring_v = np.mean(v[mask_ring]) / 255.0
        
        # Overall stats
        mean_h, mean_s, mean_v = np.mean(h)/179.0, np.mean(s)/255.0, np.mean(v)/255.0
        std_h, std_s, std_v = np.std(h)/179.0, np.std(s)/255.0, np.std(v)/255.0
        
        features = [center_h, center_s, center_v, ring_h, ring_s, ring_v, mean_h, mean_s, mean_v, std_h, std_s, std_v]
        X.append(features)
        y.append(1)
    
    for path in glob.glob("ml_data/negative/*.png"):
        img = cv2.imread(path)
        if img is None or img.shape[:2] != (PATCH_SIZE, PATCH_SIZE):
            continue
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[:,:,0], hsv[:,:,1], hsv[:,:,2]
        
        center_h, center_s, center_v = h[12,12]/179.0, s[12,12]/255.0, v[12,12]/255.0
        mask_ring = np.zeros((PATCH_SIZE, PATCH_SIZE), dtype=bool)
        for dy in range(-8, 9):
            for dx in range(-8, 9):
                if 3 <= (dx**2+dy**2)**0.5 <= 8:
                    mask_ring[12+dy, 12+dx] = True
        ring_h = np.mean(h[mask_ring]) / 179.0
        ring_s = np.mean(s[mask_ring]) / 255.0
        ring_v = np.mean(v[mask_ring]) / 255.0
        mean_h, mean_s, mean_v = np.mean(h)/179.0, np.mean(s)/255.0, np.mean(v)/255.0
        std_h, std_s, std_v = np.std(h)/179.0, np.std(s)/255.0, np.std(v)/255.0
        
        features = [center_h, center_s, center_v, ring_h, ring_s, ring_v, mean_h, mean_s, mean_v, std_h, std_s, std_v]
        X.append(features)
        y.append(0)
    
    return np.array(X, dtype=np.float32), np.array(y)

X, y = load_patches_hsv()
print(f"Loaded {len(X)} patches ({sum(y==1)} positive, {sum(y==0)} negative)")
print(f"Features: center HSV, ring HSV, mean HSV, std HSV (12 features)")

clf = RandomForestClassifier(n_estimators=200, max_depth=10, min_samples_leaf=3, random_state=42)
scores = cross_val_score(clf, X, y, cv=5, scoring='f1')
print(f"Cross-val F1: {scores.mean():.3f} (+/- {scores.std():.3f})")

clf.fit(X, y)

with open("ml_data/player_classifier_hsv.pkl", "wb") as f:
    pickle.dump(clf, f)
print("Saved ml_data/player_classifier_hsv.pkl")
