#!/usr/bin/env bash
# Start the app.
#
#   bash scripts/run.sh              # fixture mode, no API key needed
#   bash scripts/run.sh --live       # read real photos (needs ANTHROPIC_API_KEY)
#   bash scripts/run.sh --dev        # auto-reload while editing (not for a demo)
#   PORT=9000 bash scripts/run.sh    # different port
#
# Editing a scene template invalidates its cached video automatically, so you do
# not need --dev just to iterate on the animations.

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

# Load .env if present, so a key is set once rather than re-exported in every
# shell. It is gitignored; see .env.example. Existing environment variables win,
# so `OPENAI_API_KEY=... bash scripts/run.sh --live` still overrides the file.
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/.env"
  set +a
  echo "==> loaded .env"
fi

MODE="fixture"
RELOAD="0"
for arg in "$@"; do
  case "$arg" in
    --live) MODE="live" ;;
    --dev)  RELOAD="1" ;;
    -h|--help)
      sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $arg  (try --live, --dev, --help)" >&2; exit 2 ;;
  esac
done

if [ "$MODE" = "live" ]; then
  # Any supported provider will do here. The backend decides which one is
  # actually used (it is pinned in vision_providers.py) and says precisely
  # what is wrong if the pinned provider's key is the one missing -- this
  # gate only needs to know that SOME key exists. It used to demand
  # ANTHROPIC_API_KEY, which refused to start for an OpenAI key even though
  # setkey.sh offers OpenAI first.
  if [ -z "${OPENAI_API_KEY:-}${ANTHROPIC_API_KEY:-}${GEMINI_API_KEY:-}${OPENROUTER_API_KEY:-}" ]; then
    echo "ERROR: --live needs a vision API key." >&2
    echo "  Set one with:  bash scripts/setkey.sh" >&2
    echo "Or drop --live to run on the bundled samples instead." >&2
    exit 1
  fi
  export USE_FIXTURE=0
  echo "==> LIVE mode: uploaded photos go to the vision model."
else
  export USE_FIXTURE=1
  echo "==> FIXTURE mode: bundled samples only, no API key or network needed."
  echo "    (use --live to read real photographs)"
fi

case "$PORT" in
  ''|*[!0-9]*) echo "ERROR: PORT must be a number, got '$PORT'." >&2; exit 2 ;;
esac

# Fail with a clear message rather than uvicorn's traceback. Done by binding the
# socket rather than shelling out to lsof, which is not installed everywhere --
# and when it was missing this check silently passed and you got the traceback
# anyway. The venv is already proven above, so python is always available here.
if ! "$VENV/bin/python" - "$PORT" <<'PY'
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
then
  echo "ERROR: port $PORT is already in use." >&2
  if command -v lsof >/dev/null 2>&1; then
    echo "Using it right now:" >&2
    lsof -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | sed 's/^/  /' >&2 || true
  fi
  echo "Either stop that process, or run on another port:" >&2
  echo "    PORT=$((PORT + 1)) bash scripts/run.sh" >&2
  exit 1
fi

[ -d "$REPO_ROOT/samples" ] || echo "WARNING: samples/ is missing; fixture mode has nothing to show." >&2

echo
echo "    Open  ->  http://localhost:$PORT"
echo "    Stop  ->  Ctrl-C"
echo
cd "$REPO_ROOT"

# No --reload by default. The reloader restarts the process whenever a file
# under backend/ is saved, and every analysed job lives in memory -- so a
# teammate saving a file mid-demo makes the video the judge is watching 404.
# Use --dev while you are working on it.
if [ "$RELOAD" = "1" ]; then
  echo "    (--dev: auto-reloading on file changes)"
  exec "$VENV/bin/python" -m uvicorn backend.app:app \
    --host 0.0.0.0 --port "$PORT" --reload \
    --reload-dir backend --reload-dir frontend
fi
exec "$VENV/bin/python" -m uvicorn backend.app:app \
  --host 0.0.0.0 --port "$PORT"
