# Rib.gg API — endpoint reference & rediscovery notes

Rib.gg publishes **no official public API**. The endpoints implemented in
`src/vantage/sources/rib/` are the community-documented "classic" ones, reverse
engineered by the R package [`tonyelhabr/valorantr`](https://github.com/tonyelhabr/valorantr)
and confirmed against real traffic.

> Status check (Aug 2026): `be-prod.rib.gg` does not resolve on some networks,
> and `www.rib.gg` rejects plain requests. Rib collection is therefore
> **best-effort and opt-in** (`rib.enabled: true`). If your network can reach a
> working host, point `rib.base_url` at it.

## Classic endpoints

Base URL: `https://be-prod.rib.gg/v1`

| Purpose | Method & path |
| --- | --- |
| All teams | `GET /teams/all` |
| Team detail | `GET /teams/{teamId}` |
| Player detail | `GET /players/{playerId}` |
| Events (paginated) | `GET /events?query=&sort=startDate&sortAscending=false&hasSeries=true&take=50` |
| Series for an event | `GET /series?take=50&eventIds[]={eventId}&completed=true` |
| Series detail (matches/player stats) | `GET /series/{seriesId}` |
| Map-level detail | `GET /matches/{matchId}/details` → `events`, `locations`, `economies` |
| Agent analytics | `GET /analytics/agents?map_id&region_id&event_id&role_id&patch_id` |
| Composition analytics | `GET /analytics/compositions?map_id&region_id&event_id&role_id&patch_id` |
| Map analytics | `GET /analytics/maps?region_id&event_id&patch_id` |
| Weapon analytics | `GET /analytics/weapons?map_id&side&region_id&event_id&role_id&patch_id` |

Response envelope:

- List endpoints → `{"meta": {"total": N, "start": 0, "results": N}, "data": [...]}`
- Detail endpoints → `{"data": {...}}`

## Series payload (key fields)

`id`, `event_id`, `team1id`, `team2id`, `start_date`, `best_of`, `stage`,
`bracket`, `completed`, `live`, `win_condition`, **`vlr_id`** (VLR match id — the
cross-source join key used by this pipeline), `vod_url`, `event_name`,
`event_slug`, `event_logo_url`, `team1`, `team2`, `matches` (per-map results),
`stats`, `player_stats` (per map per player).

## How to rediscover / verify endpoints

1. **Check connectivity first** (DNS + TLS) — the failure modes change over time:
   ```powershell
   Resolve-DnsName be-prod.rib.gg
   curl.exe -s -o NUL -w "%{http_code}" https://be-prod.rib.gg/v1/teams/all
   ```
2. **Browser DevTools.** Open a rib.gg page (e.g. an event's match list), open
   Network tab, filter `Fetch/XHR`, and look for calls to a JSON backend
   (`be-prod.rib.gg`, `backend-prod.rib.gg`, or a CDN). Record base URL + paths.
3. **Grep the valorantr source** for the canonical paths:
   `https://github.com/tonyelhabr/valorantr/blob/master/R/get.R`
4. **Probe the envelope.** Confirm `meta`/`data` shape with a small request and
   note field naming (rib is inconsistent: snake_case top-level vs camelCase in
   some query params). `src/vantage/sources/rib/parser.py` reads both spellings.
5. **Update config.** Put the working host in `config.yaml` → `rib.base_url`,
   flip `rib.enabled: true`, and run `python run.py --rib --rib-event <id>`.

## Query-parameter naming

`tonyelhabr/valorantr` sends snake_case params (`map_id`, `region_id`). The raw
API is documented with camelCase (`mapId=1&regionId=2&side=atk`). The client
defaults to snake_case; if a rediscovered host needs camelCase, pass them
explicitly:
```python
client.analytics("weapons", mapId=1, regionId=2, side="atk")
```

## Caveats

- Rib.gg economy data is **per-player per-round** (loadout cost + credits), not
  per-team buy symbols. The parser aggregates players per team per round to fill
  the unified `TeamEconomy` model (`credits` = sum, `bank_after_buy` = sum of
  cost, `buy_type` from summed credits via the same thresholds as VLR).
- The operator-kill / first-kill matrices present on the site may not all be in
  the API; missing fields are left `null`.
- `series` pagination uses `take`/`start` in `meta`; the client currently reads
  the first page (`take` from config, default 50).
