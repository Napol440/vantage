"""Discover completed match ids by event, team, or date range."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import List, Optional, Tuple

from .fetcher import VLRFetcher
from .parser import clean, soup

log = logging.getLogger(__name__)

_MATCH_LINK_RE = re.compile(r"^/(\d+)/([^/]+)/?$")

_Day = date


def scrape_event_match_ids(
    fetcher: VLRFetcher,
    event_id: int,
    slug: Optional[str] = None,
) -> List[Tuple[int, str]]:
    """Completed match ids for an event (Matches tab, group=completed)."""
    url = fetcher.event_matches_url(event_id, slug) + "/?series_id=all&group=completed"
    html = fetcher.get_html(url)
    return _match_ids_from_listing(html)


def scrape_team_match_ids(
    fetcher: VLRFetcher,
    team_id: int,
    slug: Optional[str] = None,
) -> List[Tuple[int, str]]:
    """Recent matches listed on a team page (results + schedule)."""
    url = fetcher.team_url(team_id, slug)
    html = fetcher.get_html(url)
    s = soup(html)
    out: List[Tuple[int, str]] = []
    for a in s.select("a[href]"):
        href = a.get("href") or ""
        m = _MATCH_LINK_RE.match(href)
        if not m:
            continue
        # Only match items, not news posts.
        if "match-item" not in (a.get("class") or []) and "m-item" not in (a.get("class") or []):
            continue
        out.append((int(m.group(1)), m.group(2)))
    return _dedupe(out)


def scrape_results_by_date(
    fetcher: VLRFetcher,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    max_pages: int = 50,
) -> List[Tuple[int, str]]:
    """Walk the Results tab (/matches/results) page by page, filtering by date.

    Each results page groups matches under a day header; parsing stops when
    every day on a page is earlier than ``date_from``.
    """
    out: List[Tuple[int, str]] = []
    for page in range(1, max_pages + 1):
        html = fetcher.get_html(f"{fetcher.base}/matches/results/", params={"page": page})
        ids, days = _match_ids_with_days(html)
        out.extend(ids)
        if date_from is not None and days and max(days) < date_from:
            log.info("Stopping results pagination at page %s (all earlier than %s).", page, date_from)
            break
        if not ids:
            break
    return _dedupe(out)


def _match_ids_from_listing(html: str) -> List[Tuple[int, str]]:
    s = soup(html)
    out: List[Tuple[int, str]] = []
    for a in s.select("a.wf-module-item.match-item"):
        href = a.get("href") or ""
        m = _MATCH_LINK_RE.match(href)
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return _dedupe(out)


def _match_ids_with_days(html: str) -> Tuple[List[Tuple[int, str]], List[date]]:
    s = soup(html)
    out: List[Tuple[int, str]] = []
    days: List[date] = []
    current_day: Optional[date] = None
    for el in s.find_all(("div", "a")):
        cls = el.get("class") or []
        if "wf-label" in cls and "mod-large" in cls:
            d = _parse_day_label(el.get_text(" ", strip=True))
            if d:
                current_day = d
                days.append(d)
            continue
        if "match-item" in cls and el.name == "a":
            href = el.get("href") or ""
            m = _MATCH_LINK_RE.match(href)
            if m:
                out.append((int(m.group(1)), m.group(2)))
    return out, days


def _parse_day_label(text: str) -> Optional[date]:
    text = clean(text)
    for fmt in ("%a, %B %d, %Y", "%A, %B %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _dedupe(items: List[Tuple[int, str]]) -> List[Tuple[int, str]]:
    seen: set = set()
    out = []
    for mid, slug in items:
        if mid in seen:
            continue
        seen.add(mid)
        out.append((mid, slug))
    return out
