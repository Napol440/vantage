"""Display-space to world-space geolocation (Component 3, M4).

Two-step transform, both stored per (map, production) in ``calibrations``:

1. Display -> canonical minimap (affine) via the minimap bbox corners.
2. Canonical minimap -> world (projective homography) fitted from >=4
   hand-labelled anchors whose world coordinates are known.

``geolocate_regions`` converts detected marker pixel positions in a
``MinimapRegion`` into world coordinates using the calibration for the map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .localize import MinimapRegion
from .profiles import Profile


@dataclass
class Calibration:
    map_name: str
    production: str
    source: str                     # "manual" | "auto"
    anchors_display: list[tuple[float, float]]       # px in overview space
    anchors_world: list[tuple[float, float]]         # world units
    homography: Optional[np.ndarray] = field(default=None, repr=False)

    def fit(self) -> "Calibration":
        if len(self.anchors_display) < 4:
            raise ValueError("geolocation requires >= 4 anchor pairs")
        src = np.asarray(self.anchors_display, dtype=np.float32)
        dst = np.asarray(self.anchors_world, dtype=np.float32)
        self.homography, _ = cv2_find_homography(src, dst)
        return self


def cv2_find_homography(src: np.ndarray, dst: np.ndarray):
    import cv2

    H, _ = cv2.findHomography(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    return H, True


def calibrate_from_anchors(map_name: str, production: str,
                           anchors_display: list,
                           anchors_world: list) -> Calibration:
    cal = Calibration(map_name=map_name, production=production, source="manual",
                      anchors_display=anchors_display, anchors_world=anchors_world)
    return cal.fit()


def geolocate_point(cal: Calibration, x_px: float, y_px: float) -> tuple[float, float]:
    """Map a display-space point (overview coords) to world coords."""
    if cal.homography is None:
        cal.fit()
    p = np.array([x_px, y_px, 1.0], dtype=np.float64)
    q = cal.homography @ p
    return float(q[0] / q[2]), float(q[1] / q[2])


def geolocate_detection(cal: Calibration, region: MinimapRegion,
                        dot: dict, profile: Profile) -> tuple[float, float] | None:
    """Convert a detector dot (patch-local px) into world coords.

    The patch is cropped from the region bbox, so patch coors need the region
    origin added before the homography (which is fit in overview space).
    """
    wx = region.x + dot["x"]
    wy = region.y + dot["y"]
    return geolocate_point(cal, wx, wy)