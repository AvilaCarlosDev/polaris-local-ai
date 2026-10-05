#!/usr/bin/env bash
# Render the FLOATING ISLAND MIRAGE voxel hero (frames + MP4) on this machine.
# Everything runs locally: no cloud, no API. Needs python3 with Pillow and ffmpeg.
#
#   scripts/hero-scene.sh [outdir]     # default /opt/ia/hero
#   FRAMES=300 scripts/hero-scene.sh   # shorter preview
set -euo pipefail

cd "$(dirname "$0")/.."
out=${1:-/opt/ia/hero}
frames=${FRAMES:-870}

mkdir -p "$out/frames"
python3 scripts/hero-scene.py --range 0 "$((frames - 1))" --outdir "$out/frames"
ffmpeg -y -loglevel error -framerate 30 -i "$out/frames/f%04d.png" \
  -c:v libx264 -pix_fmt yuv420p -crf 22 -movflags +faststart "$out/hero-scene.mp4"
ffmpeg -y -loglevel error -framerate 30 -i "$out/frames/f%04d.png" \
  -vf scale=1280:720 -c:v libx264 -pix_fmt yuv420p -crf 27 \
  -movflags +faststart "$out/hero-scene-720.mp4"
ffmpeg -y -loglevel error -i "$out/hero-scene.mp4" -ss 00:00:14 -frames:v 1 \
  -vf scale=720:-1 -quality 82 "$out/hero-scene-preview.webp"
echo "wrote $out/hero-scene.mp4, $out/hero-scene-720.mp4, $out/hero-scene-preview.webp"
