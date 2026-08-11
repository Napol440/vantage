"""Offline parser smoke tests using fixtures captured from VLR match 712831."""

from __future__ import annotations

import os

import pytest

from vantage.config import Config
from vantage.sources.vlr.match import merge_economy, merge_performance, parse_match_page

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name: str) -> str:
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def match():
    m = parse_match_page(
        712831,
        _read("match_712831.html"),
        "https://www.vlr.gg/712831/karmine-corp-vs-team-liquid-vct-2026-emea-stage-2-w3/",
    )
    merge_economy(m, _read("match_712831_economy.html"))
    merge_performance(m, _read("match_712831_performance.html"))
    return m


def test_header(match):
    assert match.team1_id == 8877 and match.team1_name == "Karmine Corp"
    assert match.team2_id == 474 and match.team2_name == "Team Liquid"
    assert match.event_id == 2976
    assert match.best_of == 3
    assert match.team1_score == 2 and match.team2_score == 1
    assert match.winner_team_id == 8877


def test_veto(match):
    assert len(match.veto) == 7
    assert match.veto[0].action.value == "ban" and match.veto[0].team_name == "Karmine Corp"
    assert match.veto[6].action.value == "remains" and match.veto[6].map_name == "Haven"


def test_maps(match):
    assert [mp.map_name for mp in match.maps] == ["Lotus", "Summit", "Haven"]
    lotus = match.maps[0]
    assert (lotus.team1_score, lotus.team2_score) == (13, 11)
    assert lotus.picked_by_team_id == 8877
    assert lotus.duration_seconds == 3640
    assert lotus.team1_first_half_score == 7 and lotus.team1_second_half_score == 6
    assert len(lotus.rounds) == 24


def test_rounds(match):
    r1 = match.maps[0].rounds[0]
    assert r1.round_number == 1
    assert r1.winning_side.value == "defense"
    assert r1.winning_team_id == 8877


def test_economy(match):
    r2 = match.maps[0].rounds[1]
    assert len(r2.economies) == 2
    e1, e2 = r2.economies
    assert e1.team_name == "Karmine Corp" and e1.buy_type.value == "semi_buy"
    assert e2.team_name == "Team Liquid" and e2.buy_type.value == "eco"
    assert e2.credits == 4600


def test_performance_merge(match):
    for mp in match.maps:
        assert len(mp.players) == 10
    dos9 = next(p for p in match.maps[0].players if p.player_name == "dos9")
    assert dos9.kills == 24 and dos9.assists == 15
    assert dos9.multikills["2k"] == 3
    assert dos9.operator_kills == 0


def test_config_from_file():
    cfg = Config.from_file()
    assert cfg.http.rate_limit_seconds >= 0.5
    assert cfg.paths.data_dir
