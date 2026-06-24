import sqlite3
import requests
import time
from DataCollection import process_match, get_or_fetch_player, headers

def get_db():
    conn = sqlite3.connect("faceit_data.db")
    conn.row_factory = sqlite3.Row
    return conn

def get_player_match_history(player_id, limit=50):
    """
    Fetches a player's match history from the FACEIT API.
    Returns a list of match IDs.
    """
    response = requests.get(
        f"https://open.faceit.com/data/v4/players/{player_id}/history",
        params={"game": "cs2", "limit": limit},
        headers=headers,
        timeout=10
    )
    time.sleep(0.5)

    if response.status_code != 200:
        return []

    # status_code tells you if the API call succeeded
    # 200 means success, anything else means something went wrong
    # returning an empty list means we just skip this player and move on
    # rather than crashing the whole script

    items = response.json().get("items", [])
    return [match["match_id"] for match in items]

def get_players_from_matches(starting_player_id):
    """
    Returns the frozen snapshot of seed players minus those already collected.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT player_id FROM seed_players")
    seed_players = set(row["player_id"] for row in cursor.fetchall())

    cursor.execute("SELECT player_id FROM snowball_progress")
    already_collected = set(row["player_id"] for row in cursor.fetchall())

    conn.close()

    return seed_players - already_collected

def mark_player_collected(player_id):
    """
    Records that we've already collected match history for this player
    so we don't fetch them again if the script restarts
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO snowball_progress (player_id) VALUES (?)
    """, (player_id,))
    conn.commit()
    conn.close()

def snowball(starting_player_id, matches_per_player=50):
    """
    Main snowball loop:
    1. Start with your own matches
    2. Find all new players from those matches
    3. Fetch their match histories
    4. Repeat until you have enough data
    """
    conn = get_db()
    cursor = conn.cursor()

    # We need a new table to track which players we've already
    # collected history for -- without this restarting the script
    # would re-fetch everyone from scratch
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS snowball_progress (
            player_id TEXT PRIMARY KEY
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seed_players (
            player_id TEXT PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()

    # Phase 1 -- collect your own matches first if not already done
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT player_id FROM snowball_progress WHERE player_id = ?", (starting_player_id,))
    already_done = cursor.fetchone()
    conn.close()

    if not already_done:
        print("Collecting matches for starting player...")
        starting_matches = get_player_match_history(starting_player_id, limit=100)
        for i, match_id in enumerate(starting_matches):
            print(f"Processing starting player match {i+1}/{len(starting_matches)}")
            process_match(match_id)
        mark_player_collected(starting_player_id)

        # Snapshot seed players now, before phase 2 adds more matches
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO seed_players
            SELECT DISTINCT pms2.player_id
            FROM player_match_stats pms1
            JOIN player_match_stats pms2 ON pms1.match_id = pms2.match_id
            WHERE pms1.player_id = ?
            AND pms2.player_id != ?
        """, (starting_player_id, starting_player_id))
        conn.commit()
        conn.close()
        print(f"Snapshotted seed players")
    else:
        print("Starting player already collected, skipping phase 1")

    # Phase 2 -- snowball outward one level only
    # collect history for all players seen in the starting matches,
    # but don't expand further from the new matches those players introduce
    new_players = get_players_from_matches(starting_player_id)
    print(f"{len(new_players)} new players to collect history for")

    for i, player_id in enumerate(new_players):
        print(f"Collecting player {i+1}/{len(new_players)}: {player_id}")

        try:
            match_ids = get_player_match_history(player_id, limit=matches_per_player)
            for match_id in match_ids:
                process_match(match_id)
        except Exception as e:
            print(f"Error on player {player_id}, skipping: {e}")

        # Mark this player as done immediately after collecting
        # so if the script crashes halfway through we don't redo them
        mark_player_collected(player_id)

        # Print progress every 10 players so you can monitor
        if (i + 1) % 10 == 0:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM matches")
            total = cursor.fetchone()["count"]
            conn.close()
            print(f"Total matches in database so far: {total}")

    print("Snowball complete")

# Replace with your own player ID
snowball("18ed6f43-0f27-4a76-9e2d-9c47932c1367", matches_per_player=50)