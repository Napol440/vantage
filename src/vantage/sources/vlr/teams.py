"""Team roster scraping from a VLR.gg team page."""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from ...models import Player, Team
from .fetcher import VLRFetcher
from .parser import clean, player_id_from_href, soup

log = logging.getLogger(__name__)


def resolve_team(fetcher: VLRFetcher, term: str) -> Tuple[int, Optional[str]]:
    """Resolve a CLI team argument to (team_id, slug).

    Accepts an integer id, ``id/slug``, or a team name/slug looked up through
    the public /rankings page (the /search/auto endpoint is excluded by VLR's
    robots.txt, so we don't use it).
    """
    term = term.strip()
    if term.isdigit():
        return int(term), None
    if "/" in term:
        head, _, tail = term.partition("/")
        if head.isdigit():
            return int(head), tail or None

    slug = term.lower().replace(" ", "-")
    html = fetcher.get_html(f"{fetcher.base}/rankings")
    s = soup(html)
    best: Optional[Tuple[int, str]] = None
    for a in s.select("a[href^='/team/']"):
        href = a.get("href") or ""
        parts = [p for p in href.split("/") if p]
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        tid, tslug = int(parts[1]), parts[2]
        name = clean(a.get_text(" ", strip=True)).lower()
        if tslug == slug or name == term.lower() or term.lower() in name:
            if best is None or tslug == slug:
                best = (tid, tslug)
    if best is not None:
        return best
    raise ValueError(
        f"Could not resolve team '{term}'. Pass the numeric VLR team id "
        f"(from the team page URL, e.g. https://www.vlr.gg/team/474/team-liquid)."
    )


def scrape_team(fetcher: VLRFetcher, team_id: int, slug: Optional[str] = None) -> Team:
    """Team profile (name, region, logo) plus active roster."""
    html = fetcher.get_html(fetcher.team_url(team_id, slug))
    s = soup(html)

    name: Optional[str] = None
    logo: Optional[str] = None
    region: Optional[str] = None

    header = s.select_one(".wf-title")
    if header is None:
        header = s.select_one("h1")
    if header is not None:
        name = clean(header.get_text(" ", strip=True)) or None

    logo_el = s.select_one(".team-logo img") or s.select_one("img.team-logo")
    if logo_el is not None and logo_el.get("src"):
        logo = logo_el["src"]

    region_el = s.select_one(".team-header .ge-text-light") or s.select_one(".team-header-country")
    if region_el is not None:
        region = clean(region_el.get_text(" ", strip=True)) or None

    return Team(team_id=team_id, name=name or f"Team {team_id}",
                region=region, logo_url=logo)


def scrape_roster(fetcher: VLRFetcher, team_id: int, slug: Optional[str] = None) -> List[Player]:
    """Active roster players from the team page."""
    html = fetcher.get_html(fetcher.team_url(team_id, slug))
    s = soup(html)
    players: List[Player] = []
    for item in s.select(".team-roster-item"):
        a = item.select_one("a[href*='/player/']")
        pid = player_id_from_href(a.get("href")) if a else None
        alias_el = item.select_one(".team-roster-item-name-alias")
        real_el = item.select_one(".team-roster-item-name-real")
        players.append(
            Player(
                player_id=pid,
                name=clean(real_el.get_text(" ", strip=True)) if real_el else (
                    clean(alias_el.get_text(" ", strip=True)) if alias_el else f"Player {pid}"),
                handle=clean(alias_el.get_text(" ", strip=True)) if alias_el else None,
                real_name=clean(real_el.get_text(" ", strip=True)) if real_el else None,
            )
        )
    return players
