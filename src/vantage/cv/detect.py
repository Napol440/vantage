"""Player marker detection on a minimap patch (Component 3, M2/M3b).

Given a cropped minimap image (corner minimap or round-start tactical
overview), this stage thresholds the profile's marker colours in HSV,
filters blobs by size/circularity and returns dot centroids split by side.

Classical first: pure colours + blob filtering is robust on the flat-colour
broadcast minimap. Escalation to a learned detector is only triggered when a
``DetectFailure`` is reported by the validation stage.
"""

from __future__ import annotations

import numpy as np

from .profiles import Profile
from .util import connected_blobs, hsv_in_range


class DetectionResult:
    __slots__ = ("ally", "enemy")

    def __init__(self, ally: list[dict], enemy: list[dict]):
        self.ally = ally  # list of {"x","y","area"}
        self.enemy = enemy


def detect_markers(patch_bgr: np.ndarray, profile: Profile) -> DetectionResult:
    """Detect ally/enemy dots in a minimap patch (BGR image)."""
    import cv2

    hsv = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2HSV)
    ranges = profile.marker_ranges()

    def _side(hue_range, wrapped: bool, max_detections: int = 5):
        mask = hsv_in_range(hsv, hue_range.lower, hue_range.upper)
        blobs = connected_blobs(
            mask, profile.dot.min_area, profile.dot.max_area,
            circularity=profile.dot.circularity,
        )
        # Merge blobs that are closer than merge_dist (marker has an outline).
        merged = _merge(blobs, profile.dot.merge_dist_px)
        # Keep only the largest detections (real players are largest blobs)
        merged.sort(key=lambda b: -b["area"])
        return merged[:max_detections]

    ally = _side(ranges["ally"], False)
    enemy = _side(ranges["enemy"], True)
    return DetectionResult(ally=ally, enemy=enemy)


def _merge(blobs: list[dict], dist: float) -> list[dict]:
    """Greedily merge blob centroids within ``dist`` pixels (weighted by area)."""
    if not blobs:
        return []
    merged: list[dict] = []
    for b in sorted(blobs, key=lambda b: -b["area"]):
        for m in merged:
            if (m["x"] - b["x"]) ** 2 + (m["y"] - b["y"]) ** 2 <= dist * dist:
                m["x"] = (m["x"] * m["area"] + b["x"] * b["area"]) / (m["area"] + b["area"])
                m["y"] = (m["y"] * m["area"] + b["y"] * b["area"]) / (m["area"] + b["area"])
                m["area"] += b["area"]
                break
        else:
            merged.append(dict(b))
    return merged


# ---------------------------------------------------------------------------
# ML-enhanced detection: broad HSV candidates + Random Forest classifier
# ---------------------------------------------------------------------------

_ML_CLF = None
_ML_SIDE_CLF = None
_ML_PATCH = 24
_ML_HALF = _ML_PATCH // 2
_ML_MODEL_PATH = "ml_data/player_classifier_hsv.pkl"
_ML_SIDE_MODEL_PATH = "ml_data/side_classifier.pkl"


def _load_ml_clf():
    global _ML_CLF
    if _ML_CLF is None:
        import pickle, os
        model_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", _ML_MODEL_PATH)
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"ML model not found: {model_path}")
        with open(model_path, "rb") as f:
            _ML_CLF = pickle.load(f)
    return _ML_CLF


def _load_ml_side_clf():
    global _ML_SIDE_CLF
    if _ML_SIDE_CLF is None:
        import pickle, os
        model_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", _ML_SIDE_MODEL_PATH)
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"ML side model not found: {model_path}")
        with open(model_path, "rb") as f:
            _ML_SIDE_CLF = pickle.load(f)
    return _ML_SIDE_CLF


def _hsv_features(img_bgr: np.ndarray) -> np.ndarray:
    """Extract 12-dim HSV feature vector from a 24x24 BGR patch."""
    import cv2
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    ch, cs, cv_ = h[12, 12] / 179.0, s[12, 12] / 255.0, v[12, 12] / 255.0
    # Ring mask (3-8 px from center)
    ring_mask = np.zeros((_ML_PATCH, _ML_PATCH), dtype=bool)
    for dy in range(-8, 9):
        for dx in range(-8, 9):
            if 3 <= (dx ** 2 + dy ** 2) ** 0.5 <= 8:
                ring_mask[12 + dy, 12 + dx] = True
    rh = np.mean(h[ring_mask]) / 179.0
    rs = np.mean(s[ring_mask]) / 255.0
    rv = np.mean(v[ring_mask]) / 255.0
    mh, ms, mv = np.mean(h) / 179.0, np.mean(s) / 255.0, np.mean(v) / 255.0
    sh, ss, sv = np.std(h) / 179.0, np.std(s) / 255.0, np.std(v) / 255.0
    return np.array([ch, cs, cv_, rh, rs, rv, mh, ms, mv, sh, ss, sv], dtype=np.float32)


def detect_markers_ml(patch_bgr: np.ndarray, profile: Profile, prob_threshold: float = 0.5) -> DetectionResult:
    """ML-enhanced player detection: broad HSV + sliding window, filtered by Random Forest.

    Phase 1: Find HSV-colored blob candidates (high precision).
    Phase 2: Slide a window across remaining areas at lower threshold (high recall).
    Both phases feed into the player classifier + side classifier.
    """
    import cv2

    h, w = patch_bgr.shape[:2]
    hsv = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2HSV)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    clf = _load_ml_clf()
    side_clf = _load_ml_side_clf()

    def _broad_blobs(lower, upper):
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for cnt in contours:
            if cv2.contourArea(cnt) < 2:
                continue
            M = cv2.moments(cnt)
            if M["m00"] <= 0:
                continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            candidates.append({"x": float(cx), "y": float(cy), "area": float(cv2.contourArea(cnt))})
        return candidates

    # Phase 1: HSV candidates
    cands_ally = _broad_blobs([60, 10, 30], [120, 255, 255])
    cands_enemy = _broad_blobs([0, 10, 30], [20, 255, 255]) + _broad_blobs([160, 10, 30], [180, 255, 255])

    seen: set[tuple[int, int]] = set()
    ally, enemy = [], []
    all_det_positions: list[tuple[int, int]] = []

    for c in cands_ally + cands_enemy:
        key = (int(c["x"]) // 6, int(c["y"]) // 6)
        if key in seen:
            continue
        seen.add(key)
        cx, cy = int(c["x"]), int(c["y"])
        x1, y1 = max(0, cx - _ML_HALF), max(0, cy - _ML_HALF)
        x2, y2 = min(w, cx + _ML_HALF), min(h, cy + _ML_HALF)
        patch = patch_bgr[y1:y2, x1:x2]
        if patch.shape[0] < _ML_PATCH or patch.shape[1] < _ML_PATCH:
            continue
        features = _hsv_features(patch)
        prob = clf.predict_proba(features.reshape(1, -1))[0][1]
        if prob > prob_threshold:
            side_pred = side_clf.predict(features.reshape(1, -1))[0]
            side = "ally" if side_pred == 0 else "enemy"
            det = {"x": float(cx), "y": float(cy), "area": c["area"], "prob": float(prob)}
            (ally if side == "ally" else enemy).append(det)
            all_det_positions.append((cx, cy))

    return DetectionResult(ally=ally, enemy=enemy)
