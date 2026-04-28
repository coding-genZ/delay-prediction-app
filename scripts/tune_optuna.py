"""
Bayesian hyperparameter tuning for the CatBoost delay model using Optuna.

Usage:
  python tune_optuna.py                     # default 50 trials
  python tune_optuna.py --n-trials 200      # more trials for production

Outputs:
  - catboost_delay_model_tuned.cbm   (best model)
  - model_info_tuned.json            (updated config with new threshold)
  - optuna_results.csv               (all trial results)
"""

import argparse
import json
import os
import warnings

import numpy as np
import pandas as pd
import optuna
from catboost import CatBoostClassifier, Pool
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score, f1_score

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ---------------------------------------------------------------------------
# Data loading (same pipeline as the original training)
# ---------------------------------------------------------------------------

def load_and_prepare(csv_path: str = "amazon_delivery.csv"):
    df = pd.read_csv(csv_path)

    df["Order_Date"] = pd.to_datetime(df["Order_Date"])
    df["Order_Time"] = pd.to_timedelta(df["Order_Time"].astype(str))
    df["Pickup_Time"] = pd.to_timedelta(df["Pickup_Time"].astype(str))

    # Derived features
    df["Pickup_Hour"] = (df["Order_Time"].dt.total_seconds() // 3600).astype(int)
    df["Day_of_Week"] = df["Order_Date"].dt.dayofweek
    df["Is_Weekend"] = (df["Day_of_Week"] >= 5).astype(int)
    df["Prep_Minutes"] = (df["Pickup_Time"] - df["Order_Time"]).dt.total_seconds() / 60

    # Haversine distance
    lat1, lon1 = np.radians(df["Store_Latitude"]), np.radians(df["Store_Longitude"])
    lat2, lon2 = np.radians(df["Drop_Latitude"]), np.radians(df["Drop_Longitude"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    df["Distance_km"] = 2 * 6371.0 * np.arcsin(np.sqrt(a))

    # Strip whitespace from categoricals
    for col in ["Weather", "Traffic", "Vehicle", "Area", "Category"]:
        df[col] = df[col].astype(str).str.strip()

    # Binary target: delayed = delivery > 45 min
    median_time = df["Delivery_Time"].median()
    df["Delayed"] = (df["Delivery_Time"] > median_time).astype(int)

    feature_cols = [
        "Agent_Age", "Agent_Rating", "Distance_km", "Pickup_Hour",
        "Day_of_Week", "Is_Weekend", "Prep_Minutes",
        "Weather", "Traffic", "Vehicle", "Area", "Category",
    ]
    cat_cols = ["Weather", "Traffic", "Vehicle", "Area", "Category"]

    return df[feature_cols], df["Delayed"], feature_cols, cat_cols


# ---------------------------------------------------------------------------
# Optuna objective
# ---------------------------------------------------------------------------

def objective(trial, X, y, cat_cols):
    params = {
        "iterations": trial.suggest_int("iterations", 300, 1500),
        "depth": trial.suggest_int("depth", 4, 10),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1e-2, 10.0, log=True),
        "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 5.0),
        "random_strength": trial.suggest_float("random_strength", 0.0, 5.0),
        "border_count": trial.suggest_int("border_count", 32, 255),
        "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 1, 50),
        "cat_features": cat_cols,
        "eval_metric": "AUC",
        "verbose": 0,
        "random_seed": 42,
    }

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    auc_scores = []

    for train_idx, val_idx in cv.split(X, y):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

        model = CatBoostClassifier(**params)
        model.fit(
            Pool(X_train, y_train, cat_features=cat_cols),
            eval_set=Pool(X_val, y_val, cat_features=cat_cols),
            early_stopping_rounds=50,
        )

        proba = model.predict_proba(X_val)[:, 1]
        auc_scores.append(roc_auc_score(y_val, proba))

    return np.mean(auc_scores)


# ---------------------------------------------------------------------------
# Cost-sensitive threshold search
# ---------------------------------------------------------------------------

def find_optimal_threshold(y_true, y_proba, fn_cost=20, fp_cost=8):
    best_cost, best_t = float("inf"), 0.5
    for t in np.arange(0.05, 0.95, 0.01):
        preds = (y_proba >= t).astype(int)
        fn = ((y_true == 1) & (preds == 0)).sum()
        fp = ((y_true == 0) & (preds == 1)).sum()
        cost = fn * fn_cost + fp * fp_cost
        if cost < best_cost:
            best_cost, best_t = cost, t
    return round(best_t, 2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Optuna hyperparameter tuning")
    parser.add_argument("--n-trials", type=int, default=50)
    parser.add_argument("--csv", default=os.path.join(os.path.dirname(__file__), "..", "data", "amazon_delivery.csv"))
    args = parser.parse_args()

    print(f"Loading data from {args.csv}...")
    X, y, feature_cols, cat_cols = load_and_prepare(args.csv)
    print(f"  {len(X)} rows, {len(feature_cols)} features, delay rate = {y.mean():.2%}")

    print(f"\nRunning {args.n_trials} Optuna trials (5-fold CV each)...")
    study = optuna.create_study(direction="maximize", study_name="catboost-delay")
    study.optimize(lambda trial: objective(trial, X, y, cat_cols), n_trials=args.n_trials)

    print(f"\nBest CV ROC-AUC: {study.best_value:.4f}")
    print(f"Best params: {study.best_params}")

    # Save trial results
    trials_df = study.trials_dataframe()
    trials_df.to_csv(os.path.join(os.path.dirname(__file__), "..", "optuna_results.csv"), index=False)
    print("  Trial results saved to optuna_results.csv")

    # Retrain best model on full data
    print("\nRetraining best model on full dataset...")
    best_params = study.best_params.copy()
    best_params["cat_features"] = cat_cols
    best_params["eval_metric"] = "AUC"
    best_params["verbose"] = 100
    best_params["random_seed"] = 42

    final_model = CatBoostClassifier(**best_params)
    final_model.fit(Pool(X, y, cat_features=cat_cols))

    # Find optimal threshold
    proba_full = final_model.predict_proba(X)[:, 1]
    threshold = find_optimal_threshold(y, proba_full)
    f1 = f1_score(y, (proba_full >= threshold).astype(int))

    print(f"  Optimal threshold: {threshold}")
    print(f"  F1 at threshold:   {f1:.4f}")

    # Save
    final_model.save_model(os.path.join(os.path.dirname(__file__), "..", "models", "catboost_delay_model_tuned.cbm"))

    config = {
        "feature_cols": feature_cols,
        "categorical_cols": cat_cols,
        "numeric_cols": [c for c in feature_cols if c not in cat_cols],
        "optimal_threshold": threshold,
        "train_delayed_rate": round(float(y.mean()), 4),
        "test_roc_auc": round(study.best_value, 4),
        "test_f1": round(f1, 4),
        "optuna_best_params": study.best_params,
        "optuna_n_trials": args.n_trials,
    }
    with open(os.path.join(os.path.dirname(__file__), "..", "models", "model_info_tuned.json"), "w") as f:
        json.dump(config, f, indent=2)

    print("\nSaved:")
    print("  catboost_delay_model_tuned.cbm")
    print("  model_info_tuned.json")
    print("\nTo use the tuned model, rename these to replace the originals.")


if __name__ == "__main__":
    main()
