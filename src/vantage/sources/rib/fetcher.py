"""JSON HTTP fetching for rib.gg: URL builder + envelope parsing.

rib.gg responses are JSON. List endpoints return ``{"meta": {...}, "data": [...]}``
(``meta.total`` = total result count); detail endpoints return ``{"data": {...}}``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

from ...config import Config, HttpConfig
from ...http import RateLimitedSession

log = logging.getLogger(__name__)


class RibFetcher:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base = cfg.rib.base_url.rstrip("/")
        # Rib runs its own throttle (default 2s between calls), independent of VLR.
        self.http = RateLimitedSession(_http_config_from_rib(cfg))

    # -- URL builder ---------------------------------------------------------

    def url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        base = f"{self.base}/{path.lstrip('/')}"
        if not params:
            return base
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{base}?{qs}"

    # -- fetching -------------------------------------------------------------

    def get_json(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """GET a path and return the parsed JSON body (the whole envelope)."""
        url = self.url(path, params)
        resp: requests.Response = self.http.get(url, headers=headers)
        if resp.status_code >= 400:
            raise RibRequestError(url, resp.status_code)
        try:
            return resp.json()
        except ValueError:
            raise RibInvalidJSON(url)

    def get_data(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET a path and return the ``data`` field of the envelope (or the body)."""
        body = self.get_json(path, params)
        return body.get("data", body)

    def close(self) -> None:
        self.http.close()


def _http_config_from_rib(cfg: Config) -> HttpConfig:
    rib = cfg.rib
    return HttpConfig(
        base_url=rib.base_url,
        rate_limit_seconds=rib.rate_limit_seconds,
        timeout_seconds=cfg.http.timeout_seconds,
        user_agent=cfg.http.user_agent,
        retries=rib.retries,
        backoff_base_seconds=rib.backoff_base_seconds,
        backoff_factor=rib.backoff_factor,
        retry_status_codes=cfg.http.retry_status_codes,
    )


class RibRequestError(Exception):
    def __init__(self, url: str, status_code: int):
        super().__init__(f"rib.gg request failed ({status_code}): {url}")
        self.url = url
        self.status_code = status_code


class RibInvalidJSON(Exception):
    def __init__(self, url: str):
        super().__init__(f"rib.gg returned non-JSON response: {url}")
        self.url = url
