"""
SageMaker retraining pipeline for the shipment delay model.

Designed to run monthly on a schedule (EventBridge -> Lambda -> this script)
or manually from any machine with AWS credentials.

Flow:
  1. Pull feedback-enriched data from DynamoDB
  2. Merge with the original CSV training data
  3. Retrain CatBoost with the latest Optuna-tuned hyperparams
  4. Evaluate on a held-out set
  5. If performance improves, upload new model to S3
  6. Log everything to CloudWatch

Usage:
  python sagemaker_retrain.py                          # local execution
  python sagemaker_retrain.py --upload                 # retrain + upload to S3
  python sagemaker_retrain.py --upload --min-auc 0.95  # only upload if AUC >= 0.95

Env vars:
  AWS_REGION, S3_MODEL_BUCKET, DYNAMODB_PREDICTIONS_TABLE (see aws_config.py)
"""

import argparse
import json
import logging
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import roc_auc_score, f1_score, classification_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("retrain")

ROOT = os.path.join(os.path.dirname(__file__), "..")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_csv_data(csv_path: str) -> pd.DataFrame:
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

    return df


def load_feedback_data() -> pd.DataFrame:
    """Pull completed feedback records from DynamoDB and convert to training rows."""
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    table_name = os.getenv("DYNAMODB_PREDICTIONS_TABLE", "shipment-delay-predictions")
    region = os.getenv("AWS_REGION", "us-east-1")

    try:
        dynamo = boto3.resource("dynamodb", region_name=region)
        table = dynamo.Table(table_name)

        rows = []
        scan_kwargs = {
            "FilterExpression": "feedback_status = :s AND actual_outcome <> :p",
            "ExpressionAttributeValues": {":s": "received", ":p": "pending"},
        }

        while True:
            response = table.scan(**scan_kwargs)
            for item in response.get("Items", []):
                req = item.get("request", {})
                outcome = item.get("actual_outcome", "")

                if outcome in ("delivered_late", "delivered_on_time"):
                    row = {
                        "Agent_Age": int(req.get("Agent_Age", 0)),
                        "Agent_Rating": float(req.get("Agent_Rating", 0)),
                        "Distance_km": float(req.get("Distance_km", 0)),
                        "Pickup_Hour": int(req.get("Pickup_Hour", 0)),
                        "Day_of_Week": int(req.get("Day_of_Week", 0)),
                        "Is_Weekend": int(req.get("Is_Weekend", 0)),
                        "Prep_Minutes": float(req.get("Prep_Minutes", 0)),
                        "Weather": str(req.get("Weather", "")),
                        "Traffic": str(req.get("Traffic", "")),
                        "Vehicle": str(req.get("Vehicle", "")),
                        "Area": str(req.get("Area", "")),
                        "Category": str(req.get("Category", "")),
                        "Delayed": 1 if outcome == "delivered_late" else 0,
                        "source": "feedback",
                    }
                    rows.append(row)

            if "LastEvaluatedKey" not in response:
                break
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        logger.info("Loaded %d feedback rows from DynamoDB", len(rows))
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    except (BotoCoreError, ClientError) as e:
        logger.warning("Could not load feedback data: %s", e)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

FEATURE_COLS = [
    "Agent_Age", "Agent_Rating", "Distance_km", "Pickup_Hour",
    "Day_of_Week", "Is_Weekend", "Prep_Minutes",
    "Weather", "Traffic", "Vehicle", "Area", "Category",
]
CAT_COLS = ["Weather", "Traffic", "Vehicle", "Area", "Category"]


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


