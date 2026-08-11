"""Scrape a completed match: header, veto, per-map rounds, overview, performance,
and economy tabs.

The VLR match page renders all maps' data on one HTML page, so a match needs at
most three requests: the base page (header + veto + round timeline + overview
player stats), the ``tab=economy`` page, and the ``tab=performance`` page.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup, Tag

from ...config import Config
from ...models import (
    BuyType,
    MapResult,
    Match,
    PlayerMatchStats,
    Round,
    Side,
    Team,
    TeamEconomy,
    VetoAction,
    VetoEntry,
    WinCondition,
)
from .fetcher import VLRFetcher
from .parser import (
    agent_name_from_img,
    buy_type_from_symbols,
    clean,
    parse_bank,
    parse_duration_to_seconds,
    parse_utc_ts,
    player_id_from_href,
    side_from_classes,
    soup,
    team_id_from_href,
    to_float,
    to_int,
)

log = logging.getLogger(__name__)

_MAP_LABEL_RE = re.compile(r"\s*(PICK|BAN|DECIDER)\s*$", re.IGNORECASE)


class MatchScraper:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.fetcher = VLRFetcher(cfg)

    def close(self) -> None:
        self.fetcher.close()

    # -- public ---------------------------------------------------------------

    def scrape_match(self, match_id: int, slug: Optional[str] = None) -> Match:
        url = self.fetcher.match_url(match_id, slug)
        html = self.fetcher.get_html(url)
        match = parse_match_page(match_id, html, url)

        if self.cfg.scraper.include_economy:
            try:
                eco_url = self.fetcher.match_tab_url(match_id, _slug_of(match), tab="economy")
                merge_economy(match, self.fetcher.get_html(eco_url))
            except Exception:
                log.warning("Economy data unavailable for match %s; skipping.", match_id, exc_info=True)

        if self.cfg.scraper.include_performance:
            try:
                perf_url = self.fetcher.match_tab_url(match_id, _slug_of(match), tab="performance")
                merge_performance(match, self.fetcher.get_html(perf_url))
            except Exception:
                log.warning("Performance data unavailable for match %s; skipping.", match_id, exc_info=True)

        return match

    # -- team/event listing helpers (thin wrappers to keep API tidy) ---------

    def fetch_html(self, url: str) -> str:
        return self.fetcher.get_html(url)


def _slug_of(match: Match) -> str:
    if match.url:
        m = re.search(r"/\d+/([^/?]+)", match.url)
        if m:
            return m.group(1)
    return ""


# =============================================================================
# Match page parsing
# =============================================================================

def parse_match_page(match_id: int, html: str, url: str = "") -> Match:
    s = soup(html)
    header = s.select_one(".wf-card.match-header")
    match = Match(match_id=match_id, url=url, source="vlr")

    if header is None:
        log.warning("No match header found for match %s; page may be invalid.", match_id)
        return match

    _parse_header(header, match)

    # Team tags (e.g. 'KC'/'TL') are only visible on player rows; resolve the
    # tag -> team mapping from the first overview block (team1's players first).
    tag_map: Dict[str, tuple[int, Optional[str]]] = {}
    tag_order: List[str] = []

    seen_ids: set = set()
    for block in s.select("div.vm-stats-game"):
        game_id = block.get("data-game-id")
        if game_id is None or game_id in (seen_ids | {"all"}):
            continue
        seen_ids.add(game_id)
        if block.select_one(".vm-stats-game-header") is None:
            continue
        mp = _parse_map_block(block, match, tag_map, tag_order)
        if mp is not None:
            match.maps.append(mp)

    if match.veto_text:
        match.veto = parse_veto_text(match.veto_text, match, tag_map)

    _finish_match(match)
    return match


def _parse_header(header: Tag, match: Match) -> None:
    # Event + stage
    event_link = header.select_one("a.match-header-event")
    if event_link:
        href = event_link.get("href") or ""
        em = re.search(r"/event/(\d+)", href)
        if em:
            match.event_id = int(em.group(1))
        full = clean(event_link.get_text(" ", strip=True))
        series_el = event_link.select_one(".match-header-event-series")
        if series_el:
            series = clean(series_el.get_text(" ", strip=True))
            match.stage = series or None
            if series and full.endswith(series):
                full = full[: -len(series)].strip() or full
        match.event_name = full or None

    # Date (UTC)
    ts_el = header.select_one(".match-header-date .moment-tz-convert[data-utc-ts]")
    if ts_el is None:
        ts_el = header.select_one(".match-header-date [data-utc-ts]")
    match.date = parse_utc_ts(ts_el.get("data-utc-ts")) if ts_el else None

    # Teams
    vs = header.select_one(".match-header-vs")
    if vs:
        link1 = vs.select_one("a.mod-1")
        link2 = vs.select_one("a.mod-2")
        match.team1_id = team_id_from_href(link1.get("href")) if link1 else None
        match.team2_id = team_id_from_href(link2.get("href")) if link2 else None
        match.team1_name = clean(link1.get_text(" ", strip=True)) if link1 else None
        match.team2_name = clean(link2.get_text(" ", strip=True)) if link2 else None

    # Best of (the header carries both a 'final'/'qualified' note and 'Bo3')
    for note in header.select(".match-header-vs-note"):
        m = re.search(r"bo(\d+)", clean(note.get_text(" ", strip=True)), re.IGNORECASE)
        if m:
            match.best_of = int(m.group(1))
            break

    # Veto text
    veto_note = header.select_one(".match-header-note")
    if veto_note:
        match.veto_text = clean(veto_note.get_text(" ", strip=True)) or None


def parse_veto_text(text: str, match: Match, tag_map: Dict[str, tuple[int, Optional[str]]]) -> List[VetoEntry]:
    """Parse 'KC ban Breeze; TL pick Lotus; ...; Haven remains'."""
    entries: List[VetoEntry] = []
    for part in text.split(";"):
        part = clean(part)
        if not part:
            continue
        tokens = part.split()
        if not tokens:
            continue
        if tokens[-1].lower() == "remains" or part.lower().endswith("remains"):
            map_name = " ".join(tokens[:-1])
            entries.append(VetoEntry(VetoAction.REMAINS, None, map_name or part))
            continue
        if len(tokens) >= 3 and tokens[1].lower() in ("ban", "pick"):
            tag, action_word, map_name = tokens[0], tokens[1].lower(), " ".join(tokens[2:])
            action = VetoAction.PICK if action_word == "pick" else VetoAction.BAN
            team_id, team_name = tag_map.get(tag, (None, None))
            entries.append(VetoEntry(action, team_name, map_name))
    return entries


def _parse_map_block(
    block: Tag,
    match: Match,
    tag_map: Dict[str, tuple[int, Optional[str]]],
    tag_order: List[str],
) -> Optional[MapResult]:
    game_id_raw = block.get("data-game-id")
    try:
        game_id = int(game_id_raw)
    except (TypeError, ValueError):
        return None

    header = block.select_one(".vm-stats-game-header")
    if header is None:
        return None

    team_els = header.select(":scope > .team")
    if len(team_els) < 2:
        team_els = header.select(".team")
    team1_el = team_els[0]
    team2_el = next((t for t in team_els if "mod-right" in (t.get("class") or [])), team_els[-1])

    team1_name = clean(team1_el.select_one(".team-name").get_text(" ", strip=True)) if team1_el.select_one(".team-name") else None
    team2_name = clean(team2_el.select_one(".team-name").get_text(" ", strip=True)) if team2_el.select_one(".team-name") else None

    score1 = to_int(team1_el.select_one(".score").get_text(strip=True)) if team1_el.select_one(".score") else None
    score2 = to_int(team2_el.select_one(".score").get_text(strip=True)) if team2_el.select_one(".score") else None

    map_el = header.select_one(".map")
    map_name: Optional[str] = None
    picked_by: Optional[int] = None
    duration: Optional[int] = None
    if map_el:
        label_span = map_el.select_one(":scope > div span")
        if label_span is None:
            label_span = map_el.select_one("span")
        if label_span is not None:
            map_name = _MAP_LABEL_RE.sub("", clean(label_span.get_text(" ", strip=True))) or None
        pick_el = map_el.select_one("span.picked")
        if pick_el is not None:
            cls = pick_el.get("class") or []
            if "mod-1" in cls:
                picked_by = match.team1_id
            elif "mod-2" in cls:
                picked_by = match.team2_id
        dur_el = map_el.select_one(".map-duration")
        duration = parse_duration_to_seconds(dur_el.get_text(" ", strip=True)) if dur_el else None

    # Half scores: team1 displayed as "CT / T", team2 as "T / CT".
    half1 = _half_scores(team1_el)
    half2 = _half_scores(team2_el)

    mp = MapResult(
        map_id=game_id,
        map_number=len(match.maps) + 1,
        map_name=map_name or f"Map {game_id}",
        team1_id=match.team1_id,
        team2_id=match.team2_id,
        team1_score=score1 or 0,
        team2_score=score2 or 0,
        team1_first_half_score=half1[0],
        team1_second_half_score=half1[1],
        team2_first_half_score=half2[0],
        team2_second_half_score=half2[1],
        winner_team_id=(match.team1_id if (score1 or 0) > (score2 or 0)
                        else match.team2_id if (score2 or 0) > (score1 or 0) else None),
        duration_seconds=duration,
        picked_by_team_id=picked_by,
    )

    team1_tag = team1_name
    team2_tag = team2_name
    mp.players = _parse_overview(block, match, tag_map, tag_order)
    mp.rounds = _parse_rounds(block, match, mp)
    return mp


def _half_scores(team_el: Tag) -> tuple[Optional[int], Optional[int]]:
    spans = team_el.select(".mod-ct, .mod-t")
    if not spans:
        return None, None
    vals = [to_int(sp.get_text(strip=True)) for sp in spans]
    return (vals[0], vals[1]) if len(vals) >= 2 else (vals[0], None)


def _parse_overview(
    block: Tag,
    match: Match,
    tag_map: Dict[str, tuple[int, Optional[str]]],
    tag_order: List[str],
) -> List[PlayerMatchStats]:
    players: List[PlayerMatchStats] = []

    for row in block.select(".ovw-row"):
        if "mod-head" in (row.get("class") or []):
            continue
        player_el = row.select_one(".ovw-cell.mod-player")
        if player_el is None:
            continue
        a = player_el.select_one("a[href*='/player/']")
        name_el = player_el.select_one(".ovw-player-name")
        if name_el is None:
            continue
        handle = clean(name_el.get_text(" ", strip=True))
        tag_el = player_el.select_one(".ovw-player-tag")
        tag = clean(tag_el.get_text(" ", strip=True)) if tag_el else ""
        agent = agent_name_from_img(player_el.select_one(".ovw-agents img"))

        if tag and tag not in tag_map:
            idx = len(tag_order)
            tag_order.append(tag)
            team_id = match.team1_id if idx == 0 else match.team2_id
            team_name = match.team1_name if idx == 0 else match.team2_name
            tag_map[tag] = (team_id, team_name)

        team_id, team_name = tag_map.get(tag, (None, None))

        ps = PlayerMatchStats(
            player_id=player_id_from_href(a.get("href")) if a else None,
            player_name=handle,
            team_id=team_id,
            team_name=team_name,
            team_tag=tag or None,
            agent=agent,
        )
        _read_ovw_stats(row, ps)
        players.append(ps)
    return players


def _read_ovw_stats(row: Tag, ps: PlayerMatchStats) -> None:
    cells = {c.get("data-col"): c for c in row.select(".ovw-cell[data-col]")}

    def both(attr: str) -> Optional[str]:
        cell = cells.get(attr)
        if cell is None:
            return None
        side = cell.select_one(".side.mod-both")
        return clean(side.get_text(" ", strip=True)) if side else None

    ps.rating = to_float(both("rating2"))
    ps.acs = to_int(both("acs"))
    ps.kast = to_float(both("kast"))
    ps.adr = to_float(both("adr"))
    ps.headshot_pct = to_float(both("hsp"))
    ps.first_kills = to_int(both("fb"))
    ps.first_deaths = to_int(both("fd"))

    kda_el = row.select_one(".ovw-cell.mod-kda")
    if kda_el:
        for stat in kda_el.select(".ovw-kda-stat"):
            col = stat.get("data-col")
            val = to_int(stat.select_one(".side.mod-both").get_text(" ", strip=True)) if stat.select_one(".side.mod-both") else None
            if col == "kills":
                ps.kills = val
            elif col == "deaths":
                ps.deaths = val
            elif col == "assists":
                ps.assists = val


def _parse_rounds(block: Tag, match: Match, mp: MapResult) -> List[Round]:
    rounds_block = block.select_one(".vlr-rounds")
    if rounds_block is None:
        return []
    rounds: List[Round] = []
    for col in rounds_block.select(".vlr-rounds-row-col"):
        rn_el = col.select_one(".rnd-num")
        if rn_el is None:
            continue
        try:
            rn = int(rn_el.get_text(strip=True))
        except ValueError:
            continue
        sqs = col.select(".rnd-sq")
        winner_sq: Optional[Tag] = None
        winner_idx: Optional[int] = None
        for i, sq in enumerate(sqs):
            if "mod-win" in (sq.get("class") or []):
                winner_sq = sq
                winner_idx = i
                break

        rnd = Round(round_number=rn)
        if winner_sq is not None:
            cls = winner_sq.get("class") or []
            rnd.winning_side = side_from_classes(cls)
            rnd.winning_team_id = match.team1_id if winner_idx == 0 else match.team2_id
            rnd.winning_team_name = match.team1_name if winner_idx == 0 else match.team2_name
            img = winner_sq.select_one("img")
            if img:
                src = img.get("src") or ""
                icon = src.rsplit("/", 1)[-1]
                rnd.win_condition = _WIN_ICON_MAP.get(icon, WinCondition.UNKNOWN)
            else:
                rnd.win_condition = WinCondition.UNKNOWN
        rounds.append(rnd)
    return rounds


_WIN_ICON_MAP = {
    "elim.webp": WinCondition.ELIMINATION,
    "defuse.webp": WinCondition.SPIKE_DEFUSAL,
    "boom.webp": WinCondition.SPIKE_DETONATION,
    "time.webp": WinCondition.TIME_EXPIRY,
}


def _finish_match(match: Match) -> None:
    if match.maps:
        match.team1_score = sum(1 for m in match.maps if m.winner_team_id == match.team1_id)
        match.team2_score = sum(1 for m in match.maps if m.winner_team_id == match.team2_id)
        if match.team1_score and match.team2_score:
            match.winner_team_id = match.team1_id if match.team1_score > match.team2_score else match.team2_id


# =============================================================================
# Economy tab
# =============================================================================

def merge_economy(match: Match, html: str) -> None:
    s = soup(html)
    by_game = _game_blocks(s)
    merged_any = False
    for mp in match.maps:
        block = by_game.get(str(mp.map_id))
        if block is None:
            continue
        parsed = _parse_economy_block(block, match, mp)
        if parsed:
            merged_any = True
            for rn, (e1, e2) in parsed.items():
                rnd = _round_by_number(mp, rn)
                if rnd is None:
                    rnd = Round(round_number=rn)
                    mp.rounds.append(rnd)
                rnd.economies = [e1, e2]
    if not merged_any:
        log.info("No economy tables found for match %s (low-tier or missing tab).", match.match_id)


def _parse_economy_block(
    block: Tag, match: Match, mp: MapResult
) -> Dict[int, tuple[TeamEconomy, TeamEconomy]]:
    result: Dict[int, tuple[TeamEconomy, TeamEconomy]] = {}
    tables = block.select("table.mod-econ")
    for table in tables:
        for td in table.select("td"):
            rn_el = td.select_one(".round-num")
            if rn_el is None:
                continue
            try:
                rn = int(rn_el.get_text(strip=True))
            except ValueError:
                continue
            sqs = td.select(".rnd-sq")
            banks = td.select(".bank")
            if len(sqs) < 2:
                continue
            teams = _teams_for_round(match)
            e1 = _team_economy(teams[0], sqs[0], banks[0] if len(banks) > 0 else None, rn)
            e2 = _team_economy(teams[1], sqs[1], banks[1] if len(banks) > 1 else None, rn)
            result[rn] = (e1, e2)
    return result


def _team_economy(team: Team, sq: Tag, bank_el: Optional[Tag], rn: int) -> TeamEconomy:
    symbols = clean(sq.get_text(" ", strip=True))
    buy_type = buy_type_from_symbols(symbols, rn)
    return TeamEconomy(
        team_id=team.team_id,
        team_name=team.name,
        buy_type=buy_type,
        bank_after_buy=parse_bank(bank_el.get_text(" ", strip=True)) if bank_el else None,
        credits=to_int(sq.get("title")),
    )


def _teams_for_round(match: Match) -> tuple[Team, Team]:
    return (
        Team(match.team1_id, match.team1_name or "Team 1"),
        Team(match.team2_id, match.team2_name or "Team 2"),
    )


def _round_by_number(mp: MapResult, rn: int) -> Optional[Round]:
    for rnd in mp.rounds:
        if rnd.round_number == rn:
            return rnd
    return None


# =============================================================================
# Performance tab
# =============================================================================

def merge_performance(match: Match, html: str) -> None:
    s = soup(html)
    by_game = _game_blocks(s)
    merged_any = False
    for mp in match.maps:
        block = by_game.get(str(mp.map_id))
        if block is None:
            continue
        n = _merge_performance_for_map(match, mp, block)
        merged_any = merged_any or n
    if not merged_any:
        log.info("No performance tables found for match %s (low-tier or missing tab).", match.match_id)


def _merge_performance_for_map(match: Match, mp: MapResult, block: Tag) -> int:
    adv = _parse_adv_stats(block)
    op_kills = _parse_op_kills(block)

    by_key: Dict[str, PlayerMatchStats] = {}
    tag_to_team: Dict[str, tuple[Optional[int], Optional[str]]] = {}
    for ps in mp.players:
        key = _player_key(ps.player_name, ps.team_tag or "")
        by_key.setdefault(key, ps)
        if ps.team_tag:
            tag_to_team.setdefault(ps.team_tag, (ps.team_id, ps.team_name))

    for key, vals in adv.items():
        ps = by_key.get(key)
        if ps is None:
            team_id, team_name = tag_to_team.get(vals["tag"], (None, None))
            ps = PlayerMatchStats(
                player_id=None,
                player_name=vals["name"],
                team_id=team_id,
                team_name=team_name,
                team_tag=vals["tag"],
            )
            mp.players.append(ps)
            by_key[key] = ps
        ps.multikills = vals["multikills"]
        ps.clutches_won = vals["clutches"]
        ps.plants = vals.get("plants")
        ps.defuses = vals.get("defuses")
        if vals.get("agent"):
            ps.agent = vals["agent"]

    for key, op in op_kills.items():
        ps = by_key.get(key)
        if ps is None:
            team_id, team_name = tag_to_team.get(op.get("tag", ""), (None, None))
            ps = PlayerMatchStats(
                player_id=None,
                player_name=op["name"],
                team_id=team_id,
                team_name=team_name,
                team_tag=op.get("tag"),
            )
            mp.players.append(ps)
            by_key[key] = ps
        ps.operator_kills = op["kills"]

    return len(adv) or len(op_kills)


def _player_key(name: str, team: str) -> str:
    return f"{name.lower()}:::{team.lower()}"


def _parse_adv_stats(block: Tag) -> Dict[str, Dict]:
    table = block.select_one("table.mod-adv-stats")
    if table is None:
        return {}
    headers: List[str] = []
    header_row = table.select_one("tr")
    if header_row:
        for th in header_row.select("th"):
            headers.append(clean(th.get_text(" ", strip=True)))
    col = {h: i for i, h in enumerate(headers) if h}

    out: Dict[str, Dict] = {}
    for tr in table.select("tr")[1:]:
        tds = tr.select("td")
        if len(tds) < 2:
            continue
        team_el = tds[0].select_one(".team")
        if team_el is None:
            continue
        name = _player_name_from_team(team_el)
        tag = _player_tag_from_team(team_el)
        agent = agent_name_from_img(tds[1].select_one("img"))

        def cell(idx: Optional[int]) -> Optional[int]:
            if idx is None or idx >= len(tds):
                return None
            sq = tds[idx].select_one(".stats-sq")
            return to_int(_direct_text(sq)) if sq is not None else None

        multikills = {
            "2k": cell(col.get("2K")) or 0,
            "3k": cell(col.get("3K")) or 0,
            "4k": cell(col.get("4K")) or 0,
            "5k": cell(col.get("5K")) or 0,
        }
        clutches = {
            "1v1": cell(col.get("1v1")) or 0,
            "1v2": cell(col.get("1v2")) or 0,
            "1v3": cell(col.get("1v3")) or 0,
            "1v4": cell(col.get("1v4")) or 0,
            "1v5": cell(col.get("1v5")) or 0,
        }
        out[_player_key(name, tag)] = {
            "name": name,
            "tag": tag,
            "agent": agent,
            "multikills": multikills,
            "clutches": clutches,
            "plants": cell(col.get("PL")),
            "defuses": cell(col.get("DE")),
        }
    return out


def _parse_op_kills(block: Tag) -> Dict[str, Dict]:
    table = block.select_one("table.mod-matrix.mod-op")
    if table is None:
        return {}
    out: Dict[str, Dict] = {}
    for tr in table.select("tr")[1:]:
        tds = tr.select("td")
        if not tds:
            continue
        team_el = tds[0].select_one(".team")
        if team_el is None:
            continue
        name = _player_name_from_team(team_el)
        tag = _player_tag_from_team(team_el)
        total = 0
        for td in tds[1:]:
            first = td.select_one(".stats-sq")
            if first is not None:
                total += to_int(_direct_text(first)) or 0
        out[_player_key(name, tag)] = {"name": name, "kills": total}
    return out


def _player_name_from_team(team_el: Tag) -> str:
    name_el = team_el.select_one("div")
    if name_el is None:
        return clean(team_el.get_text(" ", strip=True))
    tag = clean(team_el.select_one(".team-tag").get_text(" ", strip=True)) if team_el.select_one(".team-tag") else ""
    name = clean(name_el.get_text(" ", strip=True))
    if tag and name.endswith(tag):
        name = name[: -len(tag)].strip()
    return name


def _direct_text(el: Optional[Tag]) -> str:
    """Return only the direct (non-nested) text of an element.

    VLR stats cells embed their value as a direct text node inside a
    ``.stats-sq`` and stash extra numbers in a nested popover; ``get_text``
    would concatenate both. We want just the visible value.
    """
    if el is None:
        return ""
    parts: List[str] = []
    for child in el.children:
        if isinstance(child, str):
            parts.append(child)
    return " ".join(parts).strip()


def _player_tag_from_team(team_el: Tag) -> str:
    tag_el = team_el.select_one(".team-tag")
    return clean(tag_el.get_text(" ", strip=True)) if tag_el else ""


def _game_blocks(s: BeautifulSoup) -> Dict[str, Tag]:
    out: Dict[str, Tag] = {}
    for block in s.select("div.vm-stats-game"):
        gid = block.get("data-game-id")
        if gid and gid != "all":
            out.setdefault(gid, block)
    return out
