"""Unified data models for the pipeline.

All models are plain dataclasses with a ``to_dict()`` method so records from
different sources (VLR.gg, and later Rib.gg) serialize into the same shape and
join cleanly on match id / team name / player name.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class WinCondition(str, Enum):
    ELIMINATION = "elimination"
    SPIKE_DETONATION = "spike_detonation"
    SPIKE_DEFUSAL = "spike_defusal"
    TIME_EXPIRY = "time_expiry"
    UNKNOWN = "unknown"


class Side(str, Enum):
    ATTACK = "attack"
    DEFENSE = "defense"
    UNKNOWN = "unknown"


class BuyType(str, Enum):
    ECO = "eco"
    SEMI_ECO = "semi_eco"
    SEMI_BUY = "semi_buy"
    FULL_BUY = "full_buy"
    PISTOL = "pistol"
    UNKNOWN = "unknown"


class VetoAction(str, Enum):
    BAN = "ban"
    PICK = "pick"
    REMAINS = "remains"


def _to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return [_to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


@dataclass
class Team:
    """A team as referenced by a match (id from the source site)."""

    team_id: Optional[int]
    name: str
    region: Optional[str] = None
    logo_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict(self)


@dataclass
class Player:
    """A player profile. ``handle`` is the in-game name / VLR alias."""

    player_id: Optional[int]
    name: str
    handle: Optional[str] = None
    real_name: Optional[str] = None
    country: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict(self)


@dataclass
class VetoEntry:
    """One action in a map veto/pick-ban sequence."""

    action: VetoAction
    team_name: Optional[str]
    map_name: str

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict(self)


@dataclass
class TeamEconomy:
    """Buy info for one team in one round."""

    team_id: Optional[int]
    team_name: str
    buy_type: Optional[BuyType]
    bank_after_buy: Optional[float]
    credits: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict(self)


@dataclass
class Round:
    """Per-round detail for a map.

    Combines the win outcome (winner, side, win condition) with each team's
    economy for that round. ``economies`` holds one ``TeamEconomy`` per team.
    """

    round_number: int
    win_condition: Optional[WinCondition] = None
    winning_side: Optional[Side] = None
    winning_team_id: Optional[int] = None
    winning_team_name: Optional[str] = None
    economies: List[TeamEconomy] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict(self)


@dataclass
class PlayerMatchStats:
    """A player's stats for a single map, merged from Overview + Performance tabs."""

    player_id: Optional[int]
    player_name: str
    team_id: Optional[int]
    team_name: Optional[str] = None
    team_tag: Optional[str] = None  # short tag (e.g. "KC"), used to match Performance tab
    agent: Optional[str] = None
    rating: Optional[float] = None
    acs: Optional[int] = None
    kills: Optional[int] = None
    deaths: Optional[int] = None
    assists: Optional[int] = None
    kast: Optional[float] = None
    adr: Optional[float] = None
    headshot_pct: Optional[float] = None
    first_kills: Optional[int] = None
    first_deaths: Optional[int] = None
    # Performance-tab data (may be absent on lower-tier events).
    operator_kills: Optional[int] = None
    multikills: Dict[str, int] = field(default_factory=dict)  # {"2k": n, ...}
    clutches_won: Dict[str, int] = field(default_factory=dict)  # {"1v1": n, ...}
    clutch_rounds: List[int] = field(default_factory=list)  # best-effort
    plants: Optional[int] = None
    defuses: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict(self)


@dataclass
class MapResult:
    """A single map within a match."""

    map_id: Optional[int]
    map_number: int
    map_name: str
    team1_id: Optional[int]
    team2_id: Optional[int]
    team1_score: int
    team2_score: int
    team1_first_half_score: Optional[int] = None
    team1_second_half_score: Optional[int] = None
    team2_first_half_score: Optional[int] = None
    team2_second_half_score: Optional[int] = None
    winner_team_id: Optional[int] = None
    duration_seconds: Optional[int] = None
    picked_by_team_id: Optional[int] = None  # from the PICK label
    rounds: List[Round] = field(default_factory=list)
    players: List[PlayerMatchStats] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict(self)


