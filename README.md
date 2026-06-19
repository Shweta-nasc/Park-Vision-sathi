# ParkVisionSaathi 🚔

**AI-powered patrol operations dashboard** for traffic violation management and intelligent police force deployment.

Built for the Smart India Hackathon — uses game theory, ML forecasting, and real-time risk analysis to optimize patrol routes across Bangalore's 54 police stations.

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-teal)

---

## Features

| Feature | Description |
|---------|-------------|
| **Hotspot Detection** | Time-aware DBSCAN clustering on lat/lon per hour bucket |
| **Risk Scoring** | 0–100 composite score (density, road importance, peak weight, repeat offenders, heavy vehicles) |
| **Game Theory** | Stackelberg patrol probability, violator adaptation (Expected Utility), spillover forecasting |
| **ML Forecasting** | LightGBM regressor with 22 engineered features (lag, rolling, calendar, spatial) |
| **Operations Dashboard** | Mappls map with heatmap overlays, priority area ranking, zone detail, AI chat assistant |
| **Station-based Workflow** | Select station → view jurisdiction data → dispatch to priority zones |

---

## Project Structure

```
Park-Vision-Sathi/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI entry point
│       ├── db.py                # SQLite connection helper
│       ├── models.py            # Pydantic response models
│       └── routers/
│           ├── risk.py          # /hotspots, /risk, /risk/top_zones
│           ├── forecast.py      # /forecast/zones
│           ├── game.py          # /game/stackelberg, /game/violator, /game/spillover
│           ├── heatmap.py       # /heatmap
│           ├── simulate.py      # /simulate
│           └── stations.py      # /stations, /stations/{name}/priority_areas
├── frontend/
│   ├── index.html               # Dashboard UI (Mappls SDK)
│   ├── styles.css               # Light theme, sea-green accent
│   └── app.js                   # Full application logic
├── ml/
│   ├── hotspot_dbscan.py        # Time-aware DBSCAN clustering
│   ├── risk_score.py            # Composite risk scoring engine
│   ├── game/
│   │   ├── stackelberg.py       # Patrol probability optimization
│   │   ├── expected_utility.py  # Violator adaptation modeling
│   │   └── spillover.py         # Waterbed effect forecasting
│   └── forecast/
│       ├── feature_engineering.py
│       └── train_model.py       # LightGBM training
├── data/
│   ├── load_and_clean.py        # CSV → SQLite loader
│   └── forecast_features.csv    # Engineered features
├── models/
│   ├── lightgbm_v1.pkl          # Trained model
│   └── MODEL_CARD.md            # Model documentation
├── scripts/
│   └── seed_db.py               # Database seeding utility
├── run_pipeline.py              # End-to-end ML pipeline runner
└── requirements.txt
```

---

## Quick Start

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the ML pipeline (first time only)

```bash
python3 run_pipeline.py
```

This runs DBSCAN → Risk Scoring → Game Theory → Forecasting and populates the SQLite database.

### 3. Start the API server

```bash
python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Open the dashboard

```
http://localhost:8000/dashboard/
```

Select a station → view map with heatmaps → drill into priority areas → use AI assistant.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | API health + DB table status |
| GET | `/stations` | List all 54 police stations |
| GET | `/stations/{name}/priority_areas` | Ranked zones with force + ETA |
| GET | `/stations/{name}/summary` | Zone count, high-risk count |
| GET | `/heatmap?hour=&type=` | Heatmap point data (risk/violator/spillover) |
| GET | `/risk/top_zones?hour=&n=` | Top N risk zones with full data |
| GET | `/hotspots?hour=` | DBSCAN cluster centroids |
| GET | `/risk?hour=` | All risk-scored grid cells |
| GET | `/game/stackelberg_strategy` | Patrol probability per zone |
| GET | `/game/violator_adaptation` | Violator risk scores |
| GET | `/game/spillover_forecast` | Spillover effect data |
| GET | `/forecast/zones?horizon=` | LightGBM violation forecasts |

---

## Configuration

### Mappls API Key

The dashboard uses MapmyIndia (Mappls) for map tiles. Set your API key in `frontend/index.html`:

```html
<script src="https://apis.mappls.com/advancedmaps/api/YOUR_KEY_HERE/map_sdk?..."></script>
```

Get a free key at [apis.mappls.com/console](https://apis.mappls.com/console/).

---

## Tech Stack

- **Backend:** Python 3.10+, FastAPI, SQLite, SQLAlchemy
- **ML:** scikit-learn (DBSCAN), LightGBM, scipy, numpy, pandas
- **Frontend:** Vanilla HTML/CSS/JS, Mappls SDK v3.0
- **Game Theory:** Stackelberg equilibrium, Expected Utility, Spillover modeling

---

## License

MIT
