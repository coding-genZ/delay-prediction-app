"""
AWS integrations: S3 model loading, DynamoDB prediction logging, CloudWatch logging.

Environment variables (all optional — falls back to local files and stdout logging):
  AWS_REGION              – AWS region (default: us-east-1)
  S3_MODEL_BUCKET         – S3 bucket holding model artifacts
  S3_MODEL_KEY            – key for catboost_delay_model.cbm   (default: models/catboost_delay_model.cbm)
  S3_CONFIG_KEY           – key for model_info.json             (default: models/model_info.json)
  DYNAMODB_PREDICTIONS_TABLE – DynamoDB table for prediction logs (default: shipment-delay-predictions)
  CLOUDWATCH_LOG_GROUP    – CloudWatch log group               (default: /shipment-delay/api)
"""

import os
import json
import logging
import tempfile
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("shipment_delay")

REGION = os.getenv("AWS_REGION", "us-east-1")


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _s3_client():
    return boto3.client("s3", region_name=REGION)


def download_model_from_s3(
    local_model_path: str = os.path.join(os.path.dirname(__file__), "..", "models", "catboost_delay_model.cbm"),
    local_config_path: str = os.path.join(os.path.dirname(__file__), "..", "models", "model_info.json"),
) -> tuple[str, str]:
    bucket = os.getenv("S3_MODEL_BUCKET")
    if not bucket:
        logger.info("S3_MODEL_BUCKET not set — using local model files")
        return local_model_path, local_config_path

    model_key = os.getenv("S3_MODEL_KEY", "models/catboost_delay_model.cbm")
    config_key = os.getenv("S3_CONFIG_KEY", "models/model_info.json")

    s3 = _s3_client()
    tmp_dir = tempfile.mkdtemp(prefix="delay_model_")

    model_dest = os.path.join(tmp_dir, "catboost_delay_model.cbm")
    config_dest = os.path.join(tmp_dir, "model_info.json")

    try:
        logger.info("Downloading model from s3://%s/%s", bucket, model_key)
        s3.download_file(bucket, model_key, model_dest)

        logger.info("Downloading config from s3://%s/%s", bucket, config_key)
        s3.download_file(bucket, config_key, config_dest)

        logger.info("S3 model artifacts downloaded to %s", tmp_dir)
        return model_dest, config_dest

    except (BotoCoreError, ClientError) as e:
        logger.warning("S3 download failed (%s) — falling back to local files", e)
        return local_model_path, local_config_path


def upload_model_to_s3(
    local_model_path: str = os.path.join(os.path.dirname(__file__), "..", "models", "catboost_delay_model.cbm"),
    local_config_path: str = os.path.join(os.path.dirname(__file__), "..", "models", "model_info.json"),
) -> bool:
    bucket = os.getenv("S3_MODEL_BUCKET")
    if not bucket:
        logger.error("S3_MODEL_BUCKET not set — cannot upload")
        return False

    model_key = os.getenv("S3_MODEL_KEY", "models/catboost_delay_model.cbm")
    config_key = os.getenv("S3_CONFIG_KEY", "models/model_info.json")

    s3 = _s3_client()
    try:
        logger.info("Uploading model to s3://%s/%s", bucket, model_key)
        s3.upload_file(local_model_path, bucket, model_key)

        logger.info("Uploading config to s3://%s/%s", bucket, config_key)
        s3.upload_file(local_config_path, bucket, config_key)

        logger.info("Model artifacts uploaded to S3")
        return True

    except (BotoCoreError, ClientError) as e:
        logger.error("S3 upload failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# DynamoDB prediction logging
# ---------------------------------------------------------------------------

_dynamo_table = None


def _get_dynamo_table():
    global _dynamo_table
    if _dynamo_table is not None:
        return _dynamo_table

    table_name = os.getenv("DYNAMODB_PREDICTIONS_TABLE", "shipment-delay-predictions")
    try:
        dynamo = boto3.resource("dynamodb", region_name=REGION)
        _dynamo_table = dynamo.Table(table_name)
        _dynamo_table.load()
        logger.info("Connected to DynamoDB table: %s", table_name)
        return _dynamo_table
    except (BotoCoreError, ClientError) as e:
        logger.warning("DynamoDB unavailable (%s) — predictions will not be logged", e)
        _dynamo_table = None
        return None


def _to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(round(obj, 6)))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(i) for i in obj]
    return obj


def log_prediction(
    request_data: dict,
    response_data: dict,
    weather_data: Optional[dict] = None,
) -> Optional[str]:
    table = _get_dynamo_table()
    if table is None:
        return None

    prediction_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    item = {
        "prediction_id": prediction_id,
        "timestamp": timestamp,
        "request": _to_decimal(request_data),
        "response": _to_decimal(response_data),
        "feedback_status": "pending",
    }
    if weather_data:
        item["live_weather"] = _to_decimal(weather_data)

    try:
        table.put_item(Item=item)
        logger.info("Logged prediction %s to DynamoDB", prediction_id)
        return prediction_id
    except (BotoCoreError, ClientError) as e:
        logger.warning("Failed to log prediction to DynamoDB: %s", e)
        return None


def log_feedback(
    prediction_id: str,
    dispatcher_action: str,
    actual_outcome: str,
    notes: str = "",
) -> bool:
    table = _get_dynamo_table()
    if table is None:
        return False

    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        table.update_item(
            Key={"prediction_id": prediction_id},
            UpdateExpression=(
                "SET feedback_status = :s, "
                "dispatcher_action = :da, "
                "actual_outcome = :ao, "
                "feedback_notes = :n, "
                "feedback_timestamp = :ts"
            ),
            ExpressionAttributeValues={
                ":s": "received",
                ":da": dispatcher_action,
                ":ao": actual_outcome,
                ":n": notes,
                ":ts": timestamp,
            },
        )
        logger.info("Feedback recorded for prediction %s", prediction_id)
        return True
    except (BotoCoreError, ClientError) as e:
        logger.warning("Failed to log feedback for %s: %s", prediction_id, e)
        return False


# ---------------------------------------------------------------------------
# CloudWatch logging setup
# ---------------------------------------------------------------------------

def setup_cloudwatch_logging() -> None:
    log_group = os.getenv("CLOUDWATCH_LOG_GROUP")
    if not log_group:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )
        logger.info("CLOUDWATCH_LOG_GROUP not set — logging to stdout only")
        return

    try:
        import watchtower

        cw_handler = watchtower.CloudWatchLogHandler(
            log_group_name=log_group,
            boto3_client=boto3.client("logs", region_name=REGION),
            create_log_group=True,
        )
        formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        cw_handler.setFormatter(formatter)

        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(cw_handler)

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

        logger.info("CloudWatch logging enabled — group: %s", log_group)

    except (BotoCoreError, ClientError, ImportError) as e:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )
        logger.warning("CloudWatch setup failed (%s) — logging to stdout only", e)
