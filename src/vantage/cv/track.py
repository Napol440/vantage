"""Player tracking across frames (Component 3, M5).

Associates detected marker blobs into persistent player identities using
the Hungarian algorithm for optimal assignment. Each track maintains a
history of positions and is marked as lost when unmatched for too many
frames.

Algorithm:
    1. Each frame produces up to 10 detections (5 ally, 5 enemy).
    2. Build a cost matrix: Euclidean distance between existing tracks
       and new detections, filtered by team.
    3. Run Hungarian assignment to find optimal matching.
    4. Unmatched detections create new tracks.
    5. Tracks unmatched for >MAX_LOST_FRAMES are marked inactive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


MAX_LOST_FRAMES = 10  # mark track inactive after this many unmatched frames
MAX_DIST_PX = 150.0   # maximum assignment distance (pixels)


@dataclass
class Track:
    """A single player's trajectory across frames."""
    track_id: int
    team: str                        # "ally" | "enemy"
    history: list[tuple[int, float, float]] = field(default_factory=list)
    # history entries: (frame_index, x_px, y_px)
    last_seen: int = 0               # frame_index of last detection
    active: bool = True

    @property
    def last_pos(self) -> tuple[float, float]:
        """Most recent (x, y) position."""
        _, x, y = self.history[-1]
        return x, y

    def add(self, frame_index: int, x: float, y: float) -> None:
        self.history.append((frame_index, x, y))
        self.last_seen = frame_index


class Tracker:
    """Multi-object tracker using Hungarian assignment.

    Usage::

        tracker = Tracker()
        for frame in stream:
            det = detect_markers(frame)
            tracks = tracker.update(frame.index, det.ally, det.enemy)
            for t in tracks:
                print(t.track_id, t.team, t.last_pos)
    """

    def __init__(self) -> None:
        self._tracks: list[Track] = []
        self._next_id: int = 1

    def update(self, frame_index: int,
               ally_dots: list[dict],
               enemy_dots: list[dict]) -> list[Track]:
        """Run one tracking step. Returns all active tracks."""
        from scipy.optimize import linear_sum_assignment

        # Process each team independently
        for team, dots in [("ally", ally_dots), ("enemy", enemy_dots)]:
            self._assign_team(frame_index, team, dots, linear_sum_assignment)

        # Age and prune tracks
        for t in self._tracks:
            if t.active and (frame_index - t.last_seen) > MAX_LOST_FRAMES:
                t.active = False

        return [t for t in self._tracks if t.active]

    def _assign_team(self, frame_index: int, team: str,
                     dots: list[dict], solve) -> None:
        """Assign detections to existing tracks of the same team."""
        # Existing active tracks for this team
        existing = [t for t in self._tracks if t.active and t.team == team]

        if not existing:
            # No tracks yet — create one per detection
            for d in dots:
                t = Track(track_id=self._next_id, team=team)
                self._next_id += 1
                t.add(frame_index, d["x"], d["y"])
                self._tracks.append(t)
            return

        if not dots:
            return

        # Build cost matrix: existing tracks (rows) x detections (cols)
        n_tracks = len(existing)
        n_dets = len(dots)
        cost = np.full((n_tracks, n_dets), fill_value=MAX_DIST_PX + 1)

        for i, t in enumerate(existing):
            tx, ty = t.last_pos
            for j, d in enumerate(dots):
                dx = tx - d["x"]
                dy = ty - d["y"]
                dist = (dx * dx + dy * dy) ** 0.5
                cost[i, j] = dist

        # Solve Hungarian assignment
        row_ind, col_ind = solve(cost)

        # Apply assignments where cost is reasonable
        matched_rows = set()
        matched_cols = set()
        for r, c in zip(row_ind, col_ind):
            if cost[r, c] <= MAX_DIST_PX:
                existing[r].add(frame_index, dots[c]["x"], dots[c]["y"])
                matched_rows.add(r)
                matched_cols.add(c)

        # Create new tracks for unmatched detections
        for j, d in enumerate(dots):
            if j not in matched_cols:
                t = Track(track_id=self._next_id, team=team)
                self._next_id += 1
                t.add(frame_index, d["x"], d["y"])
                self._tracks.append(t)

    @property
    def all_tracks(self) -> list[Track]:
        return list(self._tracks)

    @property
    def active_tracks(self) -> list[Track]:
        return [t for t in self._tracks if t.active]
