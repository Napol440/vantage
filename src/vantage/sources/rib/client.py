"""High-level typed access to the rib.gg API.

Implements the community-documented "classic" endpoints. Every method returns
the decoded JSON (parsed defensively by ``parser.py``), or raises
``RibRequestError`` / ``RibInvalidJSON``. Nothing here blocks on a dead host:
callers are expected to catch ``requests.RequestException`` and log.

Query-parameter naming follows ``tonyelhabr/valorantr`` (snake_case). If the
backend is rediscovered with camelCase params (``mapId``), pass them explicitly:
    client.analytics("agents", mapId=1, regionId=2)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...config import Config
from .fetcher import RibFetcher


class RibClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.fetcher = RibFetcher(cfg)

    def close(self) -> None:
        self.fetcher.close()

    # -- reference / lookups ---------------------------------------------------

    def all_teams(self) -> Any:
        return self.fetcher.get_data("teams/all")

    def team(self, team_id: int) -> Any:
        return self.fetcher.get_data(f"teams/{team_id}")

    def player(self, player_id: int) -> Any:
        return self.fetcher.get_data(f"players/{player_id}")

    # -- events / series / matches ---------------------------------------------

    def events(
        self,
        query: Optional[str] = None,
        *,
        take: int = 50,
        sort: str = "startDate",
        sort_ascending: bool = False,
        has_series: bool = True,
    ) -> Any:
        params: Dict[str, Any] = {
            "sort": sort,
            "sortAscending": str(sort_ascending).lower(),
            "hasSeries": str(has_series).lower(),
            "take": take,
        }
        if query:
            params["query"] = query
        return self.fetcher.get_data("events", params)

    def series_for_event(
        self,
        event_id: int,
        *,
        take: int = 50,
        completed: bool = True,
    ) -> Any:
        return self.fetcher.get_data(
            "series",
            {"take": take, "eventIds[]": event_id, "completed": str(completed).lower()},
        )

    def series(self, series_id: int) -> Any:
        return self.fetcher.get_data(f"series/{series_id}")

    def match_details(self, match_id: int) -> Any:
        return self.fetcher.get_data(f"matches/{match_id}/details")

    # -- analytics ----------------------------------------------------------------

    def analytics(self, kind: str, **params: Any) -> Any:
        """Generic analytics call.

        ``kind`` is one of ``agents``, ``compositions``, ``maps``, ``weapons``.
        Accepted filter kwargs: ``map_id``, ``region_id``, ``event_id``,
        ``role_id``, ``patch_id``, ``side``.
        """
        clean = {k: v for k, v in params.items() if v is not None}
        return self.fetcher.get_data(f"analytics/{kind}", clean)

    def agent_analytics(self, **params: Any) -> Any:
        return self.analytics("agents", **params)

    def composition_analytics(self, **params: Any) -> Any:
        return self.analytics("compositions", **params)

    def map_analytics(self, **params: Any) -> Any:
        return self.analytics("maps", **params)

    def weapon_analytics(self, **params: Any) -> Any:
        return self.analytics("weapons", **params)
