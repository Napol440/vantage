"""VLR.gg match page parsing with VOD harvesting (Component 3, M1).

The ``.match-vods`` container on a VLR match page holds one anchor per map::

    <div class="match-vods">
      <div class="wf-label">VODs</div>
      <div class="match-streams-container">
        <a href="https://youtu.be/<id>?t=13027" ...>Map 1</a>
        <a href="https://youtu.be/<id>?t=16807" ...>Map 2</a>
        ...
      </div>
    </div>

Each link's text (``Map N``) maps to the VLR map number (1-based, in the
order the maps were played) and the URL carries the absolute ``?t=`` offset
from the stream start.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..models import parse_youtube_url


def _fetch(url: str) -> str:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


@dataclass
class MatchPage:
    match_id: int
    vods: list  # list[Vod], imported lazily to avoid a cycle
    team_a: str = ""
    team_b: str = ""
    event: str = ""
    map_names: Optional[list[str]] = None


# Lazy import of Vod to avoid a circular import at module load time.
def _make_vod(match_id: int, map_number: int, url: str, label: str):
    from ..models import Vod

    video_id, start_s = parse_youtube_url(url)
    return Vod(
        match_id=match_id,
        map_number=map_number,
        url=url,
        label=label,
        video_id=video_id,
        start_s=start_s,
    )


def parse_match_page(html: str, match_id: int) -> MatchPage:
    """Extract the VOD links and map order from a VLR match page."""
    vods: list = []

    container = _extract_balanced_div(html, 'class="match-vods"')
    if container:
        for a in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]+?)\s*</a>', container):
            href, label = a.group(1), a.group(2).strip()
            match = re.search(r"Map\s*(\d+)", label, re.IGNORECASE)
            if match and not href.startswith("javascript"):
                map_number = int(match.group(1))
                vods.append(_make_vod(match_id, map_number, href, label))

    vods.sort(key=lambda v: v.map_number)

    team_a, team_b, event, map_names = _parse_meta(html)
    return MatchPage(
        match_id=match_id,
        vods=vods,
        team_a=team_a,
        team_b=team_b,
        event=event,
        map_names=map_names,
    )


def _extract_balanced_div(html: str, needle: str) -> Optional[str]:
    """Return the raw inner HTML of the div containing ``needle``.

    Scans forward from the needle with a running div-depth counter so nested
    elements (including self-closing divs) are handled correctly without a
    full HTML parser.
    """
    start = html.find(needle)
    if start == -1:
        return None
    # Rewind to the opening `<div ` tag that owns the needle.
    open_idx = html.rfind("<div", 0, start)
    if open_idx == -1:
        return None

    depth = 0
    pos = open_idx
    end = len(html)
    while pos < end:
        lt = html.find("<", pos)
        if lt == -1:
            break
        gt = html.find(">", lt)
        if gt == -1:
            break
        tag = html[lt : gt + 1]
        is_close = tag.startswith("</") and re.match(r"</\s*div", tag, re.IGNORECASE)
        is_open = re.match(r"<div\b", tag, re.IGNORECASE) and not tag.endswith("/>")
        if is_close:
            depth -= 1
            if depth <= 0:
                return html[open_idx:gt]
        elif is_open:
            depth += 1
        pos = gt + 1
    return None


def _parse_meta(html: str) -> tuple[str, str, str, list[str]]:
    """Parse team names, event name and map list (map_names is best-effort)."""
    team_a = team_b = event = ""
    maps: list[str] = []

    # Team names: <div class="wp-title module-title teams">
    names = re.findall(r'<div class="[^"]*wf-title[^"]*">\s*(.{2,40}?)\s*</div>', html)
    if len(names) >= 2:
        team_a, team_b = names[0].strip(), names[1].strip()

    # VLR map names come from the map-score / veto sections; try the active
    # map roster in the match summary first, else fall back to the stats table.
    # We accept any known map slug to keep parsing tolerant of VLR layout drift.
    known_maps = _KNOWN_MAPS
    for cap in re.finditer(r'"mapName"\s*:\s*"([^"]+)"', html):
        if cap.group(1).lower() in known_maps and cap.group(1) not in maps:
            maps.append(cap.group(1))

    # Best effort event name from the breadcrumb/nav.
    m = re.search(r'<a[^>]*class="[^"]*match-header-event[^"]*"[^>]*>\s*(.+?)\s*</a>', html)
    if m:
        event = re.sub(r"<[^>]+>", "", m.group(1)).strip()

    return team_a, team_b, event, maps


_KNOWN_MAPS = {
    "ascent", "bind", "breeze", "fracture", "haven", "icebox", "lotus",
    "pearl", "split", "sunset", "abyss",
}


def fetch_match_page(match_id: int) -> MatchPage:
    """Download and parse a VLR match page in one call."""
    url = f"https://www.vlr.gg/{match_id}"
    html = _fetch(url)
    return parse_match_page(html, match_id)


def save_vods_to_storage(storage, match_info, match_id: int) -> int:
    """Persist harvested VOD rows. Returns the row count written."""
    return storage.save_vods(match_info.vods)