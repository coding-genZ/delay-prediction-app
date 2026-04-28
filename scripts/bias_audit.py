"""
Bias audit for the Agent_Rating feature in the delay prediction model.

Checks whether model predictions systematically differ across agent
demographic groups (age buckets) and rating bands, which could indicate
that the rating system encodes demographic bias.

Usage:
  python bias_audit.py
  python bias_audit.py --csv amazon_delivery.csv --model catboost_delay_model.cbm

Outputs:
  - bias_audit_report.csv  (group-level metrics)
  - Prints summary to stdout
"""

import argparse
import json
import os
import warnings

_ROOT = os.path.join(os.path.dirname(__file__), "..")

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score

warnings.filterwarnings("ignore")


def load_data(csv_path: str, config_path: str):
    with open(config_path) as f:
        config = json.load(f)

    df = pd.read_csv(csv_path)

    df["Order_Date"] = pd.to_datetime(df["Order_Date"])
    df["Order_Time"] = pd.to_timedelta(df["Order_Time"].astype(str))
    df["Pickup_Time"] = pd.to_timedelta(df["Pickup_Time"].astype(str))

    df["Pickup_Hour"] = (df["Order_Time"].dt.total_seconds() // 3600).astype(int)
    df["Day_of_Week"] = df["Order_Date"].dt.dayofweek
    df["Is_Weekend"] = (df["Day_of_Week"] >= 5).astype(int)
    df["Prep_Minutes"] = (df["Pickup_Time"] - df["Order_Time"]).dt.total_seconds() / 60

    lat1, lon1 = np.radians(df["Store_Latitude"]), np.radians(df["Store_Longitude"])
    lat2, lon2 = np.radians(df["Drop_Latitude"]), np.radians(df["Drop_Longitude"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    df["Distance_km"] = 2 * 6371.0 * np.arcsin(np.sqrt(a))

    for col in ["Weather", "Traffic", "Vehicle", "Area", "Category"]:
        df[col] = df[col].astype(str).str.strip()

    median_time = df["Delivery_Time"].median()
    df["Delayed"] = (df["Delivery_Time"] > median_time).astype(int)

    feature_cols = config["feature_cols"]
    threshold = config["optimal_threshold"]

    return df, feature_cols, config["categorical_cols"], threshold


def create_groups(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["age_group"] = pd.cut(
        df["Agent_Age"],
        bins=[0, 25, 35, 45, 100],
        labels=["18-25", "26-35", "36-45", "46+"],
    )
    df["rating_band"] = pd.cut(
        df["Agent_Rating"],
        bins=[0, 3.0, 4.0, 4.5, 5.01],
        labels=["1.0-3.0", "3.1-4.0", "4.1-4.5", "4.6-5.0"],
    )
    return df


def compute_group_metrics(df, group_col, y_true, y_proba, threshold):
    rows = []
    for name, idx in df.groupby(group_col).groups.items():
        yt = y_true.iloc[idx]
        yp = y_proba[idx]
        preds = (yp >= threshold).astype(int)

        n = len(yt)
        delay_rate = yt.mean()
        pred_pos_rate = preds.mean()
        mean_proba = yp.mean()

        metrics = {"group": name, "n": n, "actual_delay_rate": round(delay_rate, 4),
                   "pred_positive_rate": round(pred_pos_rate, 4),
                   "mean_predicted_prob": round(mean_proba, 4)}

        if yt.nunique() > 1:
            metrics["roc_auc"] = round(roc_auc_score(yt, yp), 4)
            metrics["f1"] = round(f1_score(yt, preds), 4)
            metrics["precision"] = round(precision_score(yt, preds, zero_division=0), 4)
            metrics["recall"] = round(recall_score(yt, preds, zero_division=0), 4)
        else:
            metrics.update({"roc_auc": None, "f1": None, "precision": None, "recall": None})

        # Disparate impact ratio (vs. overall positive rate)
        overall_rate = (y_proba >= threshold).mean()
        if overall_rate > 0:
            metrics["disparate_impact"] = round(pred_pos_rate / overall_rate, 4)
        else:
            metrics["disparate_impact"] = None

        rows.append(metrics)

    return pd.DataFrame(rows)


def print_report(title, metrics_df):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(metrics_df.to_string(index=False))

    di = metrics_df["disparate_impact"].dropna()
    if len(di) > 0:
        min_di, max_di = di.min(), di.max()
        print(f"\n  Disparate impact range: {min_di:.3f} – {max_di:.3f}")
        if min_di < 0.8 or max_di > 1.25:
            print("  ⚠ WARNING: Disparate impact outside 0.80–1.25 range (4/5ths rule)")
        else:
            print("  ✓ Disparate impact within acceptable range")


def main():
    parser = argparse.ArgumentParser(description="Bias audit for agent rating system")
    parser.add_argument("--csv", default=os.path.join(_ROOT, "data", "amazon_delivery.csv"))
    parser.add_argument("--model", default=os.path.join(_ROOT, "models", "catboost_delay_model.cbm"))
    parser.add_argument("--config", default=os.path.join(_ROOT, "models", "model_info.json"))
    args = parser.parse_args()

    print("Loading data and model...")
    df, feature_cols, cat_cols, threshold = load_data(args.csv, args.config)
    df = create_groups(df)

    model = CatBoostClassifier()
    model.load_model(args.model)

    X = df[feature_cols]
    y = df["Delayed"]
    y_proba = model.predict_proba(Pool(X, cat_features=cat_cols))[:, 1]

    print(f"Dataset: {len(df)} orders, delay rate: {y.mean():.2%}")
    print(f"Threshold: {threshold}")

    # Age group analysis
    age_metrics = compute_group_metrics(df, "age_group", y, y_proba, threshold)
    print_report("BIAS AUDIT: By Agent Age Group", age_metrics)

    # Rating band analysis
    rating_metrics = compute_group_metrics(df, "rating_band", y, y_proba, threshold)
    print_report("BIAS AUDIT: By Agent Rating Band", rating_metrics)

    # Cross-group: age x rating
    df["age_x_rating"] = df["age_group"].astype(str) + " / " + df["rating_band"].astype(str)
    cross_metrics = compute_group_metrics(df, "age_x_rating", y, y_proba, threshold)
    print_report("BIAS AUDIT: Age × Rating Interaction", cross_metrics)

    # Correlation between agent age and rating
    corr = df["Agent_Age"].corr(df["Agent_Rating"])
    print(f"\n  Pearson correlation (Age vs Rating): {corr:.4f}")
    if abs(corr) > 0.3:
        print("  ⚠ Moderate-to-strong correlation — rating may encode age bias")
    else:
        print("  ✓ Weak correlation — rating appears independent of age")

    # Save full report
    all_metrics = pd.concat([
        age_metrics.assign(analysis="age_group"),
        rating_metrics.assign(analysis="rating_band"),
        cross_metrics.assign(analysis="age_x_rating"),
    ], ignore_index=True)
    report_path = os.path.join(_ROOT, "bias_audit_report.csv")
    all_metrics.to_csv(report_path, index=False)
    print(f"\nFull report saved to {report_path}")


if __name__ == "__main__":
    main()