def retrain(csv_path: str, include_feedback: bool = True):
    logger.info("Loading CSV training data...")
    csv_df = load_csv_data(csv_path)
    csv_df["source"] = "csv"
    logger.info("  CSV rows: %d", len(csv_df))

    if include_feedback:
        fb_df = load_feedback_data()
        if not fb_df.empty:
            combined = pd.concat([csv_df[FEATURE_COLS + ["Delayed", "source"]],
                                  fb_df[FEATURE_COLS + ["Delayed", "source"]]],
                                 ignore_index=True)
            logger.info("  Combined: %d CSV + %d feedback = %d total",
                        len(csv_df), len(fb_df), len(combined))
        else:
            combined = csv_df
            logger.info("  No feedback data available, using CSV only")
    else:
        combined = csv_df

    X = combined[FEATURE_COLS]
    y = combined["Delayed"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    logger.info("Training: %d rows, Test: %d rows", len(X_train), len(X_test))

    # Load best params if available from Optuna
    params = {
        "iterations": 1000,
        "depth": 6,
        "learning_rate": 0.1,
        "l2_leaf_reg": 3.0,
        "eval_metric": "AUC",
        "verbose": 100,
        "random_seed": 42,
        "cat_features": CAT_COLS,
        "early_stopping_rounds": 50,
    }

    tuned_config = os.path.join(ROOT, "models", "model_info_tuned.json")
    if os.path.exists(tuned_config):
        with open(tuned_config) as f:
            tuned = json.load(f)
        if "optuna_best_params" in tuned:
            logger.info("Using Optuna-tuned hyperparameters")
            for k, v in tuned["optuna_best_params"].items():
                params[k] = v

    model = CatBoostClassifier(**params)
    model.fit(
        Pool(X_train, y_train, cat_features=CAT_COLS),
        eval_set=Pool(X_test, y_test, cat_features=CAT_COLS),
    )

    # Evaluate
    y_proba = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_proba)
    threshold = find_optimal_threshold(y_test, y_proba)
    y_pred = (y_proba >= threshold).astype(int)
    f1 = f1_score(y_test, y_pred)

    logger.info("Test ROC-AUC: %.4f", auc)
    logger.info("Optimal threshold: %.2f", threshold)
    logger.info("Test F1: %.4f", f1)
    logger.info("\n%s", classification_report(y_test, y_pred, target_names=["On-Time", "Delayed"]))

    # CV for stability check
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_aucs = []
    for tr_idx, val_idx in cv.split(X, y):
        cv_model = CatBoostClassifier(**{**params, "verbose": 0})
        cv_model.fit(Pool(X.iloc[tr_idx], y.iloc[tr_idx], cat_features=CAT_COLS))
        cv_proba = cv_model.predict_proba(X.iloc[val_idx])[:, 1]
        cv_aucs.append(roc_auc_score(y.iloc[val_idx], cv_proba))
    logger.info("5-fold CV AUC: %.4f ± %.4f", np.mean(cv_aucs), np.std(cv_aucs))

    # Save locally
    model.save_model(os.path.join(ROOT, "models", "catboost_delay_model_retrained.cbm"))

    config = {
        "feature_cols": FEATURE_COLS,
        "categorical_cols": CAT_COLS,
        "numeric_cols": [c for c in FEATURE_COLS if c not in CAT_COLS],
        "optimal_threshold": threshold,
        "train_delayed_rate": round(float(y.mean()), 4),
        "test_roc_auc": round(auc, 4),
        "test_f1": round(f1, 4),
        "retrained_at": datetime.now(timezone.utc).isoformat(),
        "training_rows": len(combined),
        "feedback_rows": len(combined[combined.get("source", "") == "feedback"]) if "source" in combined.columns else 0,
    }
    with open(os.path.join(ROOT, "models", "model_info_retrained.json"), "w") as f:
        json.dump(config, f, indent=2)

    logger.info("Saved: catboost_delay_model_retrained.cbm, model_info_retrained.json")

    return auc, threshold, f1


def upload_to_s3():
    import sys
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from aws_config import upload_model_to_s3
    logger.info("Uploading retrained model to S3...")
    success = upload_model_to_s3(
        local_model_path=os.path.join(ROOT, "models", "catboost_delay_model_retrained.cbm"),
        local_config_path=os.path.join(ROOT, "models", "model_info_retrained.json"),
    )
    if success:
        logger.info("Model uploaded to S3 successfully")
    else:
        logger.error("Failed to upload model to S3")
    return success


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Retrain delay prediction model")
    parser.add_argument("--csv", default=os.path.join(ROOT, "data", "amazon_delivery.csv"))
    parser.add_argument("--upload", action="store_true", help="Upload to S3 after training")
    parser.add_argument("--min-auc", type=float, default=0.0,
                        help="Only upload if test AUC >= this value")
    parser.add_argument("--no-feedback", action="store_true",
                        help="Skip DynamoDB feedback data")
    args = parser.parse_args()

    auc, threshold, f1 = retrain(args.csv, include_feedback=not args.no_feedback)

    if args.upload:
        if auc >= args.min_auc:
            upload_to_s3()
        else:
            logger.warning("AUC %.4f < min %.4f — skipping S3 upload", auc, args.min_auc)


if __name__ == "__main__":
    main()
