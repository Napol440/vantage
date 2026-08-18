"""Command-line entry points for the vantage toolkit.

Scraper:
    python -m vantage.cli scrape --team 474
    python -m vantage.cli scrape --event 2976 --limit 5

CV (computer vision):
    python -m vantage.cli cv harvest <match_id>
    python -m vantage.cli cv run <match_id> [--map N] [--seconds N]
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from vantage.config import CvConfig
from vantage.logging_setup import setup_logging
from vantage.storage import Storage

log = logging.getLogger(__name__)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="vantage", description="Valorant esports analytics toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- Scraper subcommand ---
    scrape = sub.add_parser("scrape", help="VLR.gg / rib.gg scraper")
    scrape.add_argument("--config", default=None, help="Path to config.yaml.")
    g = scrape.add_mutually_exclusive_group()
    g.add_argument("--team", dest="team", default=None,
                   help="Team id, 'id/slug', or name (resolved via /rankings).")
    g.add_argument("--event", dest="event", default=None,
                   help="Event id or 'id/slug'.")
    g.add_argument("--date-from", dest="date_from", default=None,
                   help="YYYY-MM-DD. Scrape completed matches from this date.")
    scrape.add_argument("--date-to", dest="date_to", default=None,
                        help="YYYY-MM-DD. Scrape completed matches up to this date.")
    scrape.add_argument("--limit", dest="limit", type=int, default=None,
                        help="Max matches to scrape (0 = config/unlimited).")
    scrape.add_argument("--refresh", action="store_true",
                        help="Re-scrape matches already in the database.")
    scrape.add_argument("--no-economy", action="store_true",
                        help="Skip the Economy tab.")
    scrape.add_argument("--no-performance", action="store_true",
                        help="Skip the Performance tab.")
    scrape.add_argument("--no-rosters", action="store_true",
                        help="Skip fetching team rosters.")
    scrape.add_argument("--event-info", dest="event_info", default=None,
                        help="Also collect standings/brackets for this event id/slug.")
    rib = scrape.add_argument_group("rib.gg (Component 2)")
    rib.add_argument("--rib", action="store_true",
                     help="Also collect series from rib.gg (requires an event id).")
    rib.add_argument("--rib-event", dest="rib_event", type=int, default=None,
                     help="rib.gg event id to collect series for (overrides rib.event_id).")
    rib.add_argument("--rib-take", dest="rib_take", type=int, default=None,
                     help="Max series to fetch per rib.gg page (default 50).")
    rib.add_argument("--no-rib-details", dest="no_rib_details", action="store_true",
                     help="Skip per-map match/details economy calls on rib.gg.")
    scrape.set_defaults(handler=_cmd_scrape)

    # --- CV subcommands ---
    cv = sub.add_parser("cv", help="Computer vision (minimap detection)")
    cv.add_argument("--config", default=None, help="Path to config.yaml.")
    cv_sub = cv.add_subparsers(dest="cv_command", required=True)

    harvest = cv_sub.add_parser("harvest", help="harvest VLR VOD links into the DB")
    harvest.add_argument("match_id", type=int)
    harvest.set_defaults(handler=_cmd_harvest)

    add_vod = cv_sub.add_parser("add-vod", help="register a VOD link manually for a match")
    add_vod.add_argument("match_id", type=int)
    add_vod.add_argument("url", help="YouTube watch / youtu.be URL, optionally with ?t= start")
    add_vod.add_argument("--map", type=int, default=None, help="map number (default: auto)")
    add_vod.add_argument("--label", default="", help="optional VLR map label")
    add_vod.set_defaults(handler=_cmd_add_vod)

    ingest = cv_sub.add_parser("ingest", help="stream a map window and report frame stats")
    ingest.add_argument("match_id", type=int)
    ingest.add_argument("--map", type=int, default=None, help="map number (default: all)")
    ingest.add_argument("--seconds", type=int, default=0,
                        help="cap each window at N seconds (0 = full window)")
    ingest.add_argument("--image", default=None,
                        help="save the first frame of each window to this dir (jpg)")
    ingest.set_defaults(handler=_cmd_ingest)

    run = cv_sub.add_parser("run", help="stream, segment rounds, detect markers, persist ticks")
    run.add_argument("match_id", type=int)
    run.add_argument("--map", type=int, default=None, help="map number (default: all)")
    run.add_argument("--seconds", type=int, default=0,
                     help="cap each window at N seconds (0 = full window)")
    run.add_argument("--map-name", default="",
                     help="map name for geolocation calibration (e.g. lotus)")
    run.set_defaults(handler=_cmd_run)

    cal = cv_sub.add_parser("calibrate", help="extract frames for labelling, import labels, evaluate")
    cal.add_argument("match_id", type=int)
    cal.add_argument("--map", type=int, default=None, help="map number (default: all)")
    cal.add_argument("--seconds", type=int, default=0,
                     help="cap each window at N seconds (0 = full window)")
    cal.add_argument("--step", type=int, default=6,
                     help="sample every Nth frame (6 => 1/s at 6fps)")
    cal.add_argument("--max-frames", type=int, default=40, help="frame cap per window")
    cal.add_argument("--extract", action="store_true", default=True,
                     help="save sample frames + manifest.csv (default)")
    cal.add_argument("--import-csv", default=None,
                     help="import a labelled manifest.csv (fill with label_tool.html)")
    cal.add_argument("--eval", action="store_true",
                     help="re-run localize over labelled frames and report agreement")
    cal.add_argument("--out", default="data/labels",
                     help="output directory for extracted frames")
    cal.set_defaults(handler=_cmd_calibrate)

    args = parser.parse_args(argv)

    if args.command == "scrape":
        from vantage.config import Config
        from vantage.pipeline import Pipeline
        cfg = Config.from_file(args.config)
        _apply_overrides(cfg, args)
        setup_logging(cfg)
        return args.handler(args, cfg)
    else:
        cfg = CvConfig.load(args.config)
        return args.handler(args, cfg)


def _apply_overrides(cfg, args: argparse.Namespace) -> None:
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


def _cmd_scrape(args, cfg) -> int:
    from vantage.pipeline import Pipeline
    has_vlr_target = any([cfg.targets.team, cfg.targets.event,
                          cfg.targets.date_from, cfg.targets.date_to])
    if not has_vlr_target and not cfg.rib.enabled:
        log.error("No target set. Use --team, --event, --date-from/--date-to, or --rib.")
        return 2

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


def _cmd_harvest(args, cfg: CvConfig) -> int:
    from .vlr.match import fetch_match_page

    page = fetch_match_page(args.match_id)
    with Storage(cfg.db_path) as db:
        n = db.save_vods(page.vods)
    for v in page.vods:
        print(f"  map {v.map_number}: {v.label or ''} url={v.url} start_s={v.start_s}s")
    print(f"harvested {n} VOD row(s) for match {args.match_id}")
    return 0


def _cmd_add_vod(args, cfg: CvConfig) -> int:
    from .models import Vod, parse_youtube_url

    with Storage(cfg.db_path) as db:
        if args.map is None:
            existing = db.get_vods(args.match_id)
            args.map = (max([v.map_number for v in existing], default=0) + 1)
        vod = Vod(match_id=args.match_id, map_number=args.map, url=args.url,
                  label=args.label)
        vid, t = parse_youtube_url(args.url)
        print(f"  map {args.map}: video_id={vid} start_s={vod.start_s}s label={args.label or ''}")
        db.upsert_vod(vod)
    print(f"registered VOD for match {args.match_id} map {args.map}")
    return 0


def _cmd_ingest(args, cfg: CvConfig) -> int:
    from .cv.ingest import stream_vod_window

    with Storage(cfg.db_path) as db:
        all_vods = db.get_vods(args.match_id)
        if not all_vods:
            print(f"no VODs for match {args.match_id}; run 'vantage cv harvest {args.match_id}' first",
                  file=sys.stderr)
            return 2
        vods = [v for v in all_vods if args.map is None or v.map_number == args.map]

    for vod in vods:
        duration = _window_duration(vod, args.seconds)
        print(f"  stream map {vod.map_number} ({vod.video_id}, start_s={vod.start_s}s)")
        try:
            stream, frames = stream_vod_window(vod, cfg, duration_s=duration)
            print(f"  resolved {stream.height}p {stream.ext} ({stream.protocol})")
            n = 0
            for frame in frames:
                n += 1
                if args.image and n == 1:
                    from pathlib import Path

                    out = Path(args.image)
                    out.mkdir(parents=True, exist_ok=True)
                    frame.save(out / f"match{vod.match_id}_map{vod.map_number}_f0.jpg")
            print(f"  -> {n} frames at {cfg.fps}fps")
        except Exception as exc:
            print(f"  !! failed: {exc}", file=sys.stderr)
    return 0


def _window_duration(vod, seconds: int) -> int | None:
    duration = vod.duration_s or seconds or None
    if seconds:
        duration = min(duration, seconds) if duration else seconds
    return duration


def _cmd_run(args, cfg: CvConfig) -> int:
    from .cv.detect import detect_markers
    from .cv.ingest import stream_vod_window
    from .cv.localize import localize_minimap
    from .cv.profiles import get_profile
    from .cv.rounds import RoundState
    from .cv.track import Tracker

    profile = get_profile(cfg.production_profile)
    with Storage(cfg.db_path) as db:
        all_vods = db.get_vods(args.match_id)
        if not all_vods:
            print(f"no VODs for match {args.match_id}; run 'vantage cv harvest {args.match_id}' first",
                  file=sys.stderr)
            return 2
        vods = [v for v in all_vods if args.map is None or v.map_number == args.map]

        for vod in vods:
            duration = _window_duration(vod, args.seconds)
            print(f"  map {vod.map_number}: stream + segment + detect")
            state = RoundState()
            tracker = Tracker()
            totals = {"rounds": 0, "overview": 0, "corner": 0, "ally": 0, "enemy": 0, "ticks": 0}
            try:
                stream, frames = stream_vod_window(vod, cfg, duration_s=duration)
                for frame in frames:
                    region = localize_minimap(frame.image, profile)
                    rnum, ms = state.update(frame.pts_s,
                                            region.kind if region else None, cfg.fps)
                    if rnum == 0:
                        continue
                    totals["ticks"] += 1
                    if region is None:
                        continue
                    totals[region.kind] = totals.get(region.kind, 0) + 1
                    det = detect_markers(region.crop(frame.image), profile)
                    tracks = tracker.update(frame.index, det.ally, det.enemy)
                    track_lookup = {}
                    for t in tracks:
                        x, y = t.last_pos
                        track_lookup[(t.team, round(x), round(y))] = t.track_id
                    players = []
                    for d in det.ally:
                        p = _mk_player(args.match_id, vod.map_number, rnum, ms,
                                       frame.index, "ally", d)
                        p.track_id = _find_track(track_lookup, "ally", d)
                        players.append(p)
                    for d in det.enemy:
                        p = _mk_player(args.match_id, vod.map_number, rnum, ms,
                                       frame.index, "enemy", d)
                        p.track_id = _find_track(track_lookup, "enemy", d)
                        players.append(p)
                    if players:
                        db.insert_tick(match_id=args.match_id, map_number=vod.map_number,
                                       round_number=rnum, ms_into_round=ms,
                                       frame_index=frame.index, pts_s=frame.pts_s,
                                       players=players, utilities=[], spike=None)
                    totals["ally"] += len(det.ally)
                    totals["enemy"] += len(det.enemy)
                totals["rounds"] = state.round_number
            except Exception as exc:
                print(f"  !! failed: {exc}", file=sys.stderr)
            print(f"  -> rounds={totals['rounds']} overview={totals.get('overview',0)} "
                  f"corner={totals.get('corner',0)} "
                  f"ally={totals['ally']} enemy={totals['enemy']} "
                  f"ticks={totals['ticks']} tracks={len(tracker.active_tracks)}")
    return 0


def _mk_player(match_id, map_number, rnum, ms, frame_index, team, dot):
    from .models import PlayerState

    return PlayerState(match_id=match_id, map_number=map_number, round_number=rnum,
                       ms_into_round=ms, frame_index=frame_index, team=team,
                       x_px=float(dot["x"]), y_px=float(dot["y"]), visible=True)


def _find_track(track_lookup, team, dot):
    x, y = round(dot["x"]), round(dot["y"])
    key = (team, x, y)
    if key in track_lookup:
        return track_lookup[key]
    for dx in range(-5, 6):
        for dy in range(-5, 6):
            key = (team, x + dx, y + dy)
            if key in track_lookup:
                return track_lookup[key]
    return None


def _cmd_calibrate(args, cfg: CvConfig) -> int:
    from pathlib import Path

    from .cv.calibrate import eval_agreement, extract_frames, import_labels, write_label_tool
    from .cv.profiles import get_profile

    with Storage(cfg.db_path) as db:
        all_vods = db.get_vods(args.match_id)
        if not all_vods:
            print(f"no VODs for match {args.match_id}; run 'vantage cv harvest {args.match_id}' first",
                  file=sys.stderr)
            return 2
        vods = [v for v in all_vods if args.map is None or v.map_number == args.map]

    out_root = Path(args.out)
    if args.import_csv:
        n = import_labels(cfg, Path(args.import_csv), args.match_id,
                          args.map if args.map is not None else (vods[0].map_number if vods else 0))
        print(f"  -> imported {n} label row(s)")
        return 0

    for vod in vods:
        duration = _window_duration(vod, args.seconds)
        out_dir = out_root / f"match{args.match_id}_map{vod.map_number}"
        print(f"  map {vod.map_number}: window={vod.start_s}s+")
        if args.eval:
            res = eval_agreement(vod, cfg, get_profile(cfg.production_profile),
                                 args.match_id, vod.map_number, duration_s=duration)
            print(f"  -> eval frames={res['frames']} "
                  f"accuracy={res['accuracy'] and round(res['accuracy'], 3)}")
            for kind, st in res["per_kind"].items():
                r = st["recall"]
                print(f"      {kind}: {st['tp']}/{st['n']} "
                      f"({r and round(r, 3)})")
            continue
        if args.extract:
            rows = extract_frames(vod, cfg, out_dir, step=args.step,
                                  max_frames=args.max_frames, duration_s=duration)
            tool = write_label_tool(out_dir, rows)
            print(f"  -> saved {len(rows)} frames to {out_dir}")
            print(f"     open {tool} in a browser, label, then re-run with --import-csv {out_dir / 'manifest.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
