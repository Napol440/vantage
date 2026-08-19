"""Import detection results into SQLite tick_players table."""
import sys, json
sys.path.insert(0, 'src')

from pathlib import Path
from vantage.storage import Storage
from vantage.models import PlayerState

DB_PATH = Path("data/vantage.db")
DETECTIONS = Path("twitch_data/detections_full.json")
MATCH_ID = 730541
MAP_NUMBER = 1
SOURCE = "cv"

print("Loading detections...")
with open(DETECTIONS) as f:
    results = json.load(f)
print(f"Loaded {len(results)} frames")

print("Connecting to DB...")
store = Storage(DB_PATH)

count = 0
for entry in results:
    frame_idx = entry['frame']
    pts_s = entry['pts_s']

    # We don't have round info yet, use round 0
    round_number = 0
    ms_into_round = int(pts_s * 1000)

    players = []
    for d in entry.get('positions', {}).get('ally', []):
        players.append(PlayerState(
            match_id=MATCH_ID, map_number=MAP_NUMBER,
            round_number=round_number, ms_into_round=ms_into_round,
            frame_index=frame_idx,
            team='ally', side='', agent=None, track_id=None,
            x_px=d['x'], y_px=d['y'], world_x=None, world_y=None
        ))
    for d in entry.get('positions', {}).get('enemy', []):
        players.append(PlayerState(
            match_id=MATCH_ID, map_number=MAP_NUMBER,
            round_number=round_number, ms_into_round=ms_into_round,
            frame_index=frame_idx,
            team='enemy', side='', agent=None, track_id=None,
            x_px=d['x'], y_px=d['y'], world_x=None, world_y=None
        ))

    if players:
        store.insert_tick(
            match_id=MATCH_ID,
            map_number=MAP_NUMBER,
            round_number=round_number,
            ms_into_round=ms_into_round,
            frame_index=frame_idx,
            pts_s=pts_s,
            players=players,
            utilities=[],
        )
        count += 1

print(f"\nInserted {count} ticks with players")
n_players, n_utils, n_spike = store.count_ticks(MATCH_ID, MAP_NUMBER)
print(f"DB now has: {n_players} player ticks, {n_utils} utility ticks, {n_spike} spike ticks")
