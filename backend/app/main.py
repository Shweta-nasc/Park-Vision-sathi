"""
ParkVision-Saathi — FastAPI Application Entry Point

Planner-aligned data layer: pre-computed JSON files loaded once into memory at
startup (EXECUTION_PLANNER L233/L378, MASTER_PLAN L629). No database.

Routes are mounted twice: bare paths (e.g. /heatmap) for the existing React
frontend's wire contract, and under /api (e.g. /api/heatmap) for the planner's
documented contract.
"""

from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Load a local .env (if present) so GEMINI_API_KEY etc. are available for the
# optional live-LLM tier during local runs. On Render, env vars come from the
# dashboard, so this is a no-op there. Guarded: python-dotenv is optional.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from backend.app.data_loader import store
from backend.app.routers import (risk, forecast, game, simulate, heatmap,
                                 stations, explain, traffic, agent)

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load all pre-computed JSON into memory once at startup (no DB, no network)."""
    store.load()
    yield


app = FastAPI(
    title="ParkVision-Saathi API",
    description="Congestion-impact analytics, game-theory patrol optimization, "
                "forecasting, and a self-validating agent — JSON + in-memory, no DB.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers: mount at bare paths AND under /api ──────────────────────────────
ROUTERS = [risk, forecast, game, simulate, heatmap, stations, explain, traffic, agent]
for r in ROUTERS:
    app.include_router(r.router)                 # frontend wire contract
    app.include_router(r.router, prefix="/api")  # planner contract


@app.get("/", tags=["Health"])
def root():
    return {
        "service": "ParkVision-Saathi API",
        "version": "2.0.0",
        "data_layer": "JSON + in-memory (no database)",
        "endpoints": [
            "/hotspots", "/risk/top_zones", "/risk/{zone_id}", "/heatmap",
            "/stations", "/forecast/top_risk_zones",
            "/game/stackelberg_strategy", "/game/violator_adaptation",
            "/game/spillover_arrows", "/simulate", "/explain",
            "/traffic/{zone_id}", "/agent/validation-report",
        ],
    }


@app.get("/health", tags=["Health"])
def health():
    store.ensure()
    return {
        "status": "ok",
        "data_layer": "json-in-memory",
        "zones_loaded": len(store.zones),
        "sources": store.sources,
        "calibration": store.calibration_meta,
        "headline_bucket": store.headline_bucket,
        "calibrated_bucket": store.calibration_meta.get("calibrated_bucket"),
        "agent": store.agent_summary,
    }


# ── Static frontend (vanilla dashboard served at /dashboard) ─────────────────
if FRONTEND_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
