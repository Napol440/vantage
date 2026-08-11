"""Orchestrator: discover matches, scrape them, store to SQLite + JSON."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

from .config import Config
from .models import EventInfo
from .sources.vlr import matches as vlr_matches
from .sources.vlr import teams as vlr_teams
from .sources.vlr.events import scrape_event
from .sources.vlr.fetcher import VLRFetcher
from .sources.vlr.match import MatchScraper
from .storage import Repository

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    discovered: int = 0
    scraped: int = 0
    skipped_duplicate: int = 0
    failed: List[str] = field(default_factory=list)
    no_data: List[int] = field(default_factory=list)


class Pipeline:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.repo = Repository(cfg.paths.sqlite_path)
        self.scraper = MatchScraper(cfg)
        self.fetcher: VLRFetcher = self.scraper.fetcher
        self._roster_cache: set = set()

    def run(self) -> RunSummary:
        summary = RunSummary()
        target_ids = self._discover_matches()
        summary.discovered = len(target_ids)
        log.info("Discovered %d match(es) to scrape.", len(target_ids))

        limit = self.cfg.scraper.limit
        if limit and limit > 0:
            target_ids = target_ids[:limit]

        for mid, slug in target_ids:
            self._scrape_one(mid, slug, summary)

        return summary

    # -- discovery ------------------------------------------------------------

    def _discover_matches(self) -> List[Tuple[int, Optional[str]]]:
        t = self.cfg.targets
        if t.event:
            event_id, slug = self._resolve_event(t.event)
            log.info("Event mode: event=%s", event_id)
            return vlr_matches.scrape_event_match_ids(self.fetcher, event_id, slug)
        if t.team:
            team_id, slug = vlr_teams.resolve_team(self.fetcher, t.team)
            log.info("Team mode: team=%s (%s)", team_id, slug or "")
            return vlr_matches.scrape_team_match_ids(self.fetcher, team_id, slug)
        if t.date_from or t.date_to:
            df = _parse_date(t.date_from)
            dt = _parse_date(t.date_to)
            log.info("Date mode: %s -> %s", df, dt)
            return vlr_matches.scrape_results_by_date(self.fetcher, date_from=df, date_to=dt)
        raise ValueError(
            "No collection target configured. Pass --team, --event, or "
            "--date-from/--date-to (or set targets.* in config.yaml)."
        )

    def _resolve_event(self, term: str) -> Tuple[int, Optional[str]]:
        term = term.strip()
        if term.isdigit():
            return int(term), None
        if "/" in term:
            head, _, tail = term.partition("/")
            if head.isdigit():
                return int(head), tail or None
        raise ValueError(
            f"Could not resolve event '{term}'. Pass the numeric VLR event id "
            f"(from the event page URL, e.g. https://www.vlr.gg/event/2976/...)."
        )

    # -- scraping ---------------------------------------------------------------

    def _scrape_one(self, mid: int, slug: Optional[str], summary: RunSummary) -> None:
        if not self.cfg.scraper.refresh and self.repo.match_exists(mid):
            summary.skipped_duplicate += 1
            log.info("Match %s already collected; skipping (use --refresh to re-scrape).", mid)
            return
        try:
            match = self.scraper.scrape_match(mid, slug)
        except Exception as exc:
            summary.failed.append(str(mid))
            log.error("Failed to scrape match %s: %s", mid, exc, exc_info=True)
            return

        if not match.maps:
            summary.no_data.append(mid)
            log.warning("Match %s has no map data (upcoming or unrecorded); skipping store.", mid)
            return

        self.repo.save_match(match)
        out = self.repo.dump_match_json(match, self.cfg.paths.json_dir)
        summary.scraped += 1
        log.info("Stored match %s (%d map(s)) -> %s", mid, len(match.maps), out)

        if self.cfg.scraper.include_rosters:
            self._save_rosters(match)

    def _save_rosters(self, match) -> None:
        for team_id in (match.team1_id, match.team2_id):
            if team_id is None or team_id in self._roster_cache:
                continue
            self._roster_cache.add(team_id)
            try:
                roster = vlr_teams.scrape_roster(self.fetcher, team_id)
                team = vlr_teams.scrape_team(self.fetcher, team_id)
                team.name = match.team1_name if team_id == match.team1_id else match.team2_name
                self.repo.save_team(team)
                for player in roster:
                    self.repo.save_player(player)
                log.info("Saved roster for team %s (%d player(s)).", team_id, len(roster))
            except Exception:
                log.warning("Could not fetch roster for team %s.", team_id, exc_info=True)

    # -- event metadata ----------------------------------------------------------

    def collect_event_metadata(self, event_term: str) -> Optional[EventInfo]:
        event_id, slug = self._resolve_event(event_term)
        ev = scrape_event(self.fetcher, event_id, slug)
        self.repo.save_event(ev)
        log.info("Saved event %s (%s) with %d standings, %d bracket entries.",
                 event_id, ev.name, len(ev.standings), len(ev.brackets))
        return ev

    def close(self) -> None:
        self.scraper.close()
        self.repo.close()


def _parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    return date.fromisoformat(raw)
