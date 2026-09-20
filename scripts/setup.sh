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

[ -f "$REPO_ROOT/backend/requirements.txt" ] \
  || die "backend/requirements.txt is missing. Run this from a full clone of the repo."

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
      SUDO=""
      if [ "$(id -u)" -ne 0 ]; then
        command -v sudo >/dev/null 2>&1 \
          || die "Not root and sudo is not installed. Re-run as root, or install these yourself: ffmpeg libcairo2-dev libpango1.0-dev pkg-config python3-dev build-essential fonts-dejavu-core"
        SUDO="sudo"
      fi
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
# 3.11 first: that is the version docs/RENDERING.md was verified against, and
# the newest release is exactly where manim's wheels (and pycairo's, which has
# no manylinux wheel at all) are most likely to be missing.
PY_BIN=""
for c in python3.11 python3.12 python3.13 python3; do
  command -v "$c" >/dev/null 2>&1 && { PY_BIN="$c"; break; }
done
[ -n "$PY_BIN" ] || die "No python3 found. Install Python 3.11, then re-run."

"$PY_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || die "$PY_BIN is $("$PY_BIN" -V 2>&1); manim needs 3.9 or newer."
echo "    using $PY_BIN ($("$PY_BIN" -V 2>&1))"

if command -v uv >/dev/null 2>&1; then
  # --python matters: without it uv picks its own default interpreter, which on
  # a laptop with several Pythons is often a newer one than the check above ran
  # against -- so the venv is not the Python we just validated.
  uv venv --python "$PY_BIN" "$VENV"
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
"$VENV/bin/python" -c "import fastapi, uvicorn, sympy, pydantic, PIL; print('backend deps OK')" \
  || die "The venv is missing backend dependencies. Delete $VENV and re-run."

# Text() goes through Pango and renders BLANK -- silently, with no error -- when
# no font is installed. A demo of invisible captions is worse than a crash.
if command -v fc-list >/dev/null 2>&1; then
  FONTS=$(fc-list 2>/dev/null | wc -l | tr -d ' ')
  if [ "${FONTS:-0}" -lt 1 ]; then
    echo "WARNING: no fonts found. Manim's Text() will render blank rectangles." >&2
    echo "         Install some:  apt-get install fonts-dejavu-core" >&2
  else
    echo "    fonts: $FONTS available"
  fi
fi

cd "$REPO_ROOT"

# Render into a scratch dir, not into the repo: the old script left a media/
# tree behind on every run, which is generated output nobody wants committed.
SMOKE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/manimhint-setup.XXXXXX")"
trap 'rm -rf "$SMOKE_DIR"' EXIT

echo "==> Rendering a test scene (~3s)"
SCENE="$REPO_ROOT/backend/scenes/_derisk_test.py"
if [ -f "$SCENE" ]; then
  "$VENV/bin/manim" -ql --disable_caching -v ERROR --progress_bar none \
    --media_dir "$SMOKE_DIR/media" "$SCENE" DeriskSideBySide
else
  # The scenes package is owned elsewhere and may be mid-edit. Still prove that
  # cairo, pango and ffmpeg line up, using a scene this script owns.
  cat > "$SMOKE_DIR/smoke.py" <<'SCENE_PY'
from manim import Scene, Text, FadeIn


class Smoke(Scene):
    def construct(self):
        self.play(FadeIn(Text("setup ok")), run_time=0.5)
SCENE_PY
  "$VENV/bin/manim" -ql --disable_caching -v ERROR --progress_bar none \
    --media_dir "$SMOKE_DIR/media" "$SMOKE_DIR/smoke.py" Smoke
fi

OUT=$(find "$SMOKE_DIR/media" -name '*.mp4' -type f -not -path '*partial_movie_files*' 2>/dev/null | head -1)
[ -n "$OUT" ] && [ -f "$OUT" ] || die "Manim produced no video. Check ffmpeg and cairo above."
# stat flags differ between GNU (-c%s) and BSD/macOS (-f%z).
SIZE=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT")
echo "    rendered $(basename "$OUT") ($SIZE bytes)"

# The scene above proves manim works. This proves the APP works: extraction
# fixture -> verify -> hint -> scene params, which is the path a demo takes and
# the one that breaks when a backend dependency is subtly missing.
echo "==> Smoke-testing the pipeline"
USE_FIXTURE=1 "$VENV/bin/python" - <<'PIPELINE_PY' || die "The analysis pipeline failed. See the error above."
from backend import extract, hints, verify

names = [f["name"] for f in extract.list_fixtures()]
if not names:
    raise SystemExit("no fixtures found in samples/ - is this a full clone?")
for name in names:
    ext = extract.load_fixture(name)
    plan = hints.plan(verify.verify(ext), ext)
    assert plan.hint.strip(), f"{name}: empty hint"
    assert plan.template, f"{name}: no scene chosen"
    print(f"    {name:18} -> {plan.template}")
print(f"    {len(names)} fixtures OK")
PIPELINE_PY

cat <<'DONE'

Setup complete. Start the app with:

    bash scripts/run.sh

Then open http://localhost:8000

That runs in fixture mode, which needs no API key and no network. To read real
photographs of handwritten work, export ANTHROPIC_API_KEY first.
DONE
