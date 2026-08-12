"""Map rib.gg JSON into the pipeline's unified models.

Field names follow the shapes observed by ``tonyelhabr/valorantr`` (snake_case
top level, e.g. ``start_date``), but every access goes through ``_d()`` so both
``start_date`` and ``startDate`` are accepted. Anything that is missing or
unexpected is simply skipped - this source is best-effort.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ...models import (
    BuyType,
    EventInfo,
    MapResult,
    Match,
    PlayerMatchStats,
    Round,
    Team,
    TeamEconomy,
    VetoAction,
    VetoEntry,
    WinCondition,
)

log = logging.getLogger(__name__)

# id -> name lookups (community-documented; used when the API only returns ids).
MAP_NAMES = {
    1: "Ascent", 2: "Split", 3: "Bind", 4: "Icebox", 5: "Ascent",
    6: "Haven", 7: "Haven", 8: "Breeze", 9: "Fracture", 10: "Pearl",
    11: "Lotus", 12: "Sunset", 13: "Abyss", 14: "Corrode", 16: "Summit",
}
AGENT_NAMES = {
    1: "breach", 2: "raze", 3: "cypher", 4: "sova", 5: "killjoy",
    6: "viper", 7: "phoenix", 8: "brimstone", 9: "sage", 10: "reyna",
    11: "omen", 12: "jett", 13: "skye", 14: "yoru", 15: "astra",
    16: "kayo", 17: "chamber", 18: "neon", 19: "fade",
}
WEAPON_NAMES = {
    2: "odin", 3: "ares", 4: "vandal", 5: "bulldog", 6: "phantom",
    8: "judge", 9: "bucky", 10: "frenzy", 11: "classic", 12: "ghost",
    13: "sheriff", 14: "shorty", 15: "operator", 16: "guardian",
    17: "marshal", 18: "spectre", 19: "stinger",
}
REGION_NAMES = {
    1: "Europe", 2: "North America", 3: "Asia-Pacific", 4: "Latin America",
    5: "MENA", 6: "Oceana", 7: "International",
}


def _d(obj: Optional[Dict[str, Any]], *keys: str) -> Any:
    """First non-None value among several possible keys on a dict."""
    if not isinstance(obj, dict):
        return None
    for key in keys:
        val = obj.get(key)
        if val is not None:
            return val
    return None


def _int(obj: Optional[Dict[str, Any]], *keys: str) -> Optional[int]:
    val = _d(obj, *keys)
    if val is None or isinstance(val, bool):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _str(obj: Optional[Dict[str, Any]], *keys: str) -> Optional[str]:
    val = _d(obj, *keys)
    if val is None:
        return None
    text = str(val).strip()
    return text or None


def _dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    text = str(val).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def buy_type_from_credits(team_credits: Optional[int], round_number: int) -> BuyType:
    """Map a team's summed credits to a BuyType, mirroring VLR's thresholds."""
    if team_credits is None:
        return BuyType.UNKNOWN
    if round_number == 1:
        return BuyType.PISTOL
    if team_credits < 5000:
        return BuyType.ECO
    if team_credits < 10000:
        return BuyType.SEMI_ECO
    if team_credits < 20000:
        return BuyType.SEMI_BUY
    return BuyType.FULL_BUY


# =============================================================================
# Series -> Match
# =============================================================================

def series_to_match(data: Dict[str, Any]) -> Match:
    """Convert a ``series/{id}`` payload into a unified ``Match``."""
    team1 = _d(data, "team1") or {}
    team2 = _d(data, "team2") or {}

    match = Match(
        match_id=_int(data, "id") or 0,
        event_id=_int(data, "event_id", "eventId", "event_id"),
        event_name=_str(data, "event_name", "eventName"),
        stage=_str(data, "stage"),
        date=_dt(_d(data, "start_date", "startDate")),
        best_of=_int(data, "best_of", "bestOf"),
        team1_id=_int(team1, "id") or _int(data, "team1id", "team1Id"),
        team1_name=_str(team1, "name") or _str(data, "team1Name", "team1_name"),
        team2_id=_int(team2, "id") or _int(data, "team2id", "team2Id"),
        team2_name=_str(team2, "name") or _str(data, "team2Name", "team2_name"),
        team1_score=_int(data, "team1_score", "team1Score", "score1"),
        team2_score=_int(data, "team2_score", "team2Score", "score2"),
        vlr_id=_int(data, "vlr_id", "vlrId"),
        url=_str(data, "url"),
        source="rib",
    )

    for t in (team1, team2):
        tid = _int(t, "id")
        if tid is not None:
            match.teams.append(
                Team(
                    team_id=tid,
                    name=_str(t, "name") or "",
                    region=_str(t, "region", "regionName"),
                    logo_url=_str(t, "logo", "logoUrl"),
                )
            )

    if match.team1_score is not None and match.team2_score is not None:
        if match.team1_score != match.team2_score:
            match.winner_team_id = (
                match.team1_id if match.team1_score > match.team2_score else match.team2_id
            )

    for i, mdata in enumerate(_d(data, "matches") or [], start=1):
        mp = _match_to_map_result(mdata, match, i)
        match.maps.append(mp)

    # The series-level score is sometimes absent; derive it from map winners.
    if match.team1_score is None and match.maps:
        wins1 = sum(1 for m in match.maps if m.winner_team_id == match.team1_id)
        wins2 = sum(1 for m in match.maps if m.winner_team_id == match.team2_id)
        match.team1_score, match.team2_score = wins1, wins2
        if wins1 > wins2:
            match.winner_team_id = match.team1_id
        elif wins2 > wins1:
            match.winner_team_id = match.team2_id

    # Map-level player stats may live on the series payload keyed by match id.
    for mp in match.maps:
        if mp.players:
            continue
        for row in _d(data, "player_stats") or []:
            if _int(row, "match_id", "matchId") == mp.map_id:
                mp.players.append(player_stats_row_to_model(row))

    return match


def _match_to_map_result(mdata: Dict[str, Any], match: Match, map_number: int) -> MapResult:
    map_id = _int(mdata, "id", "match_id", "matchId")
    map_name = (
        _str(mdata, "map_name", "mapName")
        or MAP_NAMES.get(_int(mdata, "map_id", "mapId") or -1, "Map %d" % map_number)
    )
    mp = MapResult(
        map_id=map_id,
        map_number=map_number,
        map_name=map_name or f"Map {map_number}",
        team1_id=_int(mdata, "team1_id", "team1Id") or match.team1_id,
        team2_id=_int(mdata, "team2_id", "team2Id") or match.team2_id,
        team1_score=_int(mdata, "team1_score", "team1Score", "score1") or 0,
        team2_score=_int(mdata, "team2_score", "team2Score", "score2") or 0,
        winner_team_id=_int(mdata, "winner_id", "winnerId", "winner_team_id", "winning_team_id"),
        duration_seconds=_int(mdata, "duration", "duration_seconds", "durationSeconds"),
    )
    if mp.winner_team_id is None and mp.team1_score != mp.team2_score:
        mp.winner_team_id = mp.team1_id if mp.team1_score > mp.team2_score else mp.team2_id

    for row in _d(mdata, "player_stats", "players") or []:
        if isinstance(row, dict) and _d(row, "player_id", "playerId", "id") is not None:
            mp.players.append(player_stats_row_to_model(row))
    return mp


def player_stats_row_to_model(row: Dict[str, Any]) -> PlayerMatchStats:
    """Convert one rib player-stats row (per map) into a PlayerMatchStats."""
    name = _str(row, "player_name", "playerName", "name", "handle") or ""
    mk = {
        "2k": _int(row, "2k", "2K") or 0,
        "3k": _int(row, "3k", "3K") or 0,
        "4k": _int(row, "4k", "4K") or 0,
        "5k": _int(row, "5k", "5K") or 0,
    }
    clutch = {
        "1v1": _int(row, "1v1") or 0,
        "1v2": _int(row, "1v2") or 0,
        "1v3": _int(row, "1v3") or 0,
        "1v4": _int(row, "1v4") or 0,
        "1v5": _int(row, "1v5") or 0,
    }
    agent_id = _int(row, "agent_id", "agentId")
    return PlayerMatchStats(
        player_id=_int(row, "player_id", "playerId", "id"),
        player_name=name,
        team_id=_int(row, "team_id", "teamId"),
        team_name=_str(row, "team_name", "teamName"),
        agent=AGENT_NAMES.get(agent_id) if agent_id else _str(row, "agent_name", "agentName"),
        rating=_float(row, "rating", "rating2"),
        acs=_int(row, "acs", "ACS"),
        kills=_int(row, "kills", "Kills"),
        deaths=_int(row, "deaths", "Deaths"),
        assists=_int(row, "assists", "Assists"),
        kast=_float(row, "kast", "KAST"),
        adr=_float(row, "adr", "ADR"),
        headshot_pct=_float(row, "hs", "hsp", "headshot_pct", "headshotPercentage"),
        first_kills=_int(row, "fk", "fb", "first_kills", "firstKills"),
        first_deaths=_int(row, "fd", "first_deaths", "firstDeaths"),
        operator_kills=_int(row, "operator_kills", "operatorKills", "op_kills"),
        multikills={k: v for k, v in mk.items() if v},
        clutches_won={k: v for k, v in clutch.items() if v},
        plants=_int(row, "plants", "plant"),
        defuses=_int(row, "defuses", "defuse"),
    )


def _float(obj: Optional[Dict[str, Any]], *keys: str) -> Optional[float]:
    val = _d(obj, *keys)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# =============================================================================
# Match details -> rounds
# =============================================================================

def merge_match_details(match: Match, details: Dict[str, Any]) -> int:
    """Merge ``matches/{id}/details`` (economies/events) into the match's maps.

    Rib reports economy at player granularity, so per-team ``TeamEconomy`` rows
    are approximated: ``credits`` = summed player credits, ``bank_after_buy`` =
    summed loadout cost, ``buy_type`` derived from summed credits.
    """
    team_names = {t.team_id: t.name for t in match.teams if t.team_id is not None}
    if match.team1_id is not None and match.team1_name:
        team_names[match.team1_id] = match.team1_name
    if match.team2_id is not None and match.team2_name:
        team_names[match.team2_id] = match.team2_name

    merged = 0
    for mp in match.maps:
        if mp.map_id is None:
            continue
        detail = _details_for_map(details, mp.map_id)
        if detail is None:
            continue
        rounds = _rounds_from_economies(detail, mp, team_names)
        if rounds:
            mp.rounds = rounds
            merged += 1
    return merged


def _details_for_map(details: Dict[str, Any], map_id: int) -> Optional[Dict[str, Any]]:
    data = _d(details, "data") or details
    if _int(data, "id", "match_id", "matchId") == map_id:
        return data
    for entry in _d(data, "maps") or []:
        if _int(entry, "id", "match_id", "matchId") == map_id:
            return entry
    return None


def _rounds_from_economies(
    detail: Dict[str, Any], mp: MapResult, team_names: Dict[int, str]
) -> List[Round]:
    players = _d(detail, "economies") or []

    # Shape A: economies = [{player_id, team_id, economy_data: [{round, cost, credits}]}]
    per_round: Dict[int, Dict[int, Dict[str, int]]] = {}  # round -> team_id -> {"cost", "credits"}
    for prow in players:
        if not isinstance(prow, dict):
            continue
        team_id = _int(prow, "team_id", "teamId")
        if team_id is None:
            continue
        eco_rows = _d(prow, "economy_data", "economyData", "data") or []
        for erow in eco_rows:
            if not isinstance(erow, dict):
                continue
            rn = _int(erow, "round", "round_number", "roundNum")
            if rn is None:
                continue
            bucket = per_round.setdefault(rn, {})
            t = bucket.setdefault(team_id, {"cost": 0, "credits": 0})
            t["cost"] += _int(erow, "cost", "total_cost", "totalCost") or 0
            t["credits"] += _int(erow, "credits", "cred") or 0

    out: List[Round] = []
    for rn in sorted(per_round):
        teams = per_round[rn]
        e1 = _team_economy_for_round(mp.team1_id, team_names, teams, rn)
        e2 = _team_economy_for_round(mp.team2_id, team_names, teams, rn)
        out.append(Round(round_number=rn, economies=[e for e in (e1, e2) if e is not None]))
    return out


def _team_economy_for_round(
    team_id: Optional[int],
    team_names: Dict[int, str],
    teams: Dict[int, Dict[str, int]],
    rn: int,
) -> Optional[TeamEconomy]:
    if team_id is None:
        return None
    bucket = teams.get(team_id)
    if bucket is None:
        return None
    return TeamEconomy(
        team_id=team_id,
        team_name=team_names.get(team_id, "Team %d" % team_id),
        buy_type=buy_type_from_credits(bucket["credits"], rn),
        bank_after_buy=float(bucket["cost"]) if bucket["cost"] else None,
        credits=bucket["credits"] or None,
    )


# =============================================================================
# Events / teams / players -> models
# =============================================================================

def event_summary_to_event_info(data: Dict[str, Any]) -> EventInfo:
    return EventInfo(
        event_id=_int(data, "id") or 0,
        name=_str(data, "name") or "",
        region=_str(data, "region", "regionName"),
        tier=_str(data, "tier", "level"),
        start_date=_dt(_d(data, "start_date", "startDate")),
        end_date=_dt(_d(data, "end_date", "endDate")),
        prize_pool=_str(data, "prize_pool", "prizePool"),
        url=_str(data, "url", "slug"),
    )


def team_to_model(data: Dict[str, Any]) -> Optional[Team]:
    tid = _int(data, "id", "team_id", "teamId")
    if tid is None:
        return None
    return Team(
        team_id=tid,
        name=_str(data, "name") or "",
        region=_str(data, "region", "regionName"),
        logo_url=_str(data, "logo", "logoUrl"),
    )


__all__ = [
    "MAP_NAMES", "AGENT_NAMES", "WEAPON_NAMES", "REGION_NAMES",
    "buy_type_from_credits", "series_to_match", "merge_match_details",
    "player_stats_row_to_model", "event_summary_to_event_info", "team_to_model",
]
