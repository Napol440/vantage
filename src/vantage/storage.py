"""SQLite storage with idempotent upserts, plus JSON export.

Records are keyed by ``(source, id)`` so that re-runs de-duplicate cleanly and
so records from a future Rib.gg source join without clashing on ids.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import (
    CV_SOURCE,
    EventInfo,
    MapResult,
    Match,
    Player,
    PlayerMatchStats,
    PlayerState,
    Round,
    SpikeState,
    Team,
    UtilityState,
    VetoEntry,
    Vod,
)

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    source TEXT NOT NULL,
    event_id INTEGER NOT NULL,
    name TEXT, region TEXT, tier TEXT,
    start_date TEXT, end_date TEXT, prize_pool TEXT,
    PRIMARY KEY (source, event_id)
);

CREATE TABLE IF NOT EXISTS teams (
    source TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    name TEXT, region TEXT, logo_url TEXT,
    PRIMARY KEY (source, team_id)
);

CREATE TABLE IF NOT EXISTS players (
    source TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    name TEXT, handle TEXT, real_name TEXT, country TEXT,
    PRIMARY KEY (source, player_id)
);

CREATE TABLE IF NOT EXISTS matches (
    source TEXT NOT NULL,
    match_id INTEGER NOT NULL,
    event_id INTEGER, event_name TEXT, stage TEXT,
    date TEXT, best_of INTEGER,
    team1_id INTEGER, team2_id INTEGER,
    team1_name TEXT, team2_name TEXT,
    team1_score INTEGER, team2_score INTEGER,
    winner_team_id INTEGER,
    veto_text TEXT, url TEXT, vlr_id INTEGER,
    PRIMARY KEY (source, match_id)
);

CREATE TABLE IF NOT EXISTS match_teams (
    source TEXT NOT NULL, match_id INTEGER NOT NULL, team_id INTEGER NOT NULL,
    PRIMARY KEY (source, match_id, team_id)
);

CREATE TABLE IF NOT EXISTS maps (
    source TEXT NOT NULL, match_id INTEGER NOT NULL, map_number INTEGER NOT NULL,
    map_id INTEGER, map_name TEXT,
    team1_score INTEGER, team2_score INTEGER,
    team1_half1 INTEGER, team1_half2 INTEGER,
    team2_half1 INTEGER, team2_half2 INTEGER,
    winner_team_id INTEGER, duration_seconds INTEGER, picked_by_team_id INTEGER,
    PRIMARY KEY (source, match_id, map_number)
);

CREATE TABLE IF NOT EXISTS vetoes (
    source TEXT NOT NULL, match_id INTEGER NOT NULL, seq INTEGER NOT NULL,
    action TEXT, team_name TEXT, map_name TEXT,
    PRIMARY KEY (source, match_id, seq)
);

CREATE TABLE IF NOT EXISTS rounds (
    source TEXT NOT NULL, match_id INTEGER NOT NULL, map_number INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    win_condition TEXT, winning_side TEXT,
    winning_team_id INTEGER, winning_team_name TEXT,
    PRIMARY KEY (source, match_id, map_number, round_number)
);

CREATE TABLE IF NOT EXISTS round_economies (
    source TEXT NOT NULL, match_id INTEGER NOT NULL, map_number INTEGER NOT NULL,
    round_number INTEGER NOT NULL, team_id INTEGER NOT NULL,
    team_name TEXT, buy_type TEXT, bank_after_buy REAL, credits INTEGER,
    PRIMARY KEY (source, match_id, map_number, round_number, team_id)
);

CREATE TABLE IF NOT EXISTS player_stats (
    source TEXT NOT NULL, match_id INTEGER NOT NULL, map_number INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    player_name TEXT, team_id INTEGER, team_name TEXT, agent TEXT,
    rating REAL, acs INTEGER, kills INTEGER, deaths INTEGER, assists INTEGER,
    kast REAL, adr REAL, headshot_pct REAL,
    first_kills INTEGER, first_deaths INTEGER,
    operator_kills INTEGER, multikills TEXT, clutches TEXT, clutch_rounds TEXT,
    plants INTEGER, defuses INTEGER,
    PRIMARY KEY (source, match_id, map_number, player_id)
);

-- CV pipeline tables (Component 3)

CREATE TABLE IF NOT EXISTS vods (
    match_id   INTEGER NOT NULL,
    map_number INTEGER NOT NULL,
    video_id   TEXT NOT NULL,
    url        TEXT NOT NULL,
    start_s    INTEGER NOT NULL DEFAULT 0,
    duration_s INTEGER NOT NULL DEFAULT 0,
    label      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (match_id, map_number)
);

CREATE TABLE IF NOT EXISTS tick_players (
    source        TEXT NOT NULL DEFAULT 'cv',
    match_id      INTEGER NOT NULL,
    map_number    INTEGER NOT NULL,
    round_number  INTEGER NOT NULL,
    ms_into_round INTEGER NOT NULL,
    frame_index   INTEGER NOT NULL,
    row_idx       INTEGER NOT NULL DEFAULT 0,
    pts_s         REAL NOT NULL,
    team          TEXT NOT NULL DEFAULT 'ally',
    side          TEXT NOT NULL DEFAULT '',
    agent         TEXT,
    track_id      INTEGER,
    x_px          REAL NOT NULL,
    y_px          REAL NOT NULL,
    world_x       REAL,
    world_y       REAL,
    PRIMARY KEY (source, match_id, map_number, round_number, ms_into_round, frame_index, row_idx)
);

CREATE TABLE IF NOT EXISTS tick_utilities (
    source        TEXT NOT NULL DEFAULT 'cv',
    match_id      INTEGER NOT NULL,
    map_number    INTEGER NOT NULL,
    round_number  INTEGER NOT NULL,
    ms_into_round INTEGER NOT NULL,
    frame_index   INTEGER NOT NULL,
    row_idx       INTEGER NOT NULL DEFAULT 0,
    pts_s         REAL NOT NULL,
    kind          TEXT NOT NULL,
    x_px          REAL NOT NULL,
    y_px          REAL NOT NULL,
    world_x       REAL,
    world_y       REAL,
    PRIMARY KEY (source, match_id, map_number, round_number, ms_into_round, frame_index, row_idx)
);

CREATE TABLE IF NOT EXISTS tick_spike (
    source        TEXT NOT NULL DEFAULT 'cv',
    match_id      INTEGER NOT NULL,
    map_number    INTEGER NOT NULL,
    round_number  INTEGER NOT NULL,
    ms_into_round INTEGER NOT NULL,
    frame_index   INTEGER NOT NULL,
    pts_s         REAL NOT NULL,
    present       INTEGER NOT NULL,
    x_px          REAL,
    y_px          REAL,
    world_x       REAL,
    world_y       REAL,
    PRIMARY KEY (source, match_id, map_number, round_number, ms_into_round, frame_index)
);

CREATE TABLE IF NOT EXISTS calibrations (
    map_name       TEXT NOT NULL,
    production     TEXT NOT NULL,
    source         TEXT NOT NULL,
    transform_json TEXT NOT NULL,
    anchors_json   TEXT NOT NULL,
    residual_mae   REAL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (map_name, production, source)
);

CREATE TABLE IF NOT EXISTS labels (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id      INTEGER NOT NULL,
    map_number    INTEGER NOT NULL,
    frame_index   INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    side          TEXT,
    agent         TEXT,
    x_px          REAL NOT NULL,
    y_px          REAL NOT NULL,
    w_px          REAL,
    h_px          REAL,
    world_x       REAL,
    world_y       REAL,
    source        TEXT NOT NULL DEFAULT 'manual',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Repository:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was first created."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(matches)")}
        if "vlr_id" not in cols:
            self.conn.execute("ALTER TABLE matches ADD COLUMN vlr_id INTEGER")

    # -- query helpers ------------------------------------------------------

    def match_exists(self, match_id: int, source: str = "vlr") -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM matches WHERE source = ? AND match_id = ?",
            (source, match_id),
        )
        return cur.fetchone() is not None

    def collected_match_ids(self, source: str = "vlr") -> List[int]:
        cur = self.conn.execute(
            "SELECT match_id FROM matches WHERE source = ? ORDER BY match_id",
            (source,),
        )
        return [r["match_id"] for r in cur.fetchall()]

    # -- write --------------------------------------------------------------

    def save_match(self, match: Match) -> None:
        """Replace all data for a match in one transaction (idempotent)."""
        source = match.source
        mid = match.match_id

        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO matches
                   (source, match_id, event_id, event_name, stage, date, best_of,
                    team1_id, team2_id, team1_name, team2_name,
                    team1_score, team2_score, winner_team_id, veto_text, url, vlr_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    source, mid, match.event_id, match.event_name, match.stage,
                    match.date.isoformat() if match.date else None,
                    match.best_of,
                    match.team1_id, match.team2_id,
                    match.team1_name, match.team2_name,
                    match.team1_score, match.team2_score,
                    match.winner_team_id, match.veto_text, match.url, match.vlr_id,
                ),
            )

            self.conn.execute(
                "DELETE FROM match_teams WHERE source = ? AND match_id = ?",
                (source, mid),
            )
            for team_id in _match_team_ids(match):
                if team_id is not None:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO match_teams VALUES (?,?,?)",
                        (source, mid, team_id),
                    )

            self.conn.execute(
                "DELETE FROM maps WHERE source = ? AND match_id = ?",
                (source, mid),
            )
            self.conn.execute(
                "DELETE FROM vetoes WHERE source = ? AND match_id = ?",
                (source, mid),
            )
            self.conn.execute(
                "DELETE FROM rounds WHERE source = ? AND match_id = ?",
                (source, mid),
            )
            self.conn.execute(
                "DELETE FROM round_economies WHERE source = ? AND match_id = ?",
                (source, mid),
            )
            self.conn.execute(
                "DELETE FROM player_stats WHERE source = ? AND match_id = ?",
                (source, mid),
            )

            for i, veto in enumerate(match.veto):
                self.conn.execute(
                    """INSERT INTO vetoes
                       (source, match_id, seq, action, team_name, map_name)
                       VALUES (?,?,?,?,?,?)""",
                    (source, mid, i, veto.action.value,
                     veto.team_name, veto.map_name),
                )

            for num, mp in enumerate(match.maps, start=1):
                self._insert_map(source, mid, num, mp)
                for rnd in mp.rounds:
                    self._insert_round(source, mid, num, rnd)
                for ps in mp.players:
                    self._insert_player_stats(source, mid, num, ps)

    def save_team(self, team: Team, source: str = "vlr") -> None:
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO teams
                   (source, team_id, name, region, logo_url) VALUES (?,?,?,?,?)""",
                (source, team.team_id, team.name, team.region, team.logo_url),
            )

    def save_player(self, player: Player, source: str = "vlr") -> None:
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO players
                   (source, player_id, name, handle, real_name, country)
                   VALUES (?,?,?,?,?,?)""",
                (source, player.player_id, player.name, player.handle,
                 player.real_name, player.country),
            )

    def save_event(self, event: EventInfo, source: str = "vlr") -> None:
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO events
                   (source, event_id, name, region, tier,
                    start_date, end_date, prize_pool)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (source, event.event_id, event.name, event.region, event.tier,
                 event.start_date.isoformat() if event.start_date else None,
                 event.end_date.isoformat() if event.end_date else None,
                 event.prize_pool),
            )

    def _insert_map(self, source: str, mid: int, num: int, mp: MapResult) -> None:
        self.conn.execute(
            """INSERT INTO maps
               (source, match_id, map_number, map_id, map_name,
                team1_score, team2_score,
                team1_half1, team1_half2, team2_half1, team2_half2,
                winner_team_id, duration_seconds, picked_by_team_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source, mid, num, mp.map_id, mp.map_name,
             mp.team1_score, mp.team2_score,
             mp.team1_first_half_score, mp.team1_second_half_score,
             mp.team2_first_half_score, mp.team2_second_half_score,
             mp.winner_team_id, mp.duration_seconds, mp.picked_by_team_id),
        )

    def _insert_round(self, source: str, mid: int, map_number: int, rnd: Round) -> None:
        self.conn.execute(
            """INSERT INTO rounds
               (source, match_id, map_number, round_number,
                win_condition, winning_side, winning_team_id, winning_team_name)
               VALUES (?,?,?,?,?,?,?,?)""",
            (source, mid, map_number, rnd.round_number,
             rnd.win_condition.value if rnd.win_condition else None,
             rnd.winning_side.value if rnd.winning_side else None,
             rnd.winning_team_id, rnd.winning_team_name),
        )
        for ec in rnd.economies:
            self.conn.execute(
                """INSERT INTO round_economies
                   (source, match_id, map_number, round_number, team_id,
                    team_name, buy_type, bank_after_buy, credits)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (source, mid, map_number, rnd.round_number, ec.team_id,
                 ec.team_name, ec.buy_type.value if ec.buy_type else None,
                 ec.bank_after_buy, ec.credits),
            )

    def _insert_player_stats(
        self, source: str, mid: int, map_number: int, ps: PlayerMatchStats
    ) -> None:
        self.conn.execute(
            """INSERT INTO player_stats
               (source, match_id, map_number, player_id, player_name,
                team_id, team_name, agent, rating, acs, kills, deaths, assists,
                kast, adr, headshot_pct, first_kills, first_deaths,
                operator_kills, multikills, clutches, clutch_rounds,
                plants, defuses)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source, mid, map_number, ps.player_id, ps.player_name,
             ps.team_id, ps.team_name, ps.agent, ps.rating, ps.acs,
             ps.kills, ps.deaths, ps.assists, ps.kast, ps.adr,
             ps.headshot_pct, ps.first_kills, ps.first_deaths,
             ps.operator_kills,
             json.dumps(ps.multikills),
             json.dumps(ps.clutches_won),
             json.dumps(ps.clutch_rounds),
             ps.plants, ps.defuses),
        )

    # -- JSON export ---------------------------------------------------------

    def dump_match_json(self, match: Match, json_dir: str | Path) -> Path:
        json_dir = Path(json_dir)
        json_dir.mkdir(parents=True, exist_ok=True)
        prefix = "" if match.source == "vlr" else f"{match.source}_"
        out = json_dir / f"{prefix}{match.match_id}.json"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(match.to_dict(), fh, indent=2, ensure_ascii=False)
        return out

    # -- CV pipeline (Component 3) -------------------------------------------

    def upsert_vod(self, vod: Vod) -> None:
        self.conn.execute(
            """
            INSERT INTO vods (match_id, map_number, video_id, url, start_s, duration_s, label)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id, map_number) DO UPDATE SET
                video_id = excluded.video_id,
                url = excluded.url,
                start_s = excluded.start_s,
                duration_s = excluded.duration_s,
                label = excluded.label
            """,
            (vod.match_id, vod.map_number, vod.video_id, vod.url, vod.start_s,
             vod.duration_s, vod.label),
        )
        self.conn.commit()

    def save_vods(self, vods: Iterable[Vod]) -> int:
        rows = list(vods)
        for vod in rows:
            self.upsert_vod(vod)
        return len(rows)

    def get_vods(self, match_id: int) -> list[Vod]:
        cur = self.conn.execute(
            "SELECT * FROM vods WHERE match_id = ? ORDER BY map_number", (match_id,)
        )
        return [self._vod_from_row(r) for r in cur.fetchall()]

    @staticmethod
    def _vod_from_row(row: sqlite3.Row) -> Vod:
        return Vod(
            match_id=row["match_id"],
            map_number=row["map_number"],
            url=row["url"],
            video_id=row["video_id"],
            start_s=row["start_s"],
            duration_s=row["duration_s"],
            label=row["label"],
        )

    def insert_tick(self, *, match_id: int, map_number: int, round_number: int,
                    ms_into_round: int, frame_index: int, pts_s: float,
                    players: Iterable[PlayerState],
                    utilities: Iterable[UtilityState],
                    spike: Optional[SpikeState] = None) -> None:
        for i, p in enumerate(players):
            self.conn.execute(
                """
                INSERT OR REPLACE INTO tick_players
                (source, match_id, map_number, round_number, ms_into_round,
                 frame_index, row_idx, pts_s, team, side, agent, track_id, x_px, y_px, world_x, world_y)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (CV_SOURCE, match_id, map_number, round_number, ms_into_round,
                 frame_index, i, pts_s, p.team, p.side, p.agent, p.track_id, p.x_px,
                 p.y_px, p.world_x, p.world_y),
            )
        for i, u in enumerate(utilities):
            self.conn.execute(
                """
                INSERT OR REPLACE INTO tick_utilities
                (source, match_id, map_number, round_number, ms_into_round,
                 frame_index, row_idx, pts_s, kind, x_px, y_px, world_x, world_y)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (CV_SOURCE, match_id, map_number, round_number, ms_into_round,
                 frame_index, i, pts_s, u.kind, u.x_px, u.y_px, u.world_x, u.world_y),
            )
        if spike is not None:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO tick_spike
                (source, match_id, map_number, round_number, ms_into_round,
                 frame_index, pts_s, present, x_px, y_px, world_x, world_y)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (CV_SOURCE, match_id, map_number, round_number, ms_into_round,
                 frame_index, pts_s, int(spike.present), spike.x_px, spike.y_px,
                 spike.world_x, spike.world_y),
            )
        self.conn.commit()

    def count_ticks(self, match_id: int, map_number: int) -> tuple[int, int, int]:
        cur = self.conn.execute(
            "SELECT COUNT(*) n FROM tick_players WHERE match_id=? AND map_number=? AND source=?",
            (match_id, map_number, CV_SOURCE),
        )
        players = cur.fetchone()["n"]
        cur = self.conn.execute(
            "SELECT COUNT(*) n FROM tick_utilities WHERE match_id=? AND map_number=? AND source=?",
            (match_id, map_number, CV_SOURCE),
        )
        utilities = cur.fetchone()["n"]
        cur = self.conn.execute(
            "SELECT COUNT(*) n FROM tick_spike WHERE match_id=? AND map_number=? AND source=?",
            (match_id, map_number, CV_SOURCE),
        )
        spike = cur.fetchone()["n"]
        return players, utilities, spike

    def upsert_label(self, *, match_id: int, map_number: int, frame_index: int,
                     kind: str, x_px: float, y_px: float, w_px: float | None = None,
                     h_px: float | None = None, source: str = "manual") -> None:
        self.conn.execute(
            """
            DELETE FROM labels WHERE match_id=? AND map_number=?
                AND frame_index=? AND kind=?
            """,
            (match_id, map_number, frame_index, kind),
        )
        self.conn.execute(
            """
            INSERT INTO labels
                (match_id, map_number, frame_index, kind, x_px, y_px, w_px, h_px, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (match_id, map_number, frame_index, kind, x_px, y_px, w_px, h_px, source),
        )
        self.conn.commit()

    def get_labels(self, match_id: int, map_number: int,
                   kind: str | None = None) -> list[sqlite3.Row]:
        sql = ("SELECT * FROM labels WHERE match_id=? AND map_number=?")
        args: list = [match_id, map_number]
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        return self.conn.execute(sql + " ORDER BY frame_index", args).fetchall()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _match_team_ids(match: Match) -> Iterable[int]:
    yield match.team1_id
    yield match.team2_id


# Alias for CV pipeline compatibility
Storage = Repository
