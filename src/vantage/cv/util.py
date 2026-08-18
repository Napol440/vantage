"""Shared small helpers for the CV pipeline (pure numpy/opencv, no I/O)."""

from __future__ import annotations

import numpy as np


def hsv_in_range(hsv: np.ndarray, lo: tuple[int, int, int],
                 hi: tuple[int, int, int]) -> np.ndarray:
    """Boolean mask of pixels whose HSV falls inside [lo, hi], supporting
    ranges that wrap around the hue circle (lo_h > hi_h, e.g. red 170-8)."""
    lo = np.asarray(lo, dtype=np.uint8)
    hi = np.asarray(hi, dtype=np.uint8)
    if lo[0] <= hi[0]:
        return cv_in_range(hsv, lo, hi)
    # Wrapped hue: mask = (h >= lo_h or h <= hi_h) and s,v within.
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    hue_ok = (h >= lo[0]) | (h <= hi[0])
    a = cv_in_range(hsv, np.array([0, lo[1], lo[2]]),
                    np.array([180, hi[1], hi[2]]))
    b = cv_in_range(hsv, np.array([lo[0], lo[1], lo[2]]),
                    np.array([180, hi[1], hi[2]]))
    c = cv_in_range(hsv, np.array([0, lo[1], lo[2]]),
                    np.array([hi[0], hi[1], hi[2]]))
    return (a | b | c) & hue_ok


def cv_in_range(hsv: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    import cv2

    lo = np.asarray(lo, dtype=np.uint8)
    hi = np.asarray(hi, dtype=np.uint8)
    return cv2.inRange(hsv, lo, hi) > 0


def connected_blobs(mask: np.ndarray, min_area: int,
                    max_area: int, circularity: float = 0.0) -> list[dict]:
    """Return centroid+box+area for connected components in a mask.

    ``circularity`` (0..1) filters blobs by how circle-like their perimeter
    is; pass ``0`` to skip the check.
    """
    import cv2

    num, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    out: list[dict] = []
    for i in range(1, num):
        area = int(stats[i, 4])
        if not (min_area <= area <= max_area):
            continue
        x, y, w, h = stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]
        if circularity > 0:
            perimeter = cv2.arcLength(
                np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
                         dtype=np.float32),
                True,
            ) or 1.0
            circ = 4 * np.pi * area / (perimeter * perimeter)
            if circ < circularity:
                continue
        out.append({
            "area": area,
            "x": float(centroids[i][0]),
            "y": float(centroids[i][1]),
            "box": (int(x), int(y), int(w), int(h)),
        })
    return out