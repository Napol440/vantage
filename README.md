# vantage

A Python pipeline for collecting Valorant esports match data. Two sources:

- **VLR.gg scraper** (Component 1, complete): scrapes completed matches, rosters,
  and event standings/brackets from [VLR.gg](https://www.vlr.gg).
- **Rib.gg caller** (Component 2): pulls series/match data from the Rib.gg API.

Both write to one SQLite database and one JSON file per match, using a unified
schema (`src/vantage/models.py`) that is source-agnostic so records from VLR.gg
and Rib.gg join cleanly — including via `matches.vlr_id`, which Rib.gg series
carry as a cross-reference to the VLR match id.

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

### Rib.gg (best-effort)

Rib.gg has no official public API; the implemented endpoints are the
community-documented classic ones, and the backend host is frequently
unreachable. Enable it only when you have a working host (see
`docs/RIB_REDISCOVERY.md`):

```powershell
python run.py --rib --rib-event 1866 --no-rosters
python run.py --rib --rib-event 1866 --no-rib-details   # skip per-map economy calls
```

`--rib-event` overrides `rib.event_id` in `config.yaml`. Rib failures are logged
and never affect the VLR pipeline.

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
- The Rib.gg component is best-effort: no official API, `be-prod.rib.gg` is often
  unreachable, and economy data there is per-player (the parser aggregates it
  per team). Keep `rib.enabled` off unless you have a working host.
- Rib.gg series report economy per player, so its per-round `TeamEconomy` rows
  are approximations (summed credits/costs).
