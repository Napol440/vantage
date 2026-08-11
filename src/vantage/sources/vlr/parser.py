"""Low-level parsing helpers for VLR.gg HTML."""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from bs4 import BeautifulSoup, Tag

from ...models import BuyType, Side, WinCondition

_TEAM_ID_RE = re.compile(r"/team/(\d+)")
_PLAYER_ID_RE = re.compile(r"/player/(\d+)")

# VLR win-condition icons (img filenames inside the round square).
WIN_CONDITION_BY_ICON = {
    "elim.webp": WinCondition.ELIMINATION,
    "defuse.webp": WinCondition.SPIKE_DEFUSAL,
    "boom.webp": WinCondition.SPIKE_DETONATION,
    "time.webp": WinCondition.TIME_EXPIRY,
}

_MAP_ID_RE = re.compile(r"/event/matches/(\d+)")


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def clean(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def to_int(value: Optional[str]) -> Optional[int]:
    text = clean(value)
    if not text or text in ("-", "–", "—", ""):
        return None
    text = text.replace(",", "")
    sign = -1 if text.startswith("-") else 1
    digits = re.sub(r"[^0-9]", "", text)
    if not digits:
        return None
    return sign * int(digits)


def to_float(value: Optional[str]) -> Optional[float]:
    text = clean(value)
    if not text or text in ("-", "–", "—"):
        return None
    text = text.rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


def parse_duration_to_seconds(value: Optional[str]) -> Optional[int]:
    """'1:00:40' -> 3640, '12:03' -> 723, '0:59' -> 59."""
    text = clean(value)
    if not text:
        return None
    parts = [int(p) for p in text.split(":") if p.isdigit()]
    if not parts:
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def parse_bank(value: Optional[str]) -> Optional[float]:
    """'0.3k' -> 300.0, '7500' -> 7500.0, '' -> None."""
    text = clean(value)
    if not text:
        return None
    text = text.lower()
    try:
        if text.endswith("k"):
            return float(text[:-1]) * 1000.0
        return float(text)
    except ValueError:
        return None


def parse_utc_ts(value: Optional[str]) -> Optional[datetime]:
    """'2026-08-01 14:10:00' -> naive datetime (UTC as given by VLR)."""
    text = clean(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def buy_type_from_symbols(symbols: str, round_number: int) -> BuyType:
    """Map the '$'/'$$'/'$$$' buy indicator (and pistol rounds) to a BuyType."""
    if round_number == 1 and not symbols:
        return BuyType.PISTOL
    if not symbols:
        return BuyType.ECO
    if symbols == "$":
        return BuyType.SEMI_ECO
    if symbols == "$$":
        return BuyType.SEMI_BUY
    return BuyType.FULL_BUY


def side_from_classes(cls: List[str]) -> Side:
    if "mod-t" in cls:
        return Side.ATTACK
    if "mod-ct" in cls:
        return Side.DEFENSE
    return Side.UNKNOWN


def team_id_from_href(href: Optional[str]) -> Optional[int]:
    if not href:
        return None
    m = _TEAM_ID_RE.search(href)
    return int(m.group(1)) if m else None


def player_id_from_href(href: Optional[str]) -> Optional[int]:
    if not href:
        return None
    m = _PLAYER_ID_RE.search(href)
    return int(m.group(1)) if m else None


def agent_name_from_img(img: Optional[Tag]) -> Optional[str]:
    if img is None:
        return None
    return clean(img.get("alt")) or None


def first_text(tag: Tag, selector: str) -> str:
    node = tag.select_one(selector)
    return clean(node.get_text(" ")) if node else ""


def parse_player_tag(el: Optional[Tag]) -> str:
    """Extract the 2-3 letter team tag from a '.team-tag' node."""
    if el is None:
        return ""
    return clean(el.get_text(" "))
