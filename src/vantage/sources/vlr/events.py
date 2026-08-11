"""Event info: group standings and playoff brackets."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from ...models import EventInfo
from .fetcher import VLRFetcher
from .parser import clean, soup, team_id_from_href, to_int

log = logging.getLogger(__name__)


def scrape_event(
    fetcher: VLRFetcher,
    event_id: int,
    slug: Optional[str] = None,
    include_brackets: bool = True,
) -> EventInfo:
    """Event metadata + group standings from the event home page, plus any
    stage brackets reachable from it."""
    html = fetcher.get_html(fetcher.event_url(event_id, slug))
    s = soup(html)

    title = s.select_one("h1.event-header-main-title")
    meta = s.select_one(".event-header-main-meta")

    ev = EventInfo(
        event_id=event_id,
        name=clean(title.get_text(" ", strip=True)) if title else f"Event {event_id}",
        url=fetcher.event_url(event_id, slug),
    )
    if meta is not None:
        meta_text = clean(meta.get_text(" ", strip=True))
        _parse_meta(meta_text, ev)

    ev.standings = _parse_standings(s)

    if include_brackets:
        ev.brackets = _parse_brackets(s)
        for stage_link in _stage_links(s):
            try:
                stage_html = fetcher.get_html(f"{fetcher.base}{stage_link}")
                ev.brackets.extend(_parse_brackets(soup(stage_html)))
            except Exception:
                log.warning("Could not fetch bracket page %s.", stage_link, exc_info=True)

    return ev


def _parse_meta(text: str, ev: EventInfo) -> None:
    import re
    from datetime import datetime

    def grab(key: str) -> Optional[str]:
        m = re.search(rf"{key}:?\s*([^·,|]+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    ev.prize_pool = grab("prize pool")
    ev.tier = grab("tier")

    for key, attr in (("start date", "start_date"), ("end date", "end_date")):
        raw = grab(key)
        if not raw:
            continue
        for fmt in ("%B %d, %Y", "%Y-%m-%d", "%B %Y"):
            try:
                setattr(ev, attr, datetime.strptime(raw, fmt).date())
                break
            except (ValueError, TypeError):
                continue


def _parse_standings(s) -> List[Dict[str, Any]]:
    """Parse group standings rows into dicts keyed by team."""
    rows: List[Dict[str, Any]] = []
    seen_teams: set = set()
    for group_el in s.select(".event-group"):
        group_name_el = group_el.select_one(".event-group-title, .wf-label")
        group_name = clean(group_name_el.get_text(" ", strip=True)) if group_name_el else None

        table = group_el.select_one("table")
        if table is None:
            continue
        for tr in table.select("tr"):
            team_link = tr.select_one("a.event-group-team")
            if team_link is None:
                continue
            team_id = team_id_from_href(team_link.get("href"))
            if team_id in seen_teams:
                continue
            seen_teams.add(team_id)
            name = clean(team_link.select_one(".event-group-team-name").get_text(" ", strip=True))
            region = clean(team_link.select_one(".event-group-team-region").get_text(" ", strip=True)) or None
            cells = [clean(td.get_text(" ", strip=True)) for td in tr.select("td")]
            rows.append({
                "group": group_name,
                "team_id": team_id,
                "team_name": name,
                "region": region,
                "record": _cell(cells, 1),
                "round_w_l": _cell(cells, 2),
                "round_diff": _cell(cells, 3),
            })
    return rows


def _cell(cells: List[str], idx: int) -> Optional[str]:
    return cells[idx] if idx < len(cells) else None


def _parse_brackets(s) -> List[Dict[str, Any]]:
    """Compact bracket representation: one entry per match."""
    matches: List[Dict[str, Any]] = []
    for col in s.select(".bracket-col"):
        round_name_el = col.select_one(".bracket-col-label")
        round_name = clean(round_name_el.get_text(" ", strip=True)) if round_name_el else None
        for item in col.select(".bracket-item"):
            teams = []
            for team_el in item.select(".bracket-item-team"):
                name_el = team_el.select_one(".bracket-item-team-name")
                name = clean(name_el.get_text(" ", strip=True)) if name_el else None
                tid = team_el.get("data-team-id")
                score_el = team_el.select_one(".bracket-item-team-score")
                score = to_int(score_el.get_text(" ", strip=True)) if score_el else None
                is_winner = "mod-winner" in (team_el.get("class") or [])
                teams.append({
                    "team_id": int(tid) if str(tid).isdigit() else None,
                    "team_name": name,
                    "score": score,
                    "winner": is_winner,
                })
            if teams:
                matches.append({"round": round_name, "teams": teams})
    return matches


def _stage_links(s) -> List[str]:
    out: List[str] = []
    for a in s.select("a[href*='/event/']"):
        href = a.get("href") or ""
        # stage links look like /event/{id}/{slug}/{stage}
        parts = [p for p in href.split("/") if p]
        if len(parts) >= 4 and parts[0] == "event":
            if href not in out:
                out.append(href)
    return out
