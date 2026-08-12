"""Offline tests for the rib.gg source (parser + URL building)."""

from __future__ import annotations

import json
import os

from vantage.config import Config
from vantage.models import BuyType
from vantage.sources.rib.fetcher import RibFetcher
from vantage.sources.rib.parser import (
    buy_type_from_credits,
    event_summary_to_event_info,
    merge_match_details,
    series_to_match,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name: str):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_series_to_match():
    m = series_to_match(_load("rib_series.json"))
    assert m.source == "rib"
    assert m.match_id == 35225
    assert m.event_id == 1866
    assert m.vlr_id == 143760
    assert m.best_of == 3
    assert m.team1_name == "OpTic Gaming" and m.team2_id == 128
    assert m.team1_score == 1 and m.team2_score == 1  # wins per map count
    assert m.winner_team_id is None  # split maps, no overall score in fixture
    assert len(m.teams) == 2
    assert len(m.maps) == 2


def test_series_map_mapping():
    m = series_to_match(_load("rib_series.json"))
    mp = m.maps[0]
    assert mp.map_name == "Bind"
    assert (mp.team1_score, mp.team2_score) == (13, 11)
    assert mp.winner_team_id == 388
    assert len(mp.players) == 2
    yay = mp.players[0]
    assert yay.player_name == "yay"
    assert yay.agent == "jett"          # agent_id 12
    assert yay.kills == 24 and yay.acs == 296
    assert yay.multikills == {"2k": 4, "3k": 2}
    assert yay.clutches_won == {"1v1": 2}


def test_match_details_merge():
    m = series_to_match(_load("rib_series.json"))
    n = merge_match_details(m, _load("rib_series_details.json"))
    assert n == 1
    rounds = m.maps[0].rounds
    assert [r.round_number for r in rounds] == [1, 2, 3]
    r3 = rounds[2]
    assert len(r3.economies) == 2
    e = next(e for e in r3.economies if e.team_name == "OpTic Gaming")
    assert e.credits == 14000       # summed 2x7000
    assert e.bank_after_buy == 10000.0  # summed 2x5000
    assert e.buy_type == BuyType.SEMI_BUY


def test_buy_type_from_credits():
    assert buy_type_from_credits(3000, 2) == BuyType.ECO
    assert buy_type_from_credits(7000, 2) == BuyType.SEMI_ECO
    assert buy_type_from_credits(15000, 2) == BuyType.SEMI_BUY
    assert buy_type_from_credits(25000, 2) == BuyType.FULL_BUY
    assert buy_type_from_credits(4000, 1) == BuyType.PISTOL
    assert buy_type_from_credits(None, 3) == BuyType.UNKNOWN


def test_event_summary():
    data = _load("rib_events.json")["data"][0]
    ev = event_summary_to_event_info(data)
    assert ev.event_id == 1866
    assert ev.name == "VALORANT Champions 2022 - Playoffs"
    assert ev.prize_pool == "$1,000,000"
    assert ev.start_date is not None


def test_fetcher_url_building():
    cfg = Config()
    cfg.rib.base_url = "https://be-prod.rib.gg/v1"
    f = RibFetcher(cfg)
    assert f.url("series/35225") == "https://be-prod.rib.gg/v1/series/35225"
    url = f.url("series", {"take": 50, "eventIds[]": 1866, "completed": "true"})
    assert "take=50" in url and "eventIds%5B%5D" not in url and "eventIds[]=1866" in url
    f.close()
