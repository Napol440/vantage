# vantage

A Python pipeline for collecting Valorant esports match data. Component 1 (this
repo, in working state) scrapes completed matches from [VLR.gg](https://www.vlr.gg);
a later Component 2 will pull supplementary data from the Rib.gg API.

Output is written to a single SQLite database and one JSON file per match, using
a unified schema (`src/vantage/models.py`) that is source-agnostic so records
from VLR.gg and Rib.gg join cleanly.

## What gets collected

- Match header: event, stage, UTC start time, best-of, both teams, final score
- Full veto / pick-ban sequence (with team attribution)
- Per-map results: score, half splits, winner, duration, map picker
- Round timeline: round number, winning team, winning side, win condition
  (elimination / spike defusal / spike detonation / time expiry)
- Per-player-per-map stats (Overview tab): agent, rating, ACS, K/D/A, KAST, ADR,
  HS%, first kills / deaths
- Per-round team economy (Economy tab): buy type (eco / semi-eco / semi-buy /
  full-buy / pistol), bank after buy, total credits
- Performance tab: multikills (2K-5K), clutches (1v1-1v5), operator kills,
  plants and defuses
- Team rosters (optional)

## Requirements

- Python 3.10+
- `pip install -r requirements.txt` (requests, beautifulsoup4, lxml, PyYAML)

## Quick start

```powershell
# Scrape the latest completed matches for a team (by VLR team id, "id/slug", or name)
python run.py --team 474

# Scrape matches from an event (VLR event id or "id/slug")
python run.py --event 2976

# Scrape completed matches within a date range
python run.py --date-from 2026-08-01 --date-to 2026-08-04

# Limit / refresh
python run.py --event 2976 --limit 10
python run.py --team 474 --refresh          # re-scrape matches already in the DB
```

All targets are mutually exclusive; `--limit` caps the number of matches scraped
per run. Add `--no-economy`, `--no-performance`, or `--no-rosters` to skip tabs.
`--event-info <event>` additionally collects standings and brackets.

Configuration lives in `config.yaml` (rate limit, retries, output paths, target
defaults). Paths in config are resolved relative to the config file.

## Output

- SQLite: `data/vantage.db` (see schema in `src/vantage/storage.py`)
- Per-match JSON: `data/json/<match_id>.json`
- Logs: `logs/vantage.log` (console + rotating file)

## Tests

```powershell
python -m pytest tests
```

The parser test runs fully offline against HTML fixtures captured from a real
VLR match.

## Caveats

- VLR.gg is community-run and its HTML changes without notice; the parser is
  tested against fixtures from VCT 2026 EMEA Stage 2 and may need updates.
- Please respect VLR.gg: the scraper defaults to ~1 request/second with retry /
  backoff. VLR's robots.txt only disallows `/search/auto` and `/rr/`.
- The Economy and Performance tabs are not present on every match (mainly
  low-tier/amateur games); those sections are skipped gracefully and logged.
- The operator-kill matrix on the Performance tab lists one team per matrix, so
  `operator_kills` may be `null` for one of the two teams.
- The Rib.gg component is not yet implemented; the `rib` config block is a
  placeholder and `enabled` defaults to `false`.
