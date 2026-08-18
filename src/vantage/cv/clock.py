"""Round-timer OCR cross-check (Component 3, M2).

The primary round-boundary signal is the tactical overview (cv/rounds.py).
This module reads the HUD round timer (e.g. "1:40") as a secondary
verification: it lets the validation stage detect if overview segmentation
drifted (timer resets should coincide with new rounds) and disambiguates
buy-phase (0:30) from live round (1:40/1:30).

Pure function: ``digits`` returns the visible time as digit strings.
"""
from __future__ import annotations

import numpy as np

from .localize import _crop_ims


def read_timer(frame_bgr: np.ndarray, timer_bbox: tuple[int, int, int, int]) -> str:
    """Return the timer text read from ``timer_bbox`` as e.g. '1:40' or ''.

    Simple classical pipeline: binarise the crop (timer digits are bright on
    dark), segment by connected components along the horizontal axis, and map
    per-blob bounding-box observation counts to digits via the 'seven-segment'
    shape of each blob's filled ratio — this is deliberately lightweight; a
    learned OCR (easyocr) can replace it without changing call sites.
    If nothing legible is found, returns ''.
    """
    import cv2

    x, y, w, h = timer_bbox
    crop = _crop_ims(frame_bgr, x, y, w, h)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Digits are light text on the dark HUD. Brightness threshold.
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if th.mean() > 128:
        th = 255 - th  # ensure foreground (digit) is white

    num, labels, stats, _ = cv2.connectedComponentsWithStats(th.astype(np.uint8))
    rows: list[tuple[int, int, int, int]] = []  # (x, y, w, h)
    for i in range(1, num):
        if stats[i, 4] < 20:
            continue
        rows.append((stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]))
    rows.sort(key=lambda b: b[0])

    text = ""
    for bx, by, bw, bh in rows:
        # Colon is small and thin; treat as separator, skip it.
        if bw * 1.0 / bh < 0.25:
            text += ":"
            continue
        # Classify digits by filled fraction + aspect. Simple lookup table.
        fill = _blob_fill(th, (bx, by, bw, bh))
        d = _classify(bw / bh, fill)
        if d is not None:
            text += d
    return text


def _blob_fill(th: np.ndarray, bbox: tuple[int, int, int, int]) -> float:
    x, y, w, h = bbox
    sub = th[y : y + h, x : x + w]
    return float(np.count_nonzero(sub)) / float(sub.size)


def _classify(aspect: float, fill: float) -> str | None:
    """Crude digit classifier by aspect ratio and filled fraction.

    Accepts the limited digit set present in round timers (0-5, 8, 9 mostly).
    aspect ~ 0.35-0.6 for most digits; '1' is the slimmest.
    """
    if aspect < 0.22:
        return "1"
    if 0.25 <= fill < 0.42:
        return "0" if aspect > 0.5 else "4" if fill < 0.36 else "7"
    if 0.42 <= fill < 0.58:
        return "8" if aspect > 0.5 else "6"
    if fill >= 0.58:
        return "9" if aspect > 0.5 else "3"
    return None