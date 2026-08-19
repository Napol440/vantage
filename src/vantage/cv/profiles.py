"""Broadcast minimap profiles (Component 3, M2/M3a).

A *profile* captures everything that is constant for one broadcast
production (e.g. the official Riot VCT broadcast) but varies across
productions: the minimap placement/size, marker colours for allies and
enemies, and the round-timer HUD region.

Profiles are pure data — no I/O, no cv logic. Detection stages read these
constants and never hardcode colours or geometry.

Colour ranges are HSV. The convention across the codebase is:
    * ``ally``  - the observing team's marker colour (cyan on VCT).
    * ``enemy`` - the opposing team's marker colour (red/pink on VCT).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class HsvRange:
    lower: tuple[int, int, int]
    upper: tuple[int, int, int]


@dataclass(frozen=True)
class MinMax:
    lo: int
    hi: int


@dataclass(frozen=True)
class DotParams:
    """Marker size/shape filters applied after HSV thresholding."""
    min_area: int = 10          # minimum blob area (px) to count as a dot
    max_area: int = 300         # maximum blob area (px) before it's an overlay
    circularity: float = 0.4    # min perimeter-circularity of a valid dot
    merge_dist_px: float = 8.0  # two blobs closer than this merge into one


@dataclass(frozen=True)
class MinimapGeometry:
    """Expected minimap placement for the production.

    ``bbox`` may be left as ``None`` when placement is unknown; localize
    then scans candidate regions. ``overview_bbox`` is the full-screen
    tactical overview shown at round start (fallback to whole frame).
    """

    bbox: Optional[tuple[int, int, int, int]] = None       # (x, y, w, h)
    overview_bbox: Optional[tuple[int, int, int, int]] = None


@dataclass(frozen=True)
class TimerRegion:
    """HUD round-timer region for OCR (see cv/clock.py)."""
    bbox: Optional[tuple[int, int, int, int]] = None
    digits: int = 2


@dataclass(frozen=True)
class Profile:
    name: str
    ally: HsvRange
    enemy: HsvRange
    dot: DotParams = field(default_factory=DotParams)
    minimap: MinimapGeometry = field(default_factory=MinimapGeometry)
    timer: TimerRegion = field(default_factory=TimerRegion)

    def marker_ranges(self) -> dict[str, HsvRange]:
        return {"ally": self.ally, "enemy": self.enemy}


# ---------------------------------------------------------------------------
# Official Riot VCT broadcast. Colours match the in-broadcast minimap HUD:
# observing team = cyan, opposing team = red/pink. Placement is captured per
# broadcast and stored in the calibrations table; we leave bbox unset here so
# localize discovers it (robust to later placement changes).
# ---------------------------------------------------------------------------
VCT_OFFICIAL = Profile(
    name="vct_official",
    ally=HsvRange(lower=(78, 70, 70), upper=(105, 255, 255)),
    enemy=HsvRange(lower=(170, 80, 60), upper=(8, 255, 255)),  # wraps 0/180
    dot=DotParams(min_area=10, max_area=300, circularity=0.4, merge_dist_px=8.0),
    minimap=MinimapGeometry(bbox=None, overview_bbox=None),
    timer=TimerRegion(bbox=None, digits=2),
)

SLIGGY_720 = Profile(
    name="sliggy_720",
    ally=HsvRange(lower=(75, 80, 110), upper=(105, 140, 230)),
    enemy=HsvRange(lower=(165, 40, 120), upper=(180, 170, 200)),
    dot=DotParams(min_area=5, max_area=80, circularity=0.3, merge_dist_px=8.0),
    minimap=MinimapGeometry(bbox=(23, 29, 256, 242)),
    timer=TimerRegion(bbox=None, digits=2),
)

PROFILES: dict[str, Profile] = {
    VCT_OFFICIAL.name: VCT_OFFICIAL,
    SLIGGY_720.name: SLIGGY_720,
}


def get_profile(name: str | None) -> Profile:
    return PROFILES.get(name or "vct_official", VCT_OFFICIAL)
