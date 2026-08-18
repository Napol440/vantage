"""Round segmentation from the stream (Component 3, M2).

The round-start tactical overview (a large, fixed minimap showing all ten
players at their spawns) is the canonical round-boundary event. Every time
an overview frame appears we start a new round segment; frames between
overviews belong to the ongoing round. This avoids relying on the fragile
round-timer OCR as the primary boundary signal (see cv/clock.py for the
timer cross-check).

Output contract: for each processed frame produce a ``(round_number,
ms_into_round)`` mapping. round_number is 1-based, incrementing on every
overview event (including the pre-map overview). ms_into_round is the
offset from the frame *right after* the overview that started the round.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RoundState:
    """Running segmentation state; feed it frames, read round info."""
    round_number: int = 0
    ms_into_round: int = 0
    _in_overview: bool = False
    _last_pts_s: Optional[float] = None
    _overview_end_s: Optional[float] = None

    def update(self, pts_s: float, region_kind: Optional[str],
               fps: float = 6.0) -> tuple[int, int]:
        """Advance the state with one frame's minimap region kind.

        Returns ``(round_number, ms_into_round)`` for the frame. ``region_kind``
        is ``"overview"``, ``"corner"`` or ``None`` (no minimap this frame).
        """
        # A new overview (round start) begins a fresh round.
        if region_kind == "overview" and not self._in_overview:
            self.round_number += 1
            # The overview occupies the first ~1s of the new round; the timer
            # starts when gameplay resumes, so anchor ms at the first frame
            # AFTER the overview (handled below).
            self._overview_end_s = None
            self._in_overview = True

        # Fallback: if no overview seen yet but we have a minimap, start round 1
        if self.round_number == 0 and region_kind in ("corner", "overview"):
            self.round_number = 1
            self._overview_end_s = pts_s

        if region_kind == "overview":
            # Still the start-of-round tactical map.
            ms = 0
        else:
            if self._in_overview:
                self._overview_end_s = pts_s
                self._in_overview = False
            if self.round_number == 0:
                # Before the very first overview we cannot assign a round yet.
                ms = 0
            else:
                base = self._overview_end_s if self._overview_end_s is not None else pts_s
                ms = int(round((pts_s - base) * 1000))

        self._last_pts_s = pts_s
        return self.round_number, max(0, ms)


@dataclass
class RoundSegment:
    """One round's worth of ticks (frame subset of the stream)."""
    round_number: int
    first_pts_s: float
    last_pts_s: float
    frame_count: int
    start_pts_s: float = 0.0  # exact overview->play resumption point


def segment_stream(regions: list[tuple[float, Optional[str]]],
                   fps: float = 6.0) -> list[RoundSegment]:
    """Turn a list of ``(pts_s, region_kind)`` into round segments (pure)."""
    state = RoundState()
    segs: list[RoundSegment] = []
    cur: Optional[RoundSegment] = None
    for pts_s, kind in regions:
        rnum, _ = state.update(pts_s, kind, fps)
        if cur is None or cur.round_number != rnum:
            cur = RoundSegment(round_number=rnum, first_pts_s=pts_s,
                               last_pts_s=pts_s, frame_count=1)
            segs.append(cur)
        else:
            cur.frame_count += 1
            cur.last_pts_s = pts_s
    return segs