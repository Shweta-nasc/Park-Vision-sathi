#!/bin/bash
# ==============================================================================
# ParkVision-Saathi — local setup & run (backend, JSON + in-memory, NO database)
# ==============================================================================
# This sets up a venv, installs deps, OPTIONALLY regenerates the data artifacts
# from the raw CSV, then starts the FastAPI backend. Deployment does NOT use this
# script — see the README "Deploy on Render" section.
# ==============================================================================

set -e

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${BLUE}🚦 ParkVision-Saathi — setup & run${NC}"

# 1. Virtual environment (repo standard: ./venv)
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}📦 Creating virtual environment (venv)...${NC}"
    python3 -m venv venv
else
    echo -e "${GREEN}✓ venv already exists.${NC}"
fi
# shellcheck disable=SC1091
source venv/bin/activate
export PYTHONNOUSERSITE=1

# 2. Dependencies
#    Full requirements (pandas/h3/ml) are only needed to REGENERATE artifacts.
#    To just serve the API you can instead: pip install -r requirements-backend.txt
echo -e "${YELLOW}📥 Installing dependencies (requirements.txt)...${NC}"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

# 3. Optionally (re)generate the data artifacts the backend serves.
#    Needs the raw violations CSV (git-ignored, local only); run_pipeline.py
#    exits cleanly with guidance if it's missing.
echo -e "${BLUE}⚙️  Regenerate data artifacts from the raw CSV? (needs dataset/*.csv) [y/N]${NC}"
read -p "Select choice [N]: " regen
regen=${regen:-N}
if [ "$regen" = "y" ] || [ "$regen" = "Y" ]; then
    echo -e "${YELLOW}🧮 Running data artifact pipeline (rekey → CIS artifact → agent)...${NC}"
    python run_pipeline.py
else
    echo -e "${YELLOW}⏭️  Using the committed JSON artifacts (no regeneration).${NC}"
fi

# 4. Start the FastAPI backend. Honors $PORT (Render-style) and defaults to 8000.
PORT="${PORT:-8000}"
echo -e "${GREEN}🚀 Starting FastAPI backend on port ${PORT}...${NC}"
echo -e "${BLUE}   API docs:  http://localhost:${PORT}/docs${NC}"
echo -e "${BLUE}   Health:    http://localhost:${PORT}/health${NC}"
echo -e "${BLUE}   Dashboard: http://localhost:${PORT}/dashboard/${NC}"
exec uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT}" --reload
