import sqlite3
import requests
import time
import pandas as pd


headers = {"Authorization": "Bearer 94412712-86f5-4f59-97ac-74b9ed717a29"}

def get_db():
    conn = sqlite3.connect("faceit_data.db")
    conn.row_factory = sqlite3.Row
    return conn

def fetch_and_save_player_history(player_id, limit=50):
    """
    Fetches a player's match history from the API and saves it to the database.
    Called automatically when a player isn't found in the database.
    Imported here locally to avoid circular imports between files
    -- collect_data imports from database, features imports from collect_data,
    so we keep the import inside the function rather than at the top of the file
    to prevent any import chain issues
    """
    from DataCollection import process_match

    print(f"Player {player_id} not in database -- fetching from API...")
    response = requests.get(
        f"https://open.faceit.com/data/v4/players/{player_id}/history",
        params={"game": "cs2", "limit": limit},
        headers=headers
    )
    time.sleep(0.5)

    if response.status_code != 200:
        print(f"Failed to fetch history for {player_id} -- skipping")
        return

    matches = response.json().get("items", [])
    for match in matches:
        process_match(match["match_id"])
    print(f"Saved {len(matches)} matches for player {player_id}")

def get_player_elo(player_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT faceit_elo FROM players WHERE player_id = ?", (player_id,))
    row = cursor.fetchone()
    conn.close()
    return row["faceit_elo"] if row else None

def get_player_map_stats(player_id, target_date, map_name, min_games=5, no_fetch=False):
    """
    Fetches a player's averaged stats on a specific map before a given date.
    Falls back to the API if the player isn't in the database.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT pms.* FROM player_match_stats pms
        JOIN matches m ON pms.match_id = m.match_id
        WHERE pms.player_id = ?
        AND m.date < ?
        AND m.map = ?
        ORDER BY m.date DESC
        LIMIT 15
    """, (player_id, target_date, map_name))
    map_stats = cursor.fetchall()
    conn.close()

    # If no data found at all, check if the player exists in the database
    # at all -- if not, fetch their history from the API then retry
    if len(map_stats) == 0:
        if no_fetch:
            return {
                "avg_kd": None, "avg_adr": None, "avg_hs_pct": None,
                "avg_entry_rate": None, "avg_entry_success": None,
                "avg_clutch_1v1": None, "avg_clutch_1v2": None,
                "avg_enemies_flashed": None, "avg_utility_success": None,
                "avg_utility_count": None, "avg_sniper_kpr": None,
                "map_win_rate": None, "map_games_played": 0
            }

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT player_id FROM players WHERE player_id = ?", (player_id,))
        player_exists = cursor.fetchone()
        conn.close()

        if not player_exists:
            # Player not in database at all -- fetch from API and retry
            fetch_and_save_player_history(player_id)

            # Retry the map stats query now that we have their history
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pms.* FROM player_match_stats pms
                JOIN matches m ON pms.match_id = m.match_id
                WHERE pms.player_id = ?
                AND m.date < ?
                AND m.map = ?
                ORDER BY m.date DESC
                LIMIT 15
            """, (player_id, target_date, map_name))
            map_stats = cursor.fetchall()
            conn.close()

    # No data even after API fetch -- return all None
    # this handles the case where a player genuinely has no history
    # on this map even after fetching their full history
    if len(map_stats) == 0:
        return {
            "avg_kd": None, "avg_adr": None, "avg_hs_pct": None,
            "avg_entry_rate": None, "avg_entry_success": None,
            "avg_clutch_1v1": None, "avg_clutch_1v2": None,
            "avg_enemies_flashed": None, "avg_utility_success": None,
            "avg_utility_count": None, "avg_sniper_kpr": None,
            "map_win_rate": None, "map_games_played": 0
        }

    if len(map_stats) < min_games:
        # Small sample -- check if player exists overall and blend with overall stats
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pms.* FROM player_match_stats pms
            JOIN matches m ON pms.match_id = m.match_id
            WHERE pms.player_id = ?
            AND m.date < ?
            ORDER BY m.date DESC
            LIMIT 20
        """, (player_id, target_date))
        overall_stats = cursor.fetchall()
        conn.close()

        map_weight = len(map_stats) / min_games
        overall_weight = 1 - map_weight

        def blend(col):
            map_avg = sum(row[col] for row in map_stats) / len(map_stats)
            overall_avg = sum(row[col] for row in overall_stats) / len(overall_stats) if overall_stats else map_avg
            return (map_avg * map_weight) + (overall_avg * overall_weight)

        return {
            "avg_kd": blend("kd_ratio"),
            "avg_adr": blend("adr"),
            "avg_hs_pct": blend("headshot_pct"),
            "avg_entry_rate": blend("entry_rate"),
            "avg_entry_success": blend("entry_success_rate"),
            "avg_clutch_1v1": blend("clutch_1v1_rate"),
            "avg_clutch_1v2": blend("clutch_1v2_rate"),
            "avg_enemies_flashed": blend("enemies_flashed_per_round"),
            "avg_utility_success": blend("utility_success_rate"),
            "avg_utility_count": blend("utility_count_per_round"),
            "avg_sniper_kpr": blend("sniper_kills_per_round"),
            "map_win_rate": sum(row["result"] for row in map_stats) / len(map_stats),
            "map_games_played": len(map_stats)
        }

    return {
        "avg_kd": sum(row["kd_ratio"] for row in map_stats) / len(map_stats),
        "avg_adr": sum(row["adr"] for row in map_stats) / len(map_stats),
        "avg_hs_pct": sum(row["headshot_pct"] for row in map_stats) / len(map_stats),
        "avg_entry_rate": sum(row["entry_rate"] for row in map_stats) / len(map_stats),
        "avg_entry_success": sum(row["entry_success_rate"] for row in map_stats) / len(map_stats),
        "avg_clutch_1v1": sum(row["clutch_1v1_rate"] for row in map_stats) / len(map_stats),
        "avg_clutch_1v2": sum(row["clutch_1v2_rate"] for row in map_stats) / len(map_stats),
        "avg_enemies_flashed": sum(row["enemies_flashed_per_round"] for row in map_stats) / len(map_stats),
        "avg_utility_success": sum(row["utility_success_rate"] for row in map_stats) / len(map_stats),
        "avg_utility_count": sum(row["utility_count_per_round"] for row in map_stats) / len(map_stats),
        "avg_sniper_kpr": sum(row["sniper_kills_per_round"] for row in map_stats) / len(map_stats),
        "map_win_rate": sum(row["result"] for row in map_stats) / len(map_stats),
        "map_games_played": len(map_stats)
    }


