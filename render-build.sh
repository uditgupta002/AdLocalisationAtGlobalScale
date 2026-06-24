#!/usr/bin/env bash
# exit on error
set -o errexit

echo "============================================="
echo "🐝 Building OmniSwarm Environment"
echo "============================================="

# 1. Install Python Dependencies
echo "Installing Python requirements..."
pip install --upgrade pip
pip install -r requirements.txt

# 2. Install FFmpeg (Static Build) if not present
# Render native python environments do not have apt-get sudo access.
echo "Setting up FFmpeg..."
mkdir -p bin

if ! command -v ffmpeg &> /dev/null; then
    echo "FFmpeg not found globally, downloading static build..."
    wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
    tar -xf ffmpeg-release-amd64-static.tar.xz
    # Move binaries to our local bin folder
    cp ffmpeg-*-static/ffmpeg bin/
    cp ffmpeg-*-static/ffprobe bin/
    rm -rf ffmpeg-*-static*
    echo "FFmpeg installed to /opt/render/project/src/bin"
else
    echo "FFmpeg is already available in the system."
fi

echo "Build complete! 🎉"
