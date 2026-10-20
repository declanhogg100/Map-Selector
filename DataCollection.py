import sqlite3
import requests
import time
from datetime import datetime


headers = {"Authorization": "Bearer 94412712-86f5-4f59-97ac-74b9ed717a29"}

def get_db():
    conn = sqlite3.connect("faceit_data.db")
    conn.row_factory = sqlite3.Row
    return conn

def get_or_fetch_player(player_id, cursor, conn):
    """
    Now takes an existing cursor and conn instead of opening its own
    so we don't have two connections open at the same time
    """
    cursor.execute("SELECT * FROM players WHERE player_id = ?", (player_id,))
    player = cursor.fetchone()

    if player:
        return player

    response = requests.get(
        f"https://open.faceit.com/data/v4/players/{player_id}",
        headers=headers,
        timeout=10
    )
    data = response.json()
    time.sleep(0.5)

    elo = data.get("games", {}).get("cs2", {}).get("faceit_elo", 0)
    level = data.get("games", {}).get("cs2", {}).get("skill_level", 0)

    cursor.execute("""
        INSERT OR IGNORE INTO players (player_id, nickname, faceit_elo, skill_level, last_updated)
        VALUES (?, ?, ?, ?, ?)
    """, (player_id, data.get("nickname"), elo, level, datetime.now().isoformat()))

    conn.commit()
    return data

def process_match(match_id):
    """
    Takes a match ID, fetches the full stats from the FACEIT API,
    and saves the match and all 10 players' stats to the database.
    Skips silently if the match is already in the database.
    """
    conn = get_db()
    cursor = conn.cursor()

    # Skip if already collected
    cursor.execute("SELECT match_id FROM matches WHERE match_id = ?", (match_id,))
    if cursor.fetchone():
        conn.close()
        return

    meta_response = requests.get(
        f"https://open.faceit.com/data/v4/matches/{match_id}",
        headers=headers,
        timeout=10
    )
    time.sleep(0.5)

    if meta_response.status_code != 200:
        conn.close()
        return

    date = meta_response.json().get("started_at", 0)

    response = requests.get(
        f"https://open.faceit.com/data/v4/matches/{match_id}/stats",
        headers=headers,
        timeout=10
    )
    time.sleep(0.5)

    if response.status_code != 200:
        conn.close()
        return

    data = response.json()
    rounds = data.get("rounds")
    if not rounds:
        conn.close()
        return

    round_data = rounds[0]
    round_stats = round_data.get("round_stats", {})
    teams = round_data.get("teams", [])

    if len(teams) < 2:
        conn.close()
        return

    map_name = round_stats.get("Map")
    winning_team = round_stats.get("Winner")
    team1_id = teams[0].get("team_id")
    team2_id = teams[1].get("team_id")

    cursor.execute("""
        INSERT OR IGNORE INTO matches (match_id, map, winning_team, team1_id, team2_id, date)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (match_id, map_name, winning_team, team1_id, team2_id, date))

    # Loop through both teams and save each player's stats
    for team in teams:
        team_id = team.get("team_id")
        for player in team.get("players", []):
            player_id = player.get("player_id")
            stats = player.get("player_stats", {})

            kd = float(stats.get("K/D Ratio", 0))
            adr = float(stats.get("ADR", 0))
            hs_pct = float(stats.get("Headshots %", 0))
            entry_rate = float(stats.get("Match Entry Rate", 0))
            entry_success = float(stats.get("Match Entry Success Rate", 0))
            clutch_1v1 = float(stats.get("Match 1v1 Win Rate", 0))
            clutch_1v2 = float(stats.get("Match 1v2 Win Rate", 0))
            enemies_flashed = float(stats.get("Enemies Flashed per Round in a Match", 0))
            utility_success = float(stats.get("Utility Success Rate per Match", 0))
            utility_count = float(stats.get("Utility Usage per Round", 0))
            sniper_kpr = float(stats.get("Sniper Kill Rate per Round", 0))
            result = int(stats.get("Result", 0))

            # Make sure this player exists in the players table
            get_or_fetch_player(player_id, cursor, conn)

            cursor.execute("""
                INSERT OR IGNORE INTO player_match_stats (
                    match_id, player_id, team, kd_ratio, adr, headshot_pct,
                    entry_rate, entry_success_rate, clutch_1v1_rate, clutch_1v2_rate,
                    enemies_flashed_per_round, utility_success_rate,
                    utility_count_per_round, sniper_kills_per_round, result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (match_id, player_id, team_id, kd, adr, hs_pct, entry_rate,
                  entry_success, clutch_1v1, clutch_1v2, enemies_flashed,
                  utility_success, utility_count, sniper_kpr, result))

    conn.commit()
    conn.close()

def collect_matches(starting_player_id, num_matches=100):
    """
    Entry point for initial data collection.
    Fetches match history for a starting player and processes each match.
    """
    response = requests.get(
        f"https://open.faceit.com/data/v4/players/{starting_player_id}/history",
        params={"game": "cs2", "limit": 100},
        headers=headers
    )
    matches = response.json().get("items", [])
    time.sleep(0.5)

    for i, match in enumerate(matches[:num_matches]):
        match_id = match.get("match_id")
        print(f"Processing match {i+1}/{num_matches}: {match_id}")
        process_match(match_id)

if __name__ == "__main__":
    collect_matches("18ed6f43-0f27-4a76-9e2d-9c47932c1367", num_matches=5)
