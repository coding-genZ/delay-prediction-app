"""
FastAPI server for shipment delay prediction.
Loads a pre-trained CatBoost model (from S3 or local), serves predictions
with SHAP explanations, and logs predictions to DynamoDB.

Run with:  uvicorn api:app --reload --port 8000

Optional env vars (see aws_config.py for full list):
  S3_MODEL_BUCKET, DYNAMODB_PREDICTIONS_TABLE, CLOUDWATCH_LOG_GROUP
"""
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import json
import math
import pandas as pd
import numpy as np
from catboost import CatBoostClassifier
import shap

from aws_config import (
    setup_cloudwatch_logging,
    download_model_from_s3,
    log_prediction,
    log_feedback,
)
from weather_service import get_route_weather

# ----- Logging (CloudWatch if configured, else stdout) -----
setup_cloudwatch_logging()
logger = logging.getLogger("shipment_delay")

# ----- Load model and config at startup (S3 if configured, else local) -----
MODEL_PATH, CONFIG_PATH = download_model_from_s3()

model = CatBoostClassifier()
model.load_model(MODEL_PATH)
logger.info("CatBoost model loaded from %s", MODEL_PATH)

with open(CONFIG_PATH) as f:
    config = json.load(f)
logger.info("Model config loaded from %s", CONFIG_PATH)

FEATURE_COLS = config["feature_cols"]
CATEGORICAL_COLS = config["categorical_cols"]
OPTIMAL_THRESHOLD = config["optimal_threshold"]

# Build a SHAP explainer once (fast for tree models)
explainer = shap.TreeExplainer(model)

# Friendly labels for the UI
FEATURE_LABELS = {
    "Agent_Age": "Courier age",
    "Agent_Rating": "Courier rating",
    "Distance_km": "Distance (km)",
    "Pickup_Hour": "Pickup hour",
    "Day_of_Week": "Day of week",
    "Is_Weekend": "Weekend",
    "Prep_Minutes": "Prep time (min)",
    "Weather": "Weather",
    "Traffic": "Traffic",
    "Vehicle": "Vehicle",
    "Area": "Area",
    "Category": "Product category",
}

# ----- FastAPI setup -----
app = FastAPI(
    title="Shipment Delay Prediction API",
    description="Predicts whether an e-commerce shipment will arrive late, with SHAP explanations.",
    version="1.0.0",
)

# Allow Streamlit running on a different port to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- Request/response schemas -----
class OrderRequest(BaseModel):
    Agent_Age: int = Field(..., ge=18, le=80, example=32)
    Agent_Rating: float = Field(..., ge=1.0, le=5.0, example=4.5)
    Store_Latitude: float = Field(..., example=22.745049)
    Store_Longitude: float = Field(..., example=75.892471)
    Drop_Latitude: float = Field(..., example=22.765049)
    Drop_Longitude: float = Field(..., example=75.912471)
    Pickup_Hour: int = Field(..., ge=0, le=23, example=14)
    Day_of_Week: int = Field(..., ge=0, le=6, example=2)
    Prep_Minutes: float = Field(..., ge=0, le=120, example=10)
    Weather: str = Field(..., example="Sunny")
    Traffic: str = Field(..., example="Medium")
    Vehicle: str = Field(..., example="motorcycle")
    Area: str = Field(..., example="Urban")
    Category: str = Field(..., example="Electronics")


class DriverFactor(BaseModel):
    feature: str
    value: str
    direction: str  # "increases" or "decreases"
    shap_value: float


class PredictionResponse(BaseModel):
    prediction_id: Optional[str] = None
    delay_probability: float
    risk_label: str
    threshold: float
    top_drivers: List[DriverFactor]
    suggested_action: str
    live_weather: Optional[dict] = None


class FeedbackRequest(BaseModel):
    prediction_id: str = Field(..., description="ID returned from /predict")
    dispatcher_action: str = Field(
        ...,
        description="What the dispatcher did",
        example="reassigned_courier",
    )
    actual_outcome: str = Field(
        ...,
        description="What actually happened",
        example="delivered_late",
    )
    notes: str = Field("", example="Customer complained about cold food")


