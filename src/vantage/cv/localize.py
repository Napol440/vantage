"""Minimap region localisation (Component 3, M2/M3a).

Finds where the minimap sits in a broadcast frame. Two distinct appearances:

* ``corner`` minimap  - the small persistent HUD minimap (usually top-right).
* ``overview``        - the full-screen tactical overview shown at round start,
                        which is larger and therefore a reliable round-boundary
                        event (see cv/rounds.py).

Approach: the minimap/map tile background is a flat, dark, low-saturation
colour (the marker dots and HUD chrome are bright or saturated, so they do
not pollute it). We threshold the "map background" mask, take its largest
connected region and classify by area fraction. This is deterministic and
covered by synthetic fixtures in the test suite. Returns ``None`` when the
stage decides there is no minimap this frame (map vote, halftimes, killfeed
dwelling, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .profiles import Profile


@dataclass
class MinimapRegion:
    kind: str                # "corner" | "overview"
    bbox: tuple[int, int, int, int]  # (x, y, w, h) in frame coords
    area_frac: float         # fraction of frame covered

    @property
    def x(self) -> int:
        return self.bbox[0]

    @property
    def y(self) -> int:
        return self.bbox[1]

    @property
    def w(self) -> int:
        return self.bbox[2]

    @property
    def h(self) -> int:
        return self.bbox[3]

    def crop(self, frame_bgr: np.ndarray) -> np.ndarray:
        x, y, w, h = self.bbox
        return frame_bgr[y : y + h, x : x + w]


# Map tile background: dark (low value) and low saturation. HSV hue is
# irrelevant here. Tune the thresholds independently of marker colours.
_BG_VALUE_MAX = 130
_BG_SAT_MAX = 100
# The round-start tactical overview is a LARGE CENTRED map. The persistent
# corner minimap is smaller and sits at a frame edge. Requiring centredness
# for "overview" keeps the dark-arena backdrop (which spans the edges) from
# ever starting a new round segment.
_OVERVIEW_FRAC_MIN = 0.12  # overview covers >= 12% of the frame
_OVERVIEW_FRAC_MAX = 0.60
_CENTER_BAND = 0.30        # overview centre must lie in the middle 40% band
_MIN_BG_AREA = 2000        # below this, treat as "no minimap visible"
_CORNER_FRAC_MIN = 0.01
_MINIMAP_MIN_W = 150       # minimap must be at least this wide
_MINIMAP_MAX_W = 600       # minimap must be at most this wide
_MINIMAP_MIN_H = 120       # minimap must be at least this tall
_MINIMAP_MAX_H = 500       # minimap must be at most this tall
# Calibration: typical minimap bbox from labeled ground truth (x, y, w, h)
# Used as fallback when detection fails
_CALIBRATION_BBOX = (38, 58, 387, 342)


def localize_minimap(frame_bgr: np.ndarray,
                     profile: Profile,
                     use_calibration: bool = True) -> Optional[MinimapRegion]:
    """Return the minimap region in ``frame_bgr``, or None if uncertain."""
    import cv2

    # Try dark-tile detection first
    region = _detect_by_dark_tiles(frame_bgr, profile)
    if region:
        return region

    # Fallback: marker-based detection
    region = _detect_by_markers(frame_bgr, profile)
    if region:
        return region

    # Final fallback: use calibration bbox
    if use_calibration:
        fh, fw = frame_bgr.shape[:2]
        x, y, w, h = _CALIBRATION_BBOX
        area_frac = (w * h) / (fh * fw)
        return MinimapRegion(kind="corner", bbox=(x, y, w, h), area_frac=area_frac)

    return None


def _detect_by_dark_tiles(frame_bgr: np.ndarray,
                          profile: Profile) -> Optional[MinimapRegion]:
    """Detect minimap by finding dark, low-saturation regions."""
    import cv2

    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    bg = (hsv[..., 1] <= _BG_SAT_MAX) & (hsv[..., 2] <= _BG_VALUE_MAX)
    bg_u8 = bg.astype(np.uint8)

    num, labels, stats, _ = cv2.connectedComponentsWithStats(bg_u8, connectivity=8)
    if num <= 1:
        return None

    frame_area = frame_bgr.shape[0] * frame_bgr.shape[1]
    # Largest background component is the map tile (other dark UI blocks are
    # usually smaller or non-contiguous).
    largest = max(range(1, num), key=lambda i: stats[i, 4])
    x, y, w, h, area = stats[largest]
    if area < _MIN_BG_AREA:
        return None

    # Filter by minimap size constraints
    if w < _MINIMAP_MIN_W or w > _MINIMAP_MAX_W:
        return None
    if h < _MINIMAP_MIN_H or h > _MINIMAP_MAX_H:
        return None

    area_frac = (w * h) / frame_area

    # Reject regions that are mostly CONTENT (e.g. a map thumbnail inside the
    # scoreboard that happens to be dark): the map tile is spatially smooth.
    if _tile_smoothness(bg_u8, x, y, w, h) < 0.10:
        return None

    if _OVERVIEW_FRAC_MIN <= area_frac <= _OVERVIEW_FRAC_MAX and _is_centred(x, y, w, h, frame_bgr):
        return MinimapRegion(kind="overview", bbox=(int(x), int(y), int(w), int(h)),
                             area_frac=area_frac)
    if area_frac >= _CORNER_FRAC_MIN:
        return MinimapRegion(kind="corner", bbox=(int(x), int(y), int(w), int(h)),
                             area_frac=area_frac)
    return None


def _detect_by_markers(frame_bgr: np.ndarray,
                       profile: Profile) -> Optional[MinimapRegion]:
    """Detect minimap by finding clusters of player markers (cyan/red dots)."""
    import cv2

    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

    # Find marker-colored pixels (cyan ally, red/pink enemy)
    ally = cv2.inRange(hsv, profile.ally.lower, profile.ally.upper)
    enemy = cv2.inRange(hsv, profile.enemy.lower, profile.enemy.upper)
    markers = cv2.bitwise_or(ally, enemy)

    # Clean up noise
    kernel = np.ones((3, 3), np.uint8)
    markers = cv2.morphologyEx(markers, cv2.MORPH_OPEN, kernel)

    # Find small blobs (marker-sized)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(markers, connectivity=8)
    dots = []
    for i in range(1, num):
        area = stats[i, 4]
        if 2 <= area <= 300:  # marker-sized blobs
            dots.append((stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3], area))

    if not dots:
        return None

    # Find tight clusters using simple greedy approach
    # Sort dots by y-coordinate (top-to-bottom), then find groups within 200px
    dots.sort(key=lambda d: (d[1], d[0]))
    clusters = []
    used = set()

    for i, d1 in enumerate(dots):
        if i in used:
            continue
        cluster = [d1]
        used.add(i)
        for j, d2 in enumerate(dots):
            if j in used:
                continue
            # Check if d2 is within 200px of any dot in cluster
            for c in cluster:
                dx = abs(d2[0] - c[0])
                dy = abs(d2[1] - c[1])
                if dx <= 200 and dy <= 200:
                    cluster.append(d2)
                    used.add(j)
                    break
        if len(cluster) >= 2:  # need at least 2 dots
            clusters.append(cluster)

    if not clusters:
        return None

    # Find the cluster with the most dots
    best_cluster = max(clusters, key=len)

    # Compute bounding box of the cluster
    xs = [d[0] for d in best_cluster]
    ys = [d[1] for d in best_cluster]
    xe = [d[0] + d[2] for d in best_cluster]
    ye = [d[1] + d[3] for d in best_cluster]
    x1, y1, x2, y2 = min(xs), min(ys), max(xe), max(ye)

    # Add padding (20% on each side)
    pad_x = int((x2 - x1) * 0.2)
    pad_y = int((y2 - y1) * 0.2)
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    fw, fh = frame_bgr.shape[1], frame_bgr.shape[0]
    x2 = min(fw, x2 + pad_x)
    y2 = min(fh, y2 + pad_y)

    w, h = x2 - x1, y2 - y1
    frame_area = fh * fw
    area_frac = (w * h) / frame_area

    # Filter by minimap size constraints
    if w < _MINIMAP_MIN_W or w > _MINIMAP_MAX_W:
        return None
    if h < _MINIMAP_MIN_H or h > _MINIMAP_MAX_H:
        return None

    if _OVERVIEW_FRAC_MIN <= area_frac <= _OVERVIEW_FRAC_MAX and _is_centred(x1, y1, w, h, frame_bgr):
        return MinimapRegion(kind="overview", bbox=(x1, y1, w, h), area_frac=area_frac)
    if area_frac >= _CORNER_FRAC_MIN:
        return MinimapRegion(kind="corner", bbox=(x1, y1, w, h), area_frac=area_frac)
    return None
    """True if the region's centre lies in the middle ``_CENTER_BAND`` band
    of both axes (overview tiles are centred; the arena backdrop is not)."""
    fh, fw = frame_bgr.shape[:2]
    cx = (x + w / 2) / fw
    cy = (y + h / 2) / fh
    lo = _CENTER_BAND
    hi = 1 - _CENTER_BAND
    return lo <= cx <= hi and lo <= cy <= hi


def _is_centred(x: int, y: int, w: int, h: int, frame_bgr: np.ndarray) -> bool:
    """True if the region's centre lies in the middle ``_CENTER_BAND`` band
    of both axes (overview tiles are centred; the arena backdrop is not)."""
    fh, fw = frame_bgr.shape[:2]
    cx = (x + w / 2) / fw
    cy = (y + h / 2) / fh
    lo = _CENTER_BAND
    hi = 1 - _CENTER_BAND
    return lo <= cx <= hi and lo <= cy <= hi


def _tile_smoothness(bg_mask: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    """Fraction of the region's pixels that are map-background.

    The minimap tile is mostly background; a busy thumbnail or scoreboard box
    has a low background fraction.
    """
    hh, ww = bg_mask.shape[:2]
    if w <= 0 or h <= 0:
        return 0.0
    y1, y2 = max(0, y), min(y + h, hh)
    x1, x2 = max(0, x), min(x + w, ww)
    sub = bg_mask[y1:y2, x1:x2]
    if sub.size == 0:
        return 0.0
    return float(np.count_nonzero(sub)) / float(sub.size)