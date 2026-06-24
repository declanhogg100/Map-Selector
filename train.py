import pandas as pd
import numpy as np
import json
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, log_loss, classification_report
import pickle

MAPS = ["de_mirage", "de_dust2", "de_ancient", "de_inferno", "de_anubis", "de_nuke", "de_cache", "de_overpass"]
MIN_MATCHES = 200

def train_map_model(df_map, map_name):
    drop_cols = ["label", "match_id", "map"]
    feature_cols = [c for c in df_map.columns if c not in drop_cols]

    X = df_map[feature_cols].copy()
    y = df_map["label"]

    # Drop columns that are entirely null
    X = X.dropna(axis=1, how="all")

    # Fill remaining nulls with column median
    X = X.fillna(X.median())

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        random_state=42,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    preds = model.predict(X_test)
    probs = model.predict_proba(X_test)[:, 1]
    acc = accuracy_score(y_test, preds)
    loss = log_loss(y_test, probs)

    print(f"\n{map_name} ({len(df_map)} matches)")
    print(f"  Accuracy: {acc:.3f}  |  Log loss: {loss:.3f}")
    print(classification_report(y_test, preds, target_names=["Team 2 wins", "Team 1 wins"], zero_division=0))

    # Top 10 most important features
    importances = pd.Series(model.feature_importances_, index=X.columns)
    top = importances.sort_values(ascending=False).head(10)
    print("  Top features:")
    for feat, score in top.items():
        print(f"    {feat}: {score:.4f}")

    return model, list(X.columns), acc


def main():
    df = pd.read_csv("training_data.csv")

    # Filter to competitive maps only
    df = df[df["map"].isin(MAPS)]
    print(f"Total matches after map filter: {len(df)}")

    models = {}
    for map_name in MAPS:
        df_map = df[df["map"] == map_name]
        if len(df_map) < MIN_MATCHES:
            print(f"\nSkipping {map_name} — only {len(df_map)} matches")
            continue
        model, feature_cols, acc = train_map_model(df_map, map_name)
        models[map_name] = {"model": model, "features": feature_cols, "accuracy": acc}

    # Save all models to disk
    with open("models.pkl", "wb") as f:
        pickle.dump(models, f)

    print("\nSaved models.pkl")
    print("\nSummary:")
    for map_name, m in models.items():
        print(f"  {map_name}: {m['accuracy']:.3f} accuracy")


if __name__ == "__main__":
    main()
