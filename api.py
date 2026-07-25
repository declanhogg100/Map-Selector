import pickle
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor, as_completed

from predict import (
    fetch_player_stats,
    fetch_player_elo,
    get_match_data,
    get_match_players,
    build_prediction_features,
    MAPS,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

print("Loading models...")
with open("models.pkl", "rb") as f:
    MODELS = pickle.load(f)
print("Models loaded.")

MAX_WORKERS = 5


class PredictRequest(BaseModel):
    match_id: str
    my_player_id: str


@app.post("/predict")
def predict(req: PredictRequest):
    try:
        match_data = get_match_data(req.match_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Match not found")

    team1_players, team2_players, my_team = get_match_players(match_data, req.my_player_id)
    all_player_ids = team1_players + team2_players

    all_stats = {}
    all_elos = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        stat_futures = {executor.submit(fetch_player_stats, pid): pid for pid in all_player_ids}
        elo_futures = {executor.submit(fetch_player_elo, pid): pid for pid in all_player_ids}

        for future in as_completed(stat_futures):
            pid = stat_futures[future]
            try:
                all_stats[pid] = future.result()
            except Exception:
                all_stats[pid] = {}

        for future in as_completed(elo_futures):
            pid = elo_futures[future]
            try:
                all_elos[pid] = future.result()
            except Exception:
                all_elos[pid] = None

    feature_rows = build_prediction_features(team1_players, team2_players, all_stats, all_elos)

    results = []
    for map_name, row in feature_rows.items():
        if row is None or map_name not in MODELS:
            continue

        model_data = MODELS[map_name]
        feature_cols = model_data["features"]

        X = pd.DataFrame([row])
        for col in feature_cols:
            if col not in X.columns:
                X[col] = None
        X = X[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

        prob_team1_wins = float(model_data["model"].predict_proba(X)[0][1])
        my_win_prob = prob_team1_wins if my_team == "team1" else 1 - prob_team1_wins

        results.append({
            "map": map_name,
            "win_probability": round(my_win_prob, 4),
        })

    results.sort(key=lambda x: x["win_probability"], reverse=True)

    return {
        "my_team": my_team,
        "maps": results,
    }
