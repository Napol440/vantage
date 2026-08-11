"""Rate-limited HTTP session with retry and exponential backoff."""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Dict, Iterable, Optional

import requests

from .config import HttpConfig

log = logging.getLogger(__name__)


class RateLimitedSession:
    """A requests.Session that enforces a minimum delay between requests.

    Retries failed requests (connection errors, and any status in
    ``retry_status_codes``) with exponential backoff, capped at ``retries``.
    """

    def __init__(self, cfg: HttpConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": cfg.user_agent})
        self._lock = threading.Lock()
        self._last_request: float = 0.0

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            wait = self.cfg.rate_limit_seconds - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def get(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.request("GET", url, params=params, headers=headers)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> requests.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(self.cfg.retries + 1):
            self._throttle()
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.cfg.timeout_seconds,
                    **kwargs,
                )
                if resp.status_code not in self.cfg.retry_status_codes:
                    return resp
                last_exc = _HttpStatusError(resp)
            except requests.RequestException as exc:
                last_exc = exc

            if attempt < self.cfg.retries:
                delay = _backoff_delay(self.cfg, attempt, last_exc)
                log.warning(
                    "GET %s failed (%s); retrying in %.1fs (attempt %d/%d)",
                    url,
                    last_exc,
                    delay,
                    attempt + 1,
                    self.cfg.retries,
                )
                time.sleep(delay)

        raise RuntimeError(f"Request to {url} failed after retries: {last_exc}")

    def close(self) -> None:
        self.session.close()


class _HttpStatusError(Exception):
    def __init__(self, resp: requests.Response):
        super().__init__(f"HTTP {resp.status_code}")
        self.status_code = resp.status_code


def _backoff_delay(cfg: HttpConfig, attempt: int, exc: Optional[Exception]) -> float:
    base = cfg.backoff_base_seconds * (cfg.backoff_factor**attempt)
    # Small jitter to avoid synchronized retries.
    return base * (0.8 + 0.4 * random.random())
