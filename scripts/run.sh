#!/usr/bin/env bash
# Start the app.
#
#   bash scripts/run.sh              # fixture mode, no API key needed
#   bash scripts/run.sh --live       # read real photos (needs ANTHROPIC_API_KEY)
#   PORT=9000 bash scripts/run.sh    # different port
#
# --reload is on: edit backend/ or frontend/ and just refresh the browser.
# Editing a scene template invalidates its cached video automatically.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/.venv"
PORT="${PORT:-8000}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "ERROR: no virtualenv at $VENV" >&2
  echo "Run this first:  bash scripts/setup.sh" >&2
  exit 1
fi

if ! "$VENV/bin/python" -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "ERROR: backend dependencies are missing from the venv." >&2
  echo "Run:  bash scripts/setup.sh" >&2
  exit 1
fi

MODE="fixture"
for arg in "$@"; do
  case "$arg" in
    --live) MODE="live" ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ "$MODE" = "live" ]; then
  [ -n "${ANTHROPIC_API_KEY:-}" ] \
    || { echo "ERROR: --live needs ANTHROPIC_API_KEY set." >&2
         echo "  export ANTHROPIC_API_KEY=sk-ant-..." >&2
         echo "Or drop --live to run on the bundled samples instead." >&2
         exit 1; }
  export USE_FIXTURE=0
  echo "==> LIVE mode: uploaded photos go to the vision model."
else
  export USE_FIXTURE=1
  echo "==> FIXTURE mode: bundled samples only, no API key or network needed."
  echo "    (use --live to read real photographs)"
fi

# Fail with a clear message rather than uvicorn's traceback.
if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "ERROR: port $PORT is already in use." >&2
  echo "Either stop that process, or:  PORT=$((PORT+1)) bash scripts/run.sh" >&2
  exit 1
fi

echo
echo "    Open  ->  http://localhost:$PORT"
echo
cd "$REPO_ROOT"
exec "$VENV/bin/python" -m uvicorn backend.app:app \
  --host 0.0.0.0 --port "$PORT" --reload \
  --reload-dir backend --reload-dir frontend