def build_team_features(player_stats_list, prefix):
    row = {}

    def sort_by(stat):
        return sorted(player_stats_list, key=lambda p: p[stat] or 0, reverse=True)

    by_kd = sort_by("avg_kd")
    for i, player in enumerate(by_kd):
        row[f"{prefix}kd_rank{i}"] = player["avg_kd"]
        row[f"{prefix}adr_rank{i}"] = player["avg_adr"]

    by_entry = sort_by("avg_entry_rate")
    for i, player in enumerate(by_entry):
        row[f"{prefix}entry_rate_rank{i}"] = player["avg_entry_rate"]
        row[f"{prefix}entry_success_rank{i}"] = player["avg_entry_success"]

    by_sniper = sort_by("avg_sniper_kpr")
    for i, player in enumerate(by_sniper):
        row[f"{prefix}sniper_kpr_rank{i}"] = player["avg_sniper_kpr"]

    by_flash = sort_by("avg_enemies_flashed")
    for i, player in enumerate(by_flash):
        row[f"{prefix}flash_rank{i}"] = player["avg_enemies_flashed"]

    by_clutch = sort_by("avg_clutch_1v1")
    for i, player in enumerate(by_clutch):
        row[f"{prefix}clutch_1v1_rank{i}"] = player["avg_clutch_1v1"]
        row[f"{prefix}clutch_1v2_rank{i}"] = player["avg_clutch_1v2"]

    by_utility = sort_by("avg_utility_success")
    for i, player in enumerate(by_utility):
        row[f"{prefix}utility_success_rank{i}"] = player["avg_utility_success"]
        row[f"{prefix}utility_count_rank{i}"] = player["avg_utility_count"]

    def safe_avg(stat):
        vals = [p[stat] for p in player_stats_list if p[stat] is not None]
        return sum(vals) / len(vals) if vals else None

    def safe_std(stat):
        vals = [p[stat] for p in player_stats_list if p[stat] is not None]
        if len(vals) < 2:
            return None
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        return variance ** 0.5

    row[f"{prefix}avg_map_win_rate"] = safe_avg("map_win_rate")
    row[f"{prefix}avg_hs_pct"] = safe_avg("avg_hs_pct")
    row[f"{prefix}kd_std"] = safe_std("avg_kd")
    row[f"{prefix}win_rate_std"] = safe_std("map_win_rate")

    return row


def build_match_features(match_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM matches WHERE match_id = ?", (match_id,))
    match = cursor.fetchone()
    if not match:
        conn.close()
        return None

    map_name = match["map"]
    target_date = match["date"]
    winning_team = match["winning_team"]
    team1_id = match["team1_id"]
    team2_id = match["team2_id"]

    cursor.execute("""
        SELECT player_id, team FROM player_match_stats
        WHERE match_id = ?
    """, (match_id,))
    players = cursor.fetchall()
    conn.close()

    team1_players = [p["player_id"] for p in players if p["team"] == team1_id]
    team2_players = [p["player_id"] for p in players if p["team"] == team2_id]

    if len(team1_players) == 0 or len(team2_players) == 0:
        return None

    team1_stats = [get_player_map_stats(pid, target_date, map_name) for pid in team1_players]
    team2_stats = [get_player_map_stats(pid, target_date, map_name) for pid in team2_players]

    row = {}
    row.update(build_team_features(team1_stats, "t1_"))
    row.update(build_team_features(team2_stats, "t2_"))

    for stat in ["avg_map_win_rate", "avg_hs_pct", "kd_std", "win_rate_std"]:
        t1_val = row.get(f"t1_{stat}")
        t2_val = row.get(f"t2_{stat}")
        if t1_val is not None and t2_val is not None:
            row[f"diff_{stat}"] = t1_val - t2_val
        else:
            row[f"diff_{stat}"] = None

    # ELO features
    team1_elos = sorted([e for pid in team1_players if (e := get_player_elo(pid)) is not None], reverse=True)
    team2_elos = sorted([e for pid in team2_players if (e := get_player_elo(pid)) is not None], reverse=True)

    for i, elo in enumerate(team1_elos):
        row[f"t1_elo_rank{i}"] = elo
    for i, elo in enumerate(team2_elos):
        row[f"t2_elo_rank{i}"] = elo

    t1_avg_elo = sum(team1_elos) / len(team1_elos) if team1_elos else None
    t2_avg_elo = sum(team2_elos) / len(team2_elos) if team2_elos else None
    row["t1_avg_elo"] = t1_avg_elo
    row["t2_avg_elo"] = t2_avg_elo
    row["diff_avg_elo"] = (t1_avg_elo - t2_avg_elo) if (t1_avg_elo and t2_avg_elo) else None

    row["label"] = 1 if winning_team == team1_id else 0
    row["match_id"] = match_id
    row["map"] = map_name

    return row


def build_training_dataset():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT match_id FROM matches")
    all_matches = cursor.fetchall()
    conn.close()

    rows = []
    for i, match in enumerate(all_matches):
        print(f"Building features for match {i+1}/{len(all_matches)}")
        row = build_match_features(match["match_id"])
        if row:
            rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv("training_data.csv", index=False)
    print(f"Done -- {len(df)} matches processed")
    print(df.head())
    return df
if __name__ == "__main__":
    build_training_dataset()
