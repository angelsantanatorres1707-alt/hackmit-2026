#!/usr/bin/env bash
# Set up everything Manim needs to render in this container.
#
#   bash scripts/setup.sh
#
# Idempotent: safe to re-run. Takes ~60s cold, ~5s warm.
# Deliberately does NOT install LaTeX -- see docs/RENDERING.md. Our scenes are
# LaTeX-free and a texlive install costs gigabytes and many minutes.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/.venv"

echo "==> Installing system packages (ffmpeg + cairo/pango for manim)"
export DEBIAN_FRONTEND=noninteractive
SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

$SUDO apt-get update -qq
$SUDO apt-get install -y -qq \
  ffmpeg \
  libcairo2-dev \
  libpango1.0-dev \
  pkg-config \
  python3-dev \
  build-essential

echo "==> ffmpeg: $(ffmpeg -version 2>/dev/null | head -1)"

echo "==> Creating venv at $VENV"
if command -v uv >/dev/null 2>&1; then
  uv venv --python 3.11 "$VENV"
  uv pip install --python "$VENV/bin/python" manim
else
  echo "    (uv not found, falling back to pip -- this is ~10x slower)"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip
  "$VENV/bin/pip" install manim
fi

echo "==> Verifying"
"$VENV/bin/manim" --version

# Smoke-test the real scene end to end. Fails loudly if anything is missing.
echo "==> Rendering de-risk scene (should take ~3s)"
cd "$REPO_ROOT"
time "$VENV/bin/manim" -ql --disable_caching \
  backend/scenes/_derisk_test.py DeriskSideBySide

OUT="$REPO_ROOT/media/videos/_derisk_test/480p15/DeriskSideBySide.mp4"
if [ -f "$OUT" ]; then
  echo "==> OK. Wrote $OUT ($(stat -c%s "$OUT") bytes)"
else
  echo "==> FAILED: expected output not found at $OUT" >&2
  exit 1
fi

echo
echo "Done. Activate with:  source $VENV/bin/activate"
echo "See docs/RENDERING.md for flags, timings and gotchas."