@dataclass
class Match:
    """A completed match/series between two teams."""

    match_id: int
    event_id: Optional[int] = None
    event_name: Optional[str] = None
    stage: Optional[str] = None
    date: Optional[datetime] = None
    best_of: Optional[int] = None
    team1_id: Optional[int] = None
    team1_name: Optional[str] = None
    team2_id: Optional[int] = None
    team2_name: Optional[str] = None
    team1_score: Optional[int] = None
    team2_score: Optional[int] = None
    winner_team_id: Optional[int] = None
    veto: List[VetoEntry] = field(default_factory=list)
    veto_text: Optional[str] = None
    maps: List[MapResult] = field(default_factory=list)
    teams: List[Team] = field(default_factory=list)  # rosters if fetched
    url: Optional[str] = None
    source: str = "vlr"
    vlr_id: Optional[int] = None  # VLR match id (rib series carry this cross-ref)

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict(self)


@dataclass
class EventInfo:
    """An event/tournament with bracket and standings summaries."""

    event_id: int
    name: str
    region: Optional[str] = None
    tier: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    prize_pool: Optional[str] = None
    standings: List[Dict[str, Any]] = field(default_factory=list)
    brackets: List[Dict[str, Any]] = field(default_factory=list)
    url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict(self)


def side_from_vlr(cls: str) -> Side:
    """Map VLR css modifiers (mod-t / mod-ct) to a Side."""
    if cls == "mod-t":
        return Side.ATTACK
    if cls == "mod-ct":
        return Side.DEFENSE
    return Side.UNKNOWN


# =============================================================================
# CV pipeline models (Component 3)
# =============================================================================

CV_SOURCE = "cv"


@dataclass
class Vod:
    """One map segment of a match VOD, harvested from a VLR match page."""

    match_id: int
    map_number: int
    url: str
    label: str = ""
    video_id: str = ""
    start_s: int = 0
    duration_s: int = 0

    def __post_init__(self) -> None:
        if not self.video_id or not self.start_s:
            vid, t = parse_youtube_url(self.url)
            self.video_id = self.video_id or vid
            self.start_s = self.start_s or t


def parse_youtube_url(url: str) -> tuple[str, int]:
    """Extract ``(video_id, start_s)`` from a youtu.be/YouTube watch URL."""
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    if "youtu.be" in parsed.netloc:
        vid = parsed.path.strip("/")
    else:
        q = parse_qs(parsed.query)
        vid = q.get("v", [""])[0]
    start = 0
    if parsed.query:
        q = parse_qs(parsed.query)
        if "t" in q:
            t = q["t"][0]
            try:
                start = int(t) if t.isdigit() else _parse_hms(t)
            except ValueError:
                start = 0
    return vid, start


def _parse_hms(s: str) -> int:
    parts = s.split(":")
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


@dataclass
class PlayerState:
    """A detected player marker on the minimap at a tick."""

    match_id: int
    map_number: int
    round_number: int
    ms_into_round: int
    frame_index: int
    x_px: float
    y_px: float
    team: str = "ally"
    side: str = ""
    visible: bool = True
    agent: Optional[str] = None
    track_id: Optional[int] = None
    world_x: Optional[float] = None
    world_y: Optional[float] = None


@dataclass
class UtilityState:
    """A whitelisted utility icon detected on the minimap."""

    match_id: int
    map_number: int
    round_number: int
    ms_into_round: int
    frame_index: int
    kind: str
    x_px: float
    y_px: float
    world_x: Optional[float] = None
    world_y: Optional[float] = None


@dataclass
class SpikeState:
    """Spike marker detection on the minimap."""

    match_id: int
    map_number: int
    round_number: int
    ms_into_round: int
    frame_index: int
    present: bool
    x_px: Optional[float] = None
    y_px: Optional[float] = None
    world_x: Optional[float] = None
    world_y: Optional[float] = None


@dataclass
class Tick:
    """A single frame's worth of detections, ready to persist."""

    match_id: int
    map_number: int
    round_number: int
    ms_into_round: int
    frame_index: int
    pts_s: float
    players: list[PlayerState] = field(default_factory=list)
    utilities: list[UtilityState] = field(default_factory=list)
    spike: Optional[SpikeState] = None