# ----- Helpers -----
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def build_feature_row(req: OrderRequest) -> pd.DataFrame:
    """Transform the incoming request into the exact feature layout the model expects."""
    distance = haversine_km(
        req.Store_Latitude, req.Store_Longitude, req.Drop_Latitude, req.Drop_Longitude
    )
    is_weekend = 1 if req.Day_of_Week >= 5 else 0
    row = {
        "Agent_Age": req.Agent_Age,
        "Agent_Rating": req.Agent_Rating,
        "Distance_km": distance,
        "Pickup_Hour": req.Pickup_Hour,
        "Day_of_Week": req.Day_of_Week,
        "Is_Weekend": is_weekend,
        "Prep_Minutes": req.Prep_Minutes,
        "Weather": req.Weather,
        "Traffic": req.Traffic,
        "Vehicle": req.Vehicle,
        "Area": req.Area,
        "Category": req.Category,
    }
    return pd.DataFrame([row])[FEATURE_COLS]


def suggested_action(prob: float) -> str:
    if prob >= 0.60:
        return "High risk — consider reassigning courier or notifying customer proactively."
    if prob >= OPTIMAL_THRESHOLD:
        return "Elevated risk — monitor shipment; consider route/ETA adjustment."
    return "Low risk — no action needed."


# ----- Endpoints -----
@app.get("/")
def root():
    return {
        "service": "Shipment Delay Prediction API",
        "status": "ok",
        "model": "CatBoost",
        "optimal_threshold": OPTIMAL_THRESHOLD,
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/predict", response_model=PredictionResponse)
def predict(order: OrderRequest):
    try:
        # Enrich weather from live API if available
        weather_data = get_route_weather(
            order.Store_Latitude, order.Store_Longitude,
            order.Drop_Latitude, order.Drop_Longitude,
        )
        if weather_data:
            order.Weather = weather_data["weather_label"]
            logger.info("Weather overridden by live API: %s", order.Weather)

        X = build_feature_row(order)
        proba = float(model.predict_proba(X)[0, 1])
        risk = "DELAYED" if proba >= OPTIMAL_THRESHOLD else "ON-TIME"

        # Per-order SHAP
        shap_vals = explainer.shap_values(X)[0]
        driver_df = pd.DataFrame(
            {
                "feature": X.columns,
                "value": X.iloc[0].values.astype(str),
                "shap": shap_vals,
                "abs_shap": np.abs(shap_vals),
            }
        ).sort_values("abs_shap", ascending=False).head(3)

        drivers = [
            DriverFactor(
                feature=FEATURE_LABELS.get(r["feature"], r["feature"]),
                value=str(r["value"]),
                direction="increases" if r["shap"] > 0 else "decreases",
                shap_value=float(r["shap"]),
            )
            for _, r in driver_df.iterrows()
        ]

        response = PredictionResponse(
            delay_probability=round(proba, 4),
            risk_label=risk,
            threshold=OPTIMAL_THRESHOLD,
            top_drivers=drivers,
            suggested_action=suggested_action(proba),
            live_weather=weather_data,
        )

        prediction_id = log_prediction(
            order.model_dump(), response.model_dump(), weather_data
        )
        response.prediction_id = prediction_id

        logger.info("Prediction %s: prob=%.4f risk=%s", prediction_id, proba, risk)
        return response
    except Exception as e:
        logger.error("Prediction failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Prediction error: {e}")


@app.post("/feedback")
def submit_feedback(fb: FeedbackRequest):
    success = log_feedback(
        prediction_id=fb.prediction_id,
        dispatcher_action=fb.dispatcher_action,
        actual_outcome=fb.actual_outcome,
        notes=fb.notes,
    )
    if success:
        logger.info("Feedback received for %s: action=%s outcome=%s",
                     fb.prediction_id, fb.dispatcher_action, fb.actual_outcome)
        return {"status": "ok", "prediction_id": fb.prediction_id}
    raise HTTPException(
        status_code=503,
        detail="Feedback storage unavailable — DynamoDB not configured or unreachable",
    )