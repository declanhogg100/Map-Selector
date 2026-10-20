import sys
import pickle
import requests
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from features import build_team_features


HEADERS = {"Authorization": f"Bearer {API_KEY}"}
MAX_WORKERS = 5

MAPS = ["de_mirage", "de_dust2", "de_ancient", "de_inferno", "de_anubis", "de_nuke", "de_cache", "de_overpass"]

# Maps API label format to our training format
MAP_LABEL = {
    "Mirage": "de_mirage",
    "Dust2": "de_dust2",
    "Ancient": "de_ancient",
    "Inferno": "de_inferno",
    "Anubis": "de_anubis",
    "Nuke": "de_nuke",
    "Cache": "de_cache",
    "Overpass": "de_overpass",
}


def fetch_player_elo(player_id):
    """Fetches current ELO directly from the API, bypassing the local DB."""
    response = requests.get(
        f"https://open.faceit.com/data/v4/players/{player_id}",
        headers=HEADERS,
        timeout=10
    )
    if response.status_code != 200:
        return None
    return response.json().get("games", {}).get("cs2", {}).get("faceit_elo")


def fetch_player_stats(player_id):
    """
    Fetches a player's lifetime stats per map from the FACEIT API.
    Returns a dict keyed by our map name (e.g. "de_mirage") with
    the same stat format that build_team_features expects.
    """
    response = requests.get(
        f"https://open.faceit.com/data/v4/players/{player_id}/stats/cs2",
        headers=HEADERS,
        timeout=10
    )
    if response.status_code != 200:
        return {}

    segments = response.json().get("segments", [])
    result = {}

    for seg in segments:
        if seg.get("type") != "Map":
            continue

        api_label = seg.get("label", "")
        map_name = MAP_LABEL.get(api_label)
        if not map_name:
            continue

        s = seg.get("stats", {})

        def f(key):
            val = s.get(key)
            return float(val) if val is not None else None

        result[map_name] = {
            "avg_kd":               f("Average K/D Ratio"),
            "avg_adr":              f("ADR"),
            "avg_hs_pct":           f("Average Headshots %"),
            "avg_entry_rate":       f("Entry Rate"),
            "avg_entry_success":    f("Entry Success Rate"),
            "avg_clutch_1v1":       f("1v1 Win Rate"),
            "avg_clutch_1v2":       f("1v2 Win Rate"),
            "avg_enemies_flashed":  f("Enemies Flashed per Round"),
            "avg_utility_success":  f("Utility Success Rate"),
            "avg_utility_count":    f("Utility Usage per Round"),
            "avg_sniper_kpr":       f("Sniper Kill Rate per Round"),
            # Win Rate % comes as e.g. "55" — divide by 100 to match training format
            "map_win_rate":         f("Win Rate %") / 100 if f("Win Rate %") is not None else None,
            "map_games_played":     int(f("Matches")) if f("Matches") is not None else 0,
        }

    return result


def get_match_data(match_id):
    response = requests.get(
        f"https://open.faceit.com/data/v4/matches/{match_id}",
        headers=HEADERS,
        timeout=10
    )
    if response.status_code != 200:
        print(f"Failed to fetch match {match_id}: {response.status_code}")
        sys.exit(1)
    return response.json()


def get_match_players(match_data, my_player_id):
    teams = match_data.get("teams", {})
    team1_players = [p["player_id"] for p in teams.get("faction1", {}).get("roster", [])]
    team2_players = [p["player_id"] for p in teams.get("faction2", {}).get("roster", [])]
    my_team = "team1" if my_player_id in team1_players else "team2"
    return team1_players, team2_players, my_team


def build_prediction_features(team1_players, team2_players, all_stats, all_elos):
    """
    Builds a feature row for a single map using pre-fetched player stats.
    all_stats is a dict of player_id -> map_name -> stat dict.
    all_elos is a dict of player_id -> elo (fetched live from API).
    """
    predictions = {}

    for map_name in MAPS:
        team1_map_stats = [
            all_stats[pid][map_name]
            for pid in team1_players
            if pid in all_stats and map_name in all_stats[pid]
        ]
        team2_map_stats = [
            all_stats[pid][map_name]
            for pid in team2_players
            if pid in all_stats and map_name in all_stats[pid]
        ]

        if not team1_map_stats or not team2_map_stats:
            predictions[map_name] = None
            continue

        row = {}
        row.update(build_team_features(team1_map_stats, "t1_"))
        row.update(build_team_features(team2_map_stats, "t2_"))

        for stat in ["avg_map_win_rate", "avg_hs_pct", "kd_std", "win_rate_std"]:
            t1_val = row.get(f"t1_{stat}")
            t2_val = row.get(f"t2_{stat}")
            row[f"diff_{stat}"] = (t1_val - t2_val) if (t1_val is not None and t2_val is not None) else None

        # ELO features — use live-fetched ELO, skip zeros and None
        team1_elos = sorted([e for pid in team1_players if (e := all_elos.get(pid)) and e > 0], reverse=True)
        team2_elos = sorted([e for pid in team2_players if (e := all_elos.get(pid)) and e > 0], reverse=True)

        for i, elo in enumerate(team1_elos):
            row[f"t1_elo_rank{i}"] = elo
        for i, elo in enumerate(team2_elos):
            row[f"t2_elo_rank{i}"] = elo

        t1_avg_elo = sum(team1_elos) / len(team1_elos) if team1_elos else None
        t2_avg_elo = sum(team2_elos) / len(team2_elos) if team2_elos else None
        row["t1_avg_elo"] = t1_avg_elo
        row["t2_avg_elo"] = t2_avg_elo
        row["diff_avg_elo"] = (t1_avg_elo - t2_avg_elo) if (t1_avg_elo and t2_avg_elo) else None

        predictions[map_name] = row

    return predictions


