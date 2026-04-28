# Shipment Delay Prediction App

ML-powered risk alerting for e-commerce dispatch operations. A CatBoost classifier predicts whether a shipment will arrive late, explains the top risk factors via SHAP, and lets dispatchers record feedback that feeds the next model version.

## Repository Structure

```
delay-prediction-app/
├── src/                    # Application source code
│   ├── api.py              # FastAPI backend (prediction + feedback endpoints)
│   ├── app.py              # Streamlit frontend for dispatchers
│   ├── aws_config.py       # S3, DynamoDB, CloudWatch integrations
│   └── weather_service.py  # OpenWeatherMap live weather enrichment
├── data/                   # Dataset
│   └── amazon_delivery.csv # Amazon Delivery Dataset (43,739 orders)
├── models/                 # Trained model and config
│   ├── catboost_delay_model.cbm
│   └── model_info.json     # Feature list, threshold, metrics
├── figures/                # Generated charts and UI screenshots
├── report/                 # Report generation scripts
│   ├── build_report.py     # Generates FinalReport.docx
│   └── generate_figures.py # Generates all evaluation charts
├── scripts/                # Standalone utility scripts
│   ├── tune_optuna.py      # Bayesian hyperparameter tuning (Optuna)
│   ├── sagemaker_retrain.py# Retrain with feedback data, upload to S3
│   └── bias_audit.py       # Fairness audit across demographic groups
├── infra/                  # AWS deployment
│   ├── template.yaml       # SAM template (Lambda, API Gateway, DynamoDB, S3)
│   └── lambda_handler.py   # Mangum adapter for Lambda
├── .env.example            # Environment variable template
├── .gitignore
├── requirements.txt
├── start.bat               # One-click launcher (Windows)
└── start.sh                # One-click launcher (Mac/Linux)
```

## Prerequisites

- Python 3.11+

## Quick Start

**1. Create and activate a virtual environment:**

```bash
python -m venv venv
```

Windows:
```powershell
.\venv\Scripts\Activate.ps1
```

Mac/Linux:
```bash
source venv/bin/activate
```

**2. Install dependencies:**

```bash
pip install -r requirements.txt
```

**3. Start the backend (Terminal 1):**

```bash
cd src
uvicorn api:app --port 8000
```

**4. Start the frontend (Terminal 2 — activate venv first):**

```bash
cd src
streamlit run app.py
```

**5.** Open **http://localhost:8501** in your browser.

### One-Click Start

- **Windows:** Double-click `start.bat`
- **Mac/Linux:** `chmod +x start.sh && ./start.sh`

Both scripts create the venv, install dependencies, start both servers, and open the browser.

## Reproducing the Pipeline

### Training and Evaluation

The model is already trained and saved in `models/`. To regenerate evaluation figures:

```bash
python report/generate_figures.py
```

This reads `data/amazon_delivery.csv` and `models/catboost_delay_model.cbm`, runs the 80/20 stratified split (random_state=42), and writes all charts to `figures/`.

### Hyperparameter Tuning (Optional)

```bash
python scripts/tune_optuna.py                  # 50 trials
python scripts/tune_optuna.py --n-trials 200   # more trials
```

Outputs tuned model to `models/catboost_delay_model_tuned.cbm`.

### Bias Audit

```bash
python scripts/bias_audit.py
```

Checks for disparate impact across courier age groups and rating bands.

### Retraining with Feedback Data

```bash
python scripts/sagemaker_retrain.py                          # local only
python scripts/sagemaker_retrain.py --upload                 # retrain + push to S3
python scripts/sagemaker_retrain.py --upload --min-auc 0.90  # only upload if AUC meets threshold
```

## AWS Configuration (Optional)

All AWS integrations are optional. The app runs fully local with no environment variables set. Copy `.env.example` to `.env` and fill in values to enable:

| Variable | Effect |
|----------|--------|
| `S3_MODEL_BUCKET` | Load model from S3 instead of local files |
| `DYNAMODB_PREDICTIONS_TABLE` | Log predictions + feedback to DynamoDB |
| `CLOUDWATCH_LOG_GROUP` | Stream logs to CloudWatch |
| `OPENWEATHER_API_KEY` | Live weather enrichment (free tier) |

### Deploying to AWS Lambda

Prerequisites: AWS CLI + AWS SAM CLI installed, credentials configured.

```bash
# Upload model artifacts to S3
aws s3 cp models/catboost_delay_model.cbm s3://YOUR-BUCKET/models/catboost_delay_model.cbm
aws s3 cp models/model_info.json s3://YOUR-BUCKET/models/model_info.json

# Deploy with SAM
cd infra
sam build
sam deploy --guided
```

SAM creates: Lambda function, API Gateway, DynamoDB table, S3 bucket, and CloudWatch log group.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Service info + model metadata |
| `GET` | `/health` | Health check |
| `POST` | `/predict` | Score an order — returns probability, risk flag, SHAP drivers |
| `POST` | `/feedback` | Submit dispatcher action + actual outcome for a prediction |

## Model Details

- **Algorithm:** CatBoost classifier
- **Training data:** Amazon Delivery Dataset (43,594 rows after cleaning)
- **Features:** 12 input features (courier, environment, logistics, temporal)
- **Threshold:** 0.26 (cost-optimized: $20/missed delay vs $8/false alarm)
- **Top features:** Traffic, Agent Age, Agent Rating, Weather, Vehicle, Distance
