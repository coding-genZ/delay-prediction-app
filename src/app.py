"""
Streamlit UI for Shipment Delay Prediction.
Calls the local FastAPI server at http://127.0.0.1:8000/predict.
"""
import logging
import streamlit as st
import requests

from aws_config import setup_cloudwatch_logging

setup_cloudwatch_logging()
logger = logging.getLogger("shipment_delay.ui")

import os

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
API_URL = f"{API_BASE}/predict"
FEEDBACK_URL = f"{API_BASE}/feedback"

st.set_page_config(
    page_title="Shipment Delay Prediction",
    page_icon="📦",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* Global */
    .block-container { padding-top: 2rem; max-width: 1200px; }
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* Header */
    .app-header {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d6a9f 100%);
        padding: 2rem 2.5rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .app-header h1 { margin: 0; font-size: 1.8rem; font-weight: 700; color: white; }
    .app-header p  { margin: 0.4rem 0 0 0; font-size: 0.95rem; opacity: 0.85; }

    /* Section cards */
    .section-card {
        background: #ffffff;
        border: 1px solid #e8ecf1;
        border-radius: 10px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .section-title {
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #64748b;
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #e2e8f0;
    }

    /* Result cards */
    .result-card {
        border-radius: 10px;
        padding: 1.2rem 1.5rem;
        text-align: center;
        border: 1px solid #e8ecf1;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .result-card .label {
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.3rem;
    }
    .result-card .value { font-size: 1.8rem; font-weight: 700; }

    .card-prob        { background: #f0f4ff; }
    .card-prob .label { color: #4361ee; }
    .card-prob .value { color: #1e3a5f; }

    .card-risk-delayed        { background: #fff0f0; border-color: #fecaca; }
    .card-risk-delayed .label { color: #dc2626; }
    .card-risk-delayed .value { color: #dc2626; }

    .card-risk-ontime        { background: #f0fdf4; border-color: #bbf7d0; }
    .card-risk-ontime .label { color: #16a34a; }
    .card-risk-ontime .value { color: #16a34a; }

    .card-threshold        { background: #fefce8; }
    .card-threshold .label { color: #a16207; }
    .card-threshold .value { color: #854d0e; }

    /* Risk bar */
    .risk-bar-container {
        background: #f1f5f9;
        border-radius: 10px;
        height: 12px;
        width: 100%;
        margin: 0.5rem 0;
        overflow: hidden;
    }
    .risk-bar-fill {
        height: 100%;
        border-radius: 10px;
        transition: width 0.5s ease;
    }

    /* Action box */
    .action-box {
        padding: 1rem 1.2rem;
        border-radius: 8px;
        font-size: 0.95rem;
        font-weight: 500;
        margin-top: 0.5rem;
    }
    .action-high    { background: #fef2f2; border-left: 4px solid #dc2626; color: #991b1b; }
    .action-medium  { background: #fffbeb; border-left: 4px solid #f59e0b; color: #92400e; }
    .action-low     { background: #f0fdf4; border-left: 4px solid #16a34a; color: #166534; }

    /* Driver table */
    .driver-table { width: 100%; border-collapse: separate; border-spacing: 0; }
    .driver-table th {
        background: #f8fafc;
        padding: 0.7rem 1rem;
        text-align: left;
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: #64748b;
        border-bottom: 2px solid #e2e8f0;
    }
    .driver-table td {
        padding: 0.8rem 1rem;
        border-bottom: 1px solid #f1f5f9;
        font-size: 0.9rem;
    }
    .driver-table tr:last-child td { border-bottom: none; }
    .driver-table tr:hover td { background: #f8fafc; }
    .badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
    }
    .badge-up   { background: #fef2f2; color: #dc2626; }
    .badge-down { background: #f0fdf4; color: #16a34a; }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e3a5f 0%, #1a2f4a 100%);
    }
    section[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
    section[data-testid="stSidebar"] .stRadio label { color: #e2e8f0 !important; }
    section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.15); }

    /* Model stats in sidebar */
    .sidebar-stat {
        background: rgba(255,255,255,0.08);
        border-radius: 8px;
        padding: 0.7rem 0.9rem;
        margin-bottom: 0.5rem;
    }
    .sidebar-stat .stat-label { font-size: 0.72rem; opacity: 0.7; text-transform: uppercase; letter-spacing: 0.04em; }
    .sidebar-stat .stat-value { font-size: 1.1rem; font-weight: 700; }

    /* About page */
    .metric-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 1rem;
        margin: 1rem 0;
    }
    .metric-item {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
    }
    .metric-item .m-value { font-size: 1.6rem; font-weight: 700; color: #1e3a5f; }
    .metric-item .m-label { font-size: 0.78rem; color: #64748b; margin-top: 0.2rem; }

    /* Weather banner */
    .weather-banner {
        background: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 100%);
        border: 1px solid #bae6fd;
        border-radius: 8px;
        padding: 0.8rem 1.2rem;
        margin: 0.8rem 0;
        display: flex;
        align-items: center;
        gap: 0.8rem;
        font-size: 0.88rem;
        color: #0c4a6e;
    }
    .weather-banner .wb-icon { font-size: 1.4rem; }
    .weather-banner .wb-detail { opacity: 0.75; font-size: 0.8rem; }

    /* Feedback section */
    .feedback-card {
        background: #fafbfc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1.5rem;
        margin-top: 1rem;
    }
    .feedback-title {
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #64748b;
        margin-bottom: 0.8rem;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #e2e8f0;
    }

    /* Hide Streamlit defaults */
    .stDeployButton, #MainMenu { display: none; }
    footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 📦 Delay Predictor")
    st.markdown("---")

    st.markdown("""
    <div class="sidebar-stat"><div class="stat-label">Model</div><div class="stat-value">CatBoost</div></div>
    <div class="sidebar-stat"><div class="stat-label">ROC-AUC</div><div class="stat-value">0.9526</div></div>
    <div class="sidebar-stat"><div class="stat-label">Threshold</div><div class="stat-value">0.26</div></div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    view = st.radio(
        "Navigation",
        ["Single Order Scorer", "About the Model"],
        index=0,
        label_visibility="collapsed",
    )

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("""
<div class="app-header">
    <h1>Shipment Delay Prediction System</h1>
    <p>ML-powered risk alerting for dispatch operations</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Single Order Scorer
# ---------------------------------------------------------------------------
if view == "Single Order Scorer":

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown('<div class="section-card"><div class="section-title">Courier Details</div>', unsafe_allow_html=True)
        agent_age = st.number_input("Courier age", min_value=18, max_value=70, value=32, step=1)
        agent_rating = st.slider("Courier rating", 1.0, 5.0, 4.5, step=0.1)
        vehicle = st.selectbox("Vehicle", ["motorcycle", "scooter", "van", "bicycle"])
        st.markdown('</div>', unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="section-card"><div class="section-title">Route Information</div>', unsafe_allow_html=True)
        store_lat = st.number_input("Store latitude", value=22.745049, format="%.6f")
        store_lon = st.number_input("Store longitude", value=75.892471, format="%.6f")
        drop_lat = st.number_input("Drop latitude", value=22.765049, format="%.6f")
        drop_lon = st.number_input("Drop longitude", value=75.912471, format="%.6f")
        area = st.selectbox("Area", ["Metropolitian", "Urban", "Semi-Urban", "Other"])
        st.markdown('</div>', unsafe_allow_html=True)

    with col3:
        st.markdown('<div class="section-card"><div class="section-title">Conditions & Timing</div>', unsafe_allow_html=True)
        weather = st.selectbox("Weather", ["Sunny", "Cloudy", "Fog", "Windy", "Stormy", "Sandstorms"])
        traffic = st.selectbox("Traffic", ["Low", "Medium", "High", "Jam"])
        pickup_hour = st.slider("Pickup hour (24h)", 0, 23, 14)
        day_of_week = st.selectbox(
            "Day of week",
            options=[0, 1, 2, 3, 4, 5, 6],
            format_func=lambda x: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][x],
            index=2,
        )
        prep_minutes = st.number_input("Prep time (min)", min_value=0, max_value=120, value=10)
        category = st.selectbox(
            "Product category",
            ["Electronics", "Clothing", "Grocery", "Cosmetics", "Toys", "Snacks",
             "Shoes", "Apparel", "Jewelry", "Outdoors", "Kitchen", "Books",
             "Sports", "Home", "Pet Supplies", "Skincare"],
        )
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("")
    predict_btn = st.button("Predict Delay Risk", type="primary", use_container_width=True)

    if predict_btn:
        payload = {
            "Agent_Age": int(agent_age),
            "Agent_Rating": float(agent_rating),
            "Store_Latitude": float(store_lat),
            "Store_Longitude": float(store_lon),
            "Drop_Latitude": float(drop_lat),
            "Drop_Longitude": float(drop_lon),
            "Pickup_Hour": int(pickup_hour),
            "Day_of_Week": int(day_of_week),
            "Prep_Minutes": float(prep_minutes),
            "Weather": weather,
            "Traffic": traffic,
            "Vehicle": vehicle,
            "Area": area,
            "Category": category,
        }
        try:
            logger.info("Sending prediction request for courier_age=%s traffic=%s", agent_age, traffic)
            with st.spinner("Running model..."):
                r = requests.post(API_URL, json=payload, timeout=120)
                r.raise_for_status()
                st.session_state["prediction_result"] = r.json()
            logger.info("Prediction received: prob=%.4f risk=%s", st.session_state["prediction_result"]["delay_probability"], st.session_state["prediction_result"]["risk_label"])
        except requests.exceptions.ConnectionError:
            logger.error("API connection failed at %s", API_URL)
            st.error(
                "Could not reach the API at http://127.0.0.1:8000. "
                "Make sure the FastAPI server is running in another terminal."
            )
        except Exception as e:
            logger.error("Prediction request failed: %s", e, exc_info=True)
            st.error(f"Error: {e}")

    if "prediction_result" in st.session_state:
        result = st.session_state["prediction_result"]
        prob = result["delay_probability"]
        risk = result["risk_label"]
        pct = f"{prob * 100:.1f}%"

        # --- Result cards ---
        risk_class = "card-risk-delayed" if risk == "DELAYED" else "card-risk-ontime"
        risk_icon = "⚠️" if risk == "DELAYED" else "✅"

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"""
            <div class="result-card card-prob">
                <div class="label">Delay Probability</div>
                <div class="value">{pct}</div>
            </div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""
            <div class="result-card {risk_class}">
                <div class="label">Risk Flag</div>
                <div class="value">{risk_icon} {risk}</div>
            </div>""", unsafe_allow_html=True)
        with c3:
            st.markdown(f"""
            <div class="result-card card-threshold">
                <div class="label">Decision Threshold</div>
                <div class="value">{result['threshold']:.2f}</div>
            </div>""", unsafe_allow_html=True)

        # --- Risk bar ---
        if prob >= 0.60:
            bar_color = "#dc2626"
        elif prob >= 0.26:
            bar_color = "#f59e0b"
        else:
            bar_color = "#16a34a"

        st.markdown(f"""
        <div style="margin: 1rem 0 0.3rem 0;">
            <div style="display: flex; justify-content: space-between; font-size: 0.78rem; color: #94a3b8; margin-bottom: 0.3rem;">
                <span>Low Risk</span><span>High Risk</span>
            </div>
            <div class="risk-bar-container">
                <div class="risk-bar-fill" style="width: {prob * 100}%; background: {bar_color};"></div>
            </div>
        </div>""", unsafe_allow_html=True)

        # --- Action box ---
        action_text = result["suggested_action"]
        if prob >= 0.60:
            action_class = "action-high"
            action_icon = "🚨"
        elif prob >= 0.26:
            action_class = "action-medium"
            action_icon = "⚡"
        else:
            action_class = "action-low"
            action_icon = "👍"

        st.markdown(f"""
        <div class="action-box {action_class}">
            {action_icon} &nbsp; <strong>Recommended Action:</strong> {action_text}
        </div>""", unsafe_allow_html=True)

        st.markdown("")

        # --- SHAP drivers table ---
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Top Risk Factors (SHAP Explanation)</div>', unsafe_allow_html=True)

        drivers = result["top_drivers"]
        table_rows = ""
        for d in drivers:
            badge_class = "badge-up" if d["direction"] == "increases" else "badge-down"
            arrow = "↑ Increases risk" if d["direction"] == "increases" else "↓ Decreases risk"
            shap_val = f"{d['shap_value']:+.3f}"
            table_rows += f"""
            <tr>
                <td><strong>{d['feature']}</strong></td>
                <td>{d['value']}</td>
                <td><span class="badge {badge_class}">{arrow}</span></td>
                <td style="font-family: monospace; font-weight: 600;">{shap_val}</td>
            </tr>"""

        st.markdown(f"""
        <table class="driver-table">
            <thead><tr>
                <th>Feature</th><th>Value</th><th>Impact</th><th>SHAP Value</th>
            </tr></thead>
            <tbody>{table_rows}</tbody>
        </table>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # --- Live weather banner ---
        live_weather = result.get("live_weather")
        if live_weather:
            w_label = live_weather.get("weather_label", "")
            p_temp = live_weather.get("pickup_temp_c", "?")
            d_temp = live_weather.get("dropoff_temp_c", "?")
            p_wind = live_weather.get("pickup_wind_speed", "?")
            p_vis = live_weather.get("pickup_visibility_m", 10000)
            vis_km = round(p_vis / 1000, 1) if isinstance(p_vis, (int, float)) else "?"
            st.markdown(f"""
            <div class="weather-banner">
                <span class="wb-icon">🌤️</span>
                <div>
                    <strong>Live weather:</strong> {w_label} &nbsp;|&nbsp;
                    Pickup {p_temp}°C &nbsp;|&nbsp; Drop-off {d_temp}°C &nbsp;|&nbsp;
                    Wind {p_wind} m/s &nbsp;|&nbsp; Visibility {vis_km} km
                    <div class="wb-detail">Weather automatically fetched from OpenWeatherMap for the route coordinates</div>
                </div>
            </div>""", unsafe_allow_html=True)

        # --- Feedback form ---
        prediction_id = result.get("prediction_id")
        st.markdown("")
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Dispatcher Feedback</div>', unsafe_allow_html=True)
        st.markdown("Record what action you took and the actual outcome. This data feeds the next model version.", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        fb_col1, fb_col2 = st.columns(2)
        with fb_col1:
            dispatcher_action = st.selectbox(
                "Action taken",
                ["no_action", "reassigned_courier", "notified_customer",
                 "adjusted_route", "escalated", "other"],
                key="fb_action",
            )
        with fb_col2:
            actual_outcome = st.selectbox(
                "Actual delivery outcome",
                ["pending", "delivered_on_time", "delivered_late",
                 "cancelled", "returned"],
                key="fb_outcome",
            )
        fb_notes = st.text_input("Notes (optional)", key="fb_notes", placeholder="e.g. Customer reported late arrival")

        if st.button("Submit Feedback", key="fb_submit"):
            if not prediction_id:
                st.warning("Feedback logging requires DynamoDB — prediction ID not available.")
            elif actual_outcome == "pending":
                st.warning("Please select the actual delivery outcome before submitting.")
            else:
                try:
                    fb_resp = requests.post(FEEDBACK_URL, json={
                        "prediction_id": prediction_id,
                        "dispatcher_action": dispatcher_action,
                        "actual_outcome": actual_outcome,
                        "notes": fb_notes,
                    }, timeout=10)
                    fb_resp.raise_for_status()
                    st.success(f"Feedback recorded for prediction {prediction_id[:8]}...")
                    logger.info("Feedback submitted for %s", prediction_id)
                except Exception as e:
                    logger.error("Feedback submission failed: %s", e)
                    st.error(f"Could not submit feedback: {e}")

        with st.expander("View raw API response"):
            st.json(result)

# ---------------------------------------------------------------------------
# About the Model
# ---------------------------------------------------------------------------
else:
    st.markdown("""
    <div class="metric-grid">
        <div class="metric-item"><div class="m-value">0.9526</div><div class="m-label">ROC-AUC Score</div></div>
        <div class="metric-item"><div class="m-value">0.78</div><div class="m-label">F1 Score (Delayed)</div></div>
        <div class="metric-item"><div class="m-value">0.26</div><div class="m-label">Optimal Threshold</div></div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Model Overview</div>', unsafe_allow_html=True)
        st.markdown("""
**Algorithm:** CatBoost classifier

**Training data:** 40,046 orders from the Amazon Delivery Dataset

**Cross-validation:** 5-fold CV ROC-AUC 0.9517 ± 0.0025 (stable, not overfit)

**Cost-sensitive threshold:** Minimizes total business cost using \\$20 per
missed delay and \\$8 per false alarm. The optimal threshold of **0.26** reduces
total cost by **18.6%** vs. the default 0.50 cutoff.
        """)
        st.markdown('</div>', unsafe_allow_html=True)

    with col_b:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Data Caveat</div>', unsafe_allow_html=True)
        st.markdown("""
Some categorical features (Weather, Category) show near-uniform distributions,
suggesting synthetic label generation in the source dataset.

Absolute performance numbers should be interpreted with this in mind. The
model's value is in **rank-ordering risk** for dispatcher prioritization, not
in the precise probability calibration.

**Top global features (mean |SHAP|):** Traffic, Agent Age, Agent Rating,
Weather, Vehicle, Distance.
        """)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("")
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Evaluation Figures</div>', unsafe_allow_html=True)
    fig1, fig2 = st.columns(2)
    try:
        with fig1:
            st.image(os.path.join(os.path.dirname(__file__), "..", "figures", "threshold_cost_curve.png"), caption="Cost-sensitive threshold optimization")
        with fig2:
            st.image(os.path.join(os.path.dirname(__file__), "..", "figures", "shap_importance_bar.png"), caption="Global feature importance (SHAP)")
    except Exception:
        st.info("Figures not found in folder.")
    st.markdown('</div>', unsafe_allow_html=True)
