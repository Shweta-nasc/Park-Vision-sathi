"""
ParkVisionSaathi – FastAPI Application Entry Point
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from backend.app.routers import risk, forecast, game, simulate, heatmap, stations, explain, traffic, agent

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(
    title="ParkVisionSaathi API",
    description="Traffic violation analytics, risk scoring, game-theory patrol optimization, and forecasting.",
    version="1.0.0",
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(risk.router, tags=["Risk & Hotspots"])
app.include_router(forecast.router, tags=["Forecasting"])
app.include_router(game.router, tags=["Game Theory"])
app.include_router(simulate.router, tags=["Simulation"])
app.include_router(heatmap.router, tags=["Heatmap"])
app.include_router(stations.router, tags=["Stations"])
app.include_router(explain.router, tags=["Explanations"])
app.include_router(traffic.router, tags=["Traffic Context"])
app.include_router(agent.router, tags=["Agent"])


@app.get("/", tags=["Health"])
def root():
    return {
        "service": "ParkVisionSaathi API",
        "version": "1.0.0",
        "endpoints": [
            "/hotspots", "/risk", "/forecast/zones",
            "/game/stackelberg_strategy", "/game/violator_adaptation",
            "/game/spillover_forecast", "/simulate", "/heatmap",
            "/explain", "/traffic/{zone_id}"
        ]
    }



@app.get("/health", tags=["Health"])
def health():
    from backend.app.db import table_exists
    tables = ["violations", "risk_scores", "game_stackelberg",
              "game_violator_adaptation", "game_spillover"]
    status = {t: table_exists(t) for t in tables}
    return {"status": "ok", "tables": status}


# ── Static Frontend ──────────────────────────────────────────────────────────
# Mount AFTER all API routes so /dashboard serves the frontend
app.mount("/dashboard", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
