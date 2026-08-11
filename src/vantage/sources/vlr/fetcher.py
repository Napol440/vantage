"""HTTP fetching for VLR.gg: URL builders + page retrieval."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

from ...config import Config
from ...http import RateLimitedSession

log = logging.getLogger(__name__)


class VLRFetcher:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.http = RateLimitedSession(cfg.http)
        self.base = cfg.http.base_url.rstrip("/")

    # -- URL builders -------------------------------------------------------

    def match_url(self, match_id: int, slug: Optional[str] = None) -> str:
        path = f"/{match_id}" + (f"/{slug}" if slug else "")
        return f"{self.base}{path}"

    def match_tab_url(
        self,
        match_id: int,
        slug: str,
        game_id: Optional[int] = None,
        tab: str = "overview",
    ) -> str:
        params = [f"tab={tab}"]
        if game_id:
            params.append(f"game={game_id}")
        return f"{self.base}/{match_id}/{slug}?{'&'.join(params)}"

    def matches_list_url(self, group: str = "completed", page: int = 1) -> str:
        return f"{self.base}/matches/?group={group}&page={page}"

    def event_matches_url(self, event_id: int, slug: Optional[str] = None) -> str:
        base = f"{self.base}/event/matches/{event_id}"
        if slug:
            base += f"/{slug}"
        return base

    def team_url(self, team_id: int, slug: Optional[str] = None) -> str:
        path = f"/team/{team_id}" + (f"/{slug}" if slug else "")
        return f"{self.base}{path}"

    def event_url(self, event_id: int, slug: Optional[str] = None) -> str:
        path = f"/event/{event_id}" + (f"/{slug}" if slug else "")
        return f"{self.base}{path}"

    # -- fetching ------------------------------------------------------------

    def get_html(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        max_bytes: int = 4_000_000,
    ) -> str:
        """Fetch a page and return its HTML. Raises on non-200 after retries."""
        resp: requests.Response = self.http.get(url, params=params)
        if resp.status_code == 404:
            raise VLRPageNotFound(url)
        if resp.status_code >= 400:
            raise VLRRequestError(url, resp.status_code)
        if len(resp.content) > max_bytes:
            log.warning("Page %s is unusually large (%d bytes); truncating.", url, len(resp.content))
        return resp.text

    def close(self) -> None:
        self.http.close()


class VLRPageNotFound(Exception):
    def __init__(self, url: str):
        super().__init__(f"VLR page not found: {url}")
        self.url = url


class VLRRequestError(Exception):
    def __init__(self, url: str, status_code: int):
        super().__init__(f"VLR request failed ({status_code}): {url}")
        self.url = url
        self.status_code = status_code
