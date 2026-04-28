"""
Generate all figures for the final report from the actual dataset and model.
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from catboost import CatBoostClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    roc_curve, auc, confusion_matrix, precision_recall_curve,
    average_precision_score
)
import json, os, warnings
warnings.filterwarnings("ignore")

ROOT = os.path.join(os.path.dirname(__file__), "..")
FIG_DIR = os.path.join(ROOT, "figures")

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman"],
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "figure.dpi": 200,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
    "axes.spines.top": False,
    "axes.spines.right": False,
})

# ── Load data ──
df = pd.read_csv(os.path.join(ROOT, "data", "amazon_delivery.csv"))
df.columns = df.columns.str.strip()
for col in ["Weather", "Traffic", "Vehicle", "Area", "Category"]:
    df[col] = df[col].str.strip()

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1))*np.cos(np.radians(lat2))*np.sin(dlon/2)**2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

df["Distance_km"] = haversine(df.Store_Latitude, df.Store_Longitude, df.Drop_Latitude, df.Drop_Longitude)

for col in ["Order_Date", "Order_Time", "Pickup_Time"]:
    df[col] = df[col].replace(r'^\s*NaN\s*$', pd.NA, regex=True)
df.dropna(subset=["Order_Date", "Order_Time", "Pickup_Time", "Delivery_Time"], inplace=True)

df["Order_Date"] = pd.to_datetime(df["Order_Date"])
df["Order_Time"] = pd.to_timedelta(df["Order_Time"].astype(str))
df["Pickup_Time"] = pd.to_timedelta(df["Pickup_Time"].astype(str))
df["Pickup_Hour"] = (df["Order_Time"].dt.total_seconds() // 3600).astype(int)
df["Day_of_Week"] = df["Order_Date"].dt.dayofweek
df["Is_Weekend"] = (df["Day_of_Week"] >= 5).astype(int)
df["Prep_Minutes"] = (df["Pickup_Time"] - df["Order_Time"]).dt.total_seconds() / 60

median_time = df["Delivery_Time"].median()
df["Delayed"] = (df["Delivery_Time"] > median_time).astype(int)
df.dropna(subset=["Delivery_Time", "Agent_Age", "Agent_Rating"], inplace=True)

with open(os.path.join(ROOT, "models", "model_info.json")) as f:
    config = json.load(f)

FEATURE_COLS = config["feature_cols"]
CAT_COLS = config["categorical_cols"]
THRESHOLD = config["optimal_threshold"]

df.dropna(subset=FEATURE_COLS, inplace=True)
for col in CAT_COLS:
    df[col] = df[col].astype(str)

X = df[FEATURE_COLS]
y = df["Delayed"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

model = CatBoostClassifier()
model.load_model(os.path.join(ROOT, "models", "catboost_delay_model.cbm"))
y_prob = model.predict_proba(X_test)[:, 1]
y_pred = (y_prob >= THRESHOLD).astype(int)

# ═══════════════════════════════════════════════════════════════════
# Figure 1: ROC Curve
# ═══════════════════════════════════════════════════════════════════
fpr, tpr, _ = roc_curve(y_test, y_prob)
roc_auc_val = auc(fpr, tpr)

fig, ax = plt.subplots(figsize=(6, 5))
ax.plot(fpr, tpr, color="#1e3a5f", lw=2.2, label=f"CatBoost (AUC = {roc_auc_val:.4f})")
ax.plot([0, 1], [0, 1], color="#aaaaaa", lw=1, ls="--", label="Random baseline")
ax.fill_between(fpr, tpr, alpha=0.08, color="#1e3a5f")
ax.set_xlabel("False Positive Rate")
ax.set_ylabel("True Positive Rate")
ax.set_title("ROC Curve — CatBoost Delay Classifier")
ax.legend(loc="lower right", frameon=True, fancybox=True, shadow=False)
ax.set_xlim([-0.02, 1.02])
ax.set_ylim([-0.02, 1.02])
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "roc_curve.png"))
plt.close()
print("Saved: roc_curve.png")

# ═══════════════════════════════════════════════════════════════════
# Figure 2: Precision-Recall Curve
# ═══════════════════════════════════════════════════════════════════
prec, rec, _ = precision_recall_curve(y_test, y_prob)
ap = average_precision_score(y_test, y_prob)

fig, ax = plt.subplots(figsize=(6, 5))
ax.plot(rec, prec, color="#2d6a9f", lw=2.2, label=f"CatBoost (AP = {ap:.4f})")
ax.fill_between(rec, prec, alpha=0.08, color="#2d6a9f")
ax.set_xlabel("Recall")
ax.set_ylabel("Precision")
ax.set_title("Precision-Recall Curve")
ax.legend(loc="upper right", frameon=True, fancybox=True, shadow=False)
ax.set_xlim([-0.02, 1.02])
ax.set_ylim([0, 1.05])
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "precision_recall_curve.png"))
plt.close()
print("Saved: precision_recall_curve.png")

# ═══════════════════════════════════════════════════════════════════
# Figure 3: Confusion Matrix Heatmap
# ═══════════════════════════════════════════════════════════════════
cm = confusion_matrix(y_test, y_pred)
fig, ax = plt.subplots(figsize=(5.5, 4.5))
im = ax.imshow(cm, cmap="Blues", aspect="auto")

labels = [["True Negative\n(On-Time → On-Time)", "False Positive\n(On-Time → Delayed)"],
          ["False Negative\n(Delayed → On-Time)", "True Positive\n(Delayed → Delayed)"]]

for i in range(2):
    for j in range(2):
        color = "white" if cm[i, j] > cm.max() * 0.6 else "black"
        ax.text(j, i, f"{cm[i, j]:,}\n{labels[i][j]}", ha="center", va="center",
                fontsize=10, color=color, fontweight="bold")

ax.set_xticks([0, 1])
ax.set_yticks([0, 1])
ax.set_xticklabels(["On-Time", "Delayed"])
ax.set_yticklabels(["On-Time", "Delayed"])
ax.set_xlabel("Predicted Label")
ax.set_ylabel("Actual Label")
ax.set_title(f"Confusion Matrix (Threshold = {THRESHOLD})")
plt.colorbar(im, ax=ax, shrink=0.8)
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "confusion_matrix.png"))
plt.close()
print("Saved: confusion_matrix.png")

# ═══════════════════════════════════════════════════════════════════
# Figure 4: Class Distribution
# ═══════════════════════════════════════════════════════════════════
counts = df["Delayed"].value_counts().sort_index()
fig, ax = plt.subplots(figsize=(5, 4))
bars = ax.bar(["On-Time", "Delayed"], [counts[0], counts[1]],
              color=["#16a34a", "#dc2626"], width=0.5, edgecolor="white", linewidth=1.5)
for bar, val in zip(bars, [counts[0], counts[1]]):
    pct = val / len(df) * 100
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 200,
            f"{val:,}\n({pct:.1f}%)", ha="center", va="bottom", fontsize=10, fontweight="bold")
ax.set_ylabel("Number of Orders")
ax.set_title("Target Variable Distribution")
ax.set_ylim(0, max(counts) * 1.2)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "class_distribution.png"))
plt.close()
print("Saved: class_distribution.png")

# ═══════════════════════════════════════════════════════════════════
# Figure 5: Delay Rate by Traffic Level
# ═══════════════════════════════════════════════════════════════════
traffic_order = ["Low", "Medium", "High", "Jam"]
traffic_rates = df.groupby("Traffic")["Delayed"].mean().reindex(traffic_order)
traffic_counts = df.groupby("Traffic")["Delayed"].count().reindex(traffic_order)

fig, ax = plt.subplots(figsize=(6, 4.5))
colors = ["#16a34a", "#f59e0b", "#ea580c", "#dc2626"]
bars = ax.bar(traffic_order, traffic_rates * 100, color=colors, width=0.55, edgecolor="white", linewidth=1.5)
for bar, rate, cnt in zip(bars, traffic_rates, traffic_counts):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.8,
            f"{rate*100:.1f}%\n(n={cnt:,})", ha="center", va="bottom", fontsize=9)
ax.set_ylabel("Delay Rate (%)")
ax.set_xlabel("Traffic Level")
ax.set_title("Delay Rate by Traffic Condition")
ax.set_ylim(0, max(traffic_rates * 100) * 1.25)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "delay_by_traffic.png"))
plt.close()
print("Saved: delay_by_traffic.png")

# ═══════════════════════════════════════════════════════════════════
# Figure 6: Delay Rate by Weather
# ═══════════════════════════════════════════════════════════════════
weather_order = ["Sunny", "Cloudy", "Windy", "Fog", "Stormy", "Sandstorms"]
weather_rates = df.groupby("Weather")["Delayed"].mean().reindex(weather_order).dropna()
weather_counts = df.groupby("Weather")["Delayed"].count().reindex(weather_order).dropna()

fig, ax = plt.subplots(figsize=(7, 4.5))
cmap = plt.cm.YlOrRd(np.linspace(0.2, 0.85, len(weather_rates)))
bars = ax.bar(weather_rates.index, weather_rates * 100, color=cmap, width=0.55, edgecolor="white", linewidth=1.5)
for bar, rate, cnt in zip(bars, weather_rates, weather_counts):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
            f"{rate*100:.1f}%\n(n={cnt:,})", ha="center", va="bottom", fontsize=9)
ax.set_ylabel("Delay Rate (%)")
ax.set_xlabel("Weather Condition")
ax.set_title("Delay Rate by Weather Condition")
ax.set_ylim(0, max(weather_rates * 100) * 1.25)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "delay_by_weather.png"))
plt.close()
print("Saved: delay_by_weather.png")

# ═══════════════════════════════════════════════════════════════════
# Figure 7: Distance Distribution (Delayed vs On-Time)
# ═══════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(6, 4.5))
ax.hist(df[df["Delayed"]==0]["Distance_km"], bins=50, alpha=0.65, color="#16a34a",
        label="On-Time", density=True, edgecolor="white", linewidth=0.5)
ax.hist(df[df["Delayed"]==1]["Distance_km"], bins=50, alpha=0.65, color="#dc2626",
        label="Delayed", density=True, edgecolor="white", linewidth=0.5)
ax.set_xlabel("Distance (km)")
ax.set_ylabel("Density")
ax.set_title("Distance Distribution: Delayed vs On-Time")
ax.legend(frameon=True, fancybox=True)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "distance_distribution.png"))
plt.close()
print("Saved: distance_distribution.png")

# ═══════════════════════════════════════════════════════════════════
# Figure 8: Model Comparison Bar Chart
# ═══════════════════════════════════════════════════════════════════
models = ["Logistic\nRegression", "XGBoost", "CatBoost\n(Final)"]
auc_vals = [0.76, 0.95, 0.9526]
f1_vals = [0.67, 0.78, 0.781]
recall_vals = [0.69, 0.86, 0.895]

x = np.arange(len(models))
w = 0.22
fig, ax = plt.subplots(figsize=(7, 4.5))
b1 = ax.bar(x - w, auc_vals, w, label="ROC-AUC", color="#1e3a5f", edgecolor="white")
b2 = ax.bar(x, f1_vals, w, label="F1 (Delayed)", color="#2d6a9f", edgecolor="white")
b3 = ax.bar(x + w, recall_vals, w, label="Recall", color="#60a5fa", edgecolor="white")
for bars in [b1, b2, b3]:
    for bar in bars:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                f"{bar.get_height():.2f}", ha="center", va="bottom", fontsize=8.5, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(models)
ax.set_ylabel("Score")
ax.set_title("Model Comparison — Key Metrics")
ax.set_ylim(0, 1.12)
ax.legend(loc="upper left", frameon=True, fancybox=True)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "model_comparison.png"))
plt.close()
print("Saved: model_comparison.png")

# ═══════════════════════════════════════════════════════════════════
# Figure 9: Probability Distribution (Delayed vs On-Time)
# ═══════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(6, 4.5))
ax.hist(y_prob[y_test==0], bins=50, alpha=0.65, color="#16a34a",
        label="Actual On-Time", density=True, edgecolor="white", linewidth=0.5)
ax.hist(y_prob[y_test==1], bins=50, alpha=0.65, color="#dc2626",
        label="Actual Delayed", density=True, edgecolor="white", linewidth=0.5)
ax.axvline(THRESHOLD, color="#854d0e", ls="--", lw=2, label=f"Threshold = {THRESHOLD}")
ax.set_xlabel("Predicted Delay Probability")
ax.set_ylabel("Density")
ax.set_title("Score Distribution by True Class")
ax.legend(frameon=True, fancybox=True)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "score_distribution.png"))
plt.close()
print("Saved: score_distribution.png")

print("\nAll figures generated successfully!")
