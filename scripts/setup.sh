#!/usr/bin/env bash
# Install everything the app needs, on macOS or Debian/Ubuntu.
#
#   bash scripts/setup.sh
#
# Idempotent: safe to re-run. ~60s cold, ~5s warm.
#
# Deliberately does NOT install LaTeX. Every manim Matrix class shells out to
# `latex` (even for the brackets), so the scenes build matrices out of Text
# instead -- see docs/RENDERING.md. That saves a multi-gigabyte texlive install.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/.venv"

die() { echo "ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------- system libs
# ffmpeg encodes the video. cairo and pango rasterise every frame and every
# glyph; manim cannot start without them.
echo "==> Installing system packages (ffmpeg + cairo/pango)"
case "$(uname -s)" in
  Darwin)
    command -v brew >/dev/null 2>&1 \
      || die "Homebrew not found. Install it from https://brew.sh, then re-run."
    # Already-installed formulae make `brew install` exit non-zero, so don't
    # let that abort the script.
    brew install ffmpeg cairo pango pkg-config || true
    ;;
  Linux)
    if command -v apt-get >/dev/null 2>&1; then
      export DEBIAN_FRONTEND=noninteractive
      SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
      $SUDO apt-get update -qq
      # The -dev headers are needed because pycairo has no manylinux wheel and
      # compiles from source. fonts-dejavu-core matters more than it looks:
      # with no font installed, Text() renders BLANK and raises nothing.
      $SUDO apt-get install -y -qq \
        ffmpeg libcairo2-dev libpango1.0-dev pkg-config python3-dev \
        build-essential fonts-dejavu-core
    else
      echo "    Not a Debian/Ubuntu system. Install these yourself, then re-run:"
      echo "    ffmpeg, cairo (+headers), pango (+headers), pkg-config, a C compiler"
    fi
    ;;
  *) die "Unsupported OS: $(uname -s). Needs macOS or Linux." ;;
esac

command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg still not on PATH after install."
echo "==> ffmpeg: $(ffmpeg -version 2>/dev/null | head -1)"

# ---------------------------------------------------------------- python env
echo "==> Creating venv at $VENV"
PY_BIN=""
for c in python3.12 python3.11 python3; do
  command -v "$c" >/dev/null 2>&1 && { PY_BIN="$c"; break; }
done
[ -n "$PY_BIN" ] || die "No python3 found."

if command -v uv >/dev/null 2>&1; then
  uv venv "$VENV"
  PIP_INSTALL=(uv pip install --python "$VENV/bin/python")
else
  echo "    (uv not found; using pip, which is ~10x slower."
  echo "     To speed this up: curl -LsSf https://astral.sh/uv/install.sh | sh)"
  "$PY_BIN" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  PIP_INSTALL=("$VENV/bin/pip" install)
fi

echo "==> Installing manim"
"${PIP_INSTALL[@]}" manim

# This is the step the old script was missing, which left a fresh clone with
# no fastapi, no uvicorn and no sympy -- the API could not start at all.
echo "==> Installing backend dependencies"
"${PIP_INSTALL[@]}" -r "$REPO_ROOT/backend/requirements.txt"

# ---------------------------------------------------------------- verify
echo "==> Verifying"
"$VENV/bin/manim" --version
"$VENV/bin/python" -c "import fastapi, uvicorn, sympy; print('backend deps OK')"

echo "==> Rendering a test scene (~3s)"
cd "$REPO_ROOT"
"$VENV/bin/manim" -ql --disable_caching -v ERROR \
  backend/scenes/_derisk_test.py DeriskSideBySide

OUT="$REPO_ROOT/media/videos/_derisk_test/480p15/DeriskSideBySide.mp4"
[ -f "$OUT" ] || die "Render produced no file at $OUT"
# stat flags differ between GNU (-c%s) and BSD/macOS (-f%z).
SIZE=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT")
echo "==> OK. Wrote $OUT ($SIZE bytes)"

cat <<'DONE'

Setup complete. Start the app with:

    bash scripts/run.sh

Then open http://localhost:8000

That runs in fixture mode, which needs no API key and no network. To read real
photographs of handwritten work, export ANTHROPIC_API_KEY first.
DONE
