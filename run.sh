#!/bin/bash
set -e

# OmniSwarm Worker Launcher
# The frontend now lives in web/ (Next.js on Vercel). This starts only the
# Python media-processing worker (FFmpeg + Demucs + Gemini) that the Vercel
# app triggers via POST /worker/run.
echo "============================================="
echo "🐝 Starting OmniSwarm Worker 🐝"
echo "============================================="

if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

export PYTHONPATH=$(pwd)

# Some Homebrew setups put a broken ffmpeg@6 (missing libvpx) first on PATH.
# Prefer an explicitly-set FFMPEG_BIN, otherwise fall back to the main keg.
if [ -z "${FFMPEG_BIN:-}" ] && [ -x "/opt/homebrew/bin/ffmpeg" ]; then
    export FFMPEG_BIN="/opt/homebrew/bin/ffmpeg"
fi
echo "Using ffmpeg: ${FFMPEG_BIN:-ffmpeg}"

PORT="${PORT:-3001}"
echo "Starting FastAPI worker on port ${PORT}..."
uvicorn src.webhook:app --host 0.0.0.0 --port "${PORT}"
