#!/bin/bash
set -e

# Canva Content Swarm Dev Server Launcher
echo "============================================="
echo "🐝 Starting Canva Content Swarm Dev Servers 🐝"
echo "============================================="

# Ensure we are in virtual environment
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Add current workspace to python path to resolve import issues
export PYTHONPATH=$(pwd)

# Trap to kill all background processes on exit
trap "kill 0" EXIT

# Start FastAPI Webhook Server in the background
echo "Starting FastAPI webhook server on port 3001..."
uvicorn src.webhook:app --port 3001 &
WEBHOOK_PID=$!

# Wait a second for Webhook server to bind
sleep 1.5

# Start Streamlit Dashboard
echo "Starting Streamlit dashboard on port 3002..."
streamlit run src/dashboard.py --server.port 3002

# Keep script running
wait $WEBHOOK_PID
