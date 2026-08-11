"""CLI entry point for the vantage VLR.gg scraper.

Examples:
    python run.py --team 474
    python run.py --event 2976 --limit 5
    python run.py --event 2976 --no-economy
    python run.py --date-from 2026-08-01 --date-to 2026-08-03
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from vantage.config import Config
from vantage.logging_setup import setup_logging
from vantage.pipeline import Pipeline

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vantage",
        description="Valorant esports data pipeline - VLR.gg scraper.",
    )
    p.add_argument("--config", default=None, help="Path to config.yaml.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--team", dest="team", default=None,
                   help="Team id, 'id/slug', or name (resolved via /rankings).")
    g.add_argument("--event", dest="event", default=None,
                   help="Event id or 'id/slug'.")
    g.add_argument("--date-from", dest="date_from", default=None,
                   help="YYYY-MM-DD. Scrape completed matches from this date.")
    p.add_argument("--date-to", dest="date_to", default=None,
                   help="YYYY-MM-DD. Scrape completed matches up to this date.")
    p.add_argument("--limit", dest="limit", type=int, default=None,
                   help="Max matches to scrape (0 = config/unlimited).")
    p.add_argument("--refresh", action="store_true",
                   help="Re-scrape matches already in the database.")
    p.add_argument("--no-economy", action="store_true",
                   help="Skip the Economy tab.")
    p.add_argument("--no-performance", action="store_true",
                   help="Skip the Performance tab.")
    p.add_argument("--no-rosters", action="store_true",
                   help="Skip fetching team rosters.")
    p.add_argument("--event-info", dest="event_info", default=None,
                   help="Also collect standings/brackets for this event id/slug.")
    return p


def _apply_overrides(cfg: Config, args: argparse.Namespace) -> None:
    if args.team is not None:
        cfg.targets.team = args.team
    if args.event is not None:
        cfg.targets.event = args.event
    if args.date_from is not None:
        cfg.targets.date_from = args.date_from
    if args.date_to is not None:
        cfg.targets.date_to = args.date_to
    if args.limit is not None:
        cfg.scraper.limit = args.limit
    if args.refresh:
        cfg.scraper.refresh = True
    if args.no_economy:
        cfg.scraper.include_economy = False
    if args.no_performance:
        cfg.scraper.include_performance = False
    if args.no_rosters:
        cfg.scraper.include_rosters = False


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config.from_file(args.config)
    _apply_overrides(cfg, args)
    setup_logging(cfg)

    if not any([cfg.targets.team, cfg.targets.event, cfg.targets.date_from, cfg.targets.date_to]):
        build_parser().error(
            "No target set. Use --team, --event, or --date-from/--date-to."
        )

    pipeline = Pipeline(cfg)
    try:
        if args.event_info:
            ev = pipeline.collect_event_metadata(args.event_info)
            log.info("Event metadata collected: %s", ev.name if ev else "?")
        summary = pipeline.run()
    finally:
        pipeline.close()

    log.info(
        "Run complete: %d discovered, %d stored, %d duplicate-skipped, "
        "%d failed, %d no-data.",
        summary.discovered, summary.scraped, summary.skipped_duplicate,
        len(summary.failed), len(summary.no_data),
    )
    if summary.failed:
        log.warning("Failed matches: %s", ", ".join(summary.failed))
    if summary.no_data:
        log.warning("Matches without map data: %s", ", ".join(map(str, summary.no_data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