def predict(match_id, my_player_id, models):
    print(f"Fetching match {match_id}...")
    match_data = get_match_data(match_id)
    team1_players, team2_players, my_team = get_match_players(match_data, my_player_id)
    all_player_ids = team1_players + team2_players

    print(f"You are on: {my_team}")
    print(f"Fetching stats for {len(all_player_ids)} players in parallel...")

    # Fetch all 10 players' stats and ELO in parallel
    all_stats = {}
    all_elos = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        stat_futures = {executor.submit(fetch_player_stats, pid): pid for pid in all_player_ids}
        elo_futures = {executor.submit(fetch_player_elo, pid): pid for pid in all_player_ids}

        for future in as_completed(stat_futures):
            pid = stat_futures[future]
            try:
                all_stats[pid] = future.result()
            except Exception as e:
                print(f"  Failed to fetch stats for {pid}: {e}")
                all_stats[pid] = {}

        for future in as_completed(elo_futures):
            pid = elo_futures[future]
            try:
                all_elos[pid] = future.result()
            except Exception as e:
                all_elos[pid] = None

    # Print ELO summary so we can verify the calculation looks right
    print("ELOs fetched:")
    t1_elos = [all_elos.get(pid) for pid in team1_players]
    t2_elos = [all_elos.get(pid) for pid in team2_players]
    print(f"  Team 1: {t1_elos} → avg {sum(e for e in t1_elos if e and e > 0) / max(sum(1 for e in t1_elos if e and e > 0), 1):.0f}")
    print(f"  Team 2: {t2_elos} → avg {sum(e for e in t2_elos if e and e > 0) / max(sum(1 for e in t2_elos if e and e > 0), 1):.0f}")
    print(f"  You are on: {my_team}\n")

    print("Building features and predicting...\n")
    feature_rows = build_prediction_features(team1_players, team2_players, all_stats, all_elos)

    results = {}
    for map_name, row in feature_rows.items():
        if row is None or map_name not in models:
            continue

        model_data = models[map_name]
        model = model_data["model"]
        feature_cols = model_data["features"]

        X = pd.DataFrame([row])
        for col in feature_cols:
            if col not in X.columns:
                X[col] = None
        X = X[feature_cols].apply(pd.to_numeric, errors="coerce")

        # Fill nulls with 0 — with the stats API most values will be present
        X = X.fillna(0)

        prob_team1_wins = model.predict_proba(X)[0][1]
        my_win_prob = prob_team1_wins if my_team == "team1" else 1 - prob_team1_wins
        results[map_name] = my_win_prob

    sorted_maps = sorted(results.items(), key=lambda x: x[1], reverse=True)

    print("=" * 45)
    print("  MAP WIN PROBABILITIES (your team)")
    print("=" * 45)
    for map_name, prob in sorted_maps:
        bar = "█" * int(prob * 20)
        print(f"  {map_name:<20} {prob*100:5.1f}%  {bar}")
    print("=" * 45)
    print(f"\n  BAN FIRST: {sorted_maps[-1][0]} ({sorted_maps[-1][1]*100:.1f}%)")
    print(f"  PICK:      {sorted_maps[0][0]} ({sorted_maps[0][1]*100:.1f}%)")


if __name__ == "__main__":
    MY_PLAYER_ID = "18ed6f43-0f27-4a76-9e2d-9c47932c1367"

    print("Loading models...")
    with open("models.pkl", "rb") as f:
        models = pickle.load(f)

    if len(sys.argv) > 1:
        predict(sys.argv[1], MY_PLAYER_ID, models)
    else:
        print("Usage: python3 predict.py <match_id>")
        print("Get your match ID from the FACEIT room URL.")
