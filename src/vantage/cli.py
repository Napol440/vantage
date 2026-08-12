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
    rib = p.add_argument_group("rib.gg (Component 2)")
    rib.add_argument("--rib", action="store_true",
                     help="Also collect series from rib.gg (requires an event id).")
    rib.add_argument("--rib-event", dest="rib_event", type=int, default=None,
                     help="rib.gg event id to collect series for (overrides rib.event_id).")
    rib.add_argument("--rib-take", dest="rib_take", type=int, default=None,
                     help="Max series to fetch per rib.gg page (default 50).")
    rib.add_argument("--no-rib-details", dest="no_rib_details", action="store_true",
                     help="Skip per-map match/details economy calls on rib.gg.")
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
    if args.rib:
        cfg.rib.enabled = True
    if args.rib_event is not None:
        cfg.rib.event_id = args.rib_event
    if args.rib_take is not None:
        cfg.rib.take = args.rib_take
    if args.no_rib_details:
        cfg.rib.fetch_details = False


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config.from_file(args.config)
    _apply_overrides(cfg, args)
    setup_logging(cfg)

    has_vlr_target = any([cfg.targets.team, cfg.targets.event,
                          cfg.targets.date_from, cfg.targets.date_to])
    if not has_vlr_target and not cfg.rib.enabled:
        build_parser().error(
            "No target set. Use --team, --event, --date-from/--date-to, or --rib."
        )

    pipeline = Pipeline(cfg)
    summary = None
    try:
        if args.event_info:
            ev = pipeline.collect_event_metadata(args.event_info)
            log.info("Event metadata collected: %s", ev.name if ev else "?")
        if has_vlr_target:
            summary = pipeline.run()
        if cfg.rib.enabled:
            rib_summary = pipeline.collect_rib()
            if rib_summary is not None and (rib_summary.scraped or rib_summary.failed):
                log.info(
                    "rib.gg run: %d discovered, %d stored, %d duplicate-skipped, %d failed.",
                    rib_summary.discovered, rib_summary.scraped,
                    rib_summary.skipped_duplicate, len(rib_summary.failed),
                )
    finally:
        pipeline.close()

    if summary is not None:
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
