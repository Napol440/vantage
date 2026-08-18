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
