#!/bin/bash
# ==============================================================================
# ParkVisionSaathi - Pipeline & Server Startup Script
# ==============================================================================

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚔 Starting ParkVisionSaathi Setup and Run Script...${NC}"

# 1. Setup Virtual Environment
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}📦 Creating Python virtual environment (.venv)...${NC}"
    python3 -m venv .venv
else
    echo -e "${GREEN}✓ Virtual environment .venv already exists.${NC}"
fi

# Activate virtual environment
echo -e "${YELLOW}🔌 Activating virtual environment...${NC}"
source .venv/bin/activate

# 2. Install Dependencies
echo -e "${YELLOW}📥 Installing dependencies from requirements.txt...${NC}"
pip install --upgrade pip
pip install -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed successfully.${NC}"

# Disable user-site packages to prevent sandbox or system permission errors
export PYTHONNOUSERSITE=1

# 3. Ask user about running ETL and ML models
echo -e "${BLUE}⚙️ Do you want to process the raw data and train/run the ML models? (y/n)${NC}"
read -p "Select choice [y]: " run_ml
run_ml=${run_ml:-y}

if [ "$run_ml" = "y" ] || [ "$run_ml" = "Y" ]; then
    echo -e "${YELLOW}📁 Running Data ETL / Cleaning Pipeline...${NC}"
    python -m data.load_and_clean

    echo -e "${YELLOW}🗺️ Running Hotspot DBSCAN Clustering...${NC}"
    python -m ml.hotspot_dbscan

    echo -e "${YELLOW}⚠️ Computing Risk Scores...${NC}"
    python -m ml.risk_score

    echo -e "${YELLOW}♟️ Running Stackelberg Mixed-Strategy Patrol Optimization...${NC}"
    python -m ml.game.stackelberg

    echo -e "${YELLOW}🌊 Simulating Spillover (Waterbed) Effect...${NC}"
    python -m ml.game.spillover

    echo -e "${YELLOW}🎯 Modeling Violator Expected Utility & Adaptation...${NC}"
    python -m ml.game.expected_utility

    echo -e "${YELLOW}📈 Generating Forecasting Features...${NC}"
    python -m ml.forecast.feature_engineering

    echo -e "${YELLOW}🤖 Training LightGBM Forecasting Model...${NC}"
    python -m ml.forecast.train_model

    echo -e "${GREEN}✓ ML Ingestion and Training Complete!${NC}"
else
    echo -e "${YELLOW}⏭️ Skipping ML/ETL pipeline step (using pre-existing database).${NC}"
fi

# 4. Start FastAPI Backend Server
echo -e "${GREEN}🚀 Starting ParkVisionSaathi FastAPI Backend Server on port 8000...${NC}"
echo -e "${BLUE}💡 Open http://localhost:8000/dashboard/ in your browser to view the application.${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop the server.${NC}"

uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
