#!/usr/bin/env bash
# End-to-end check. Run it before you demo.
#
#   bash scripts/smoke.sh              # starts its own server on a free port
#   BASE=http://localhost:8000 bash scripts/smoke.sh   # test a running one
#
# Every fixture in samples/ must come back with a hint and either a rendered
# video or an explained fallback. Exits non-zero, loudly, if any does not.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/.venv"

[ -x "$VENV/bin/python" ] || { echo "ERROR: no venv. Run: bash scripts/setup.sh" >&2; exit 1; }

cd "$REPO_ROOT"

OWN_SERVER=""
if [ -z "${BASE:-}" ]; then
  PORT=$("$VENV/bin/python" -c 'import socket; s=socket.socket(); s.bind(("",0)); print(s.getsockname()[1]); s.close()')
  BASE="http://localhost:$PORT"
  echo "==> Starting a server on port $PORT"
  USE_FIXTURE=1 "$VENV/bin/python" -m uvicorn backend.app:app \
    --port "$PORT" --log-level warning >/tmp/manimhint-smoke.log 2>&1 &
  OWN_SERVER=$!
  trap 'kill '"$OWN_SERVER"' 2>/dev/null || true' EXIT
  for _ in $(seq 1 40); do
    curl -fsS "$BASE/api/health" >/dev/null 2>&1 && break
    "$VENV/bin/python" -c 'import time; time.sleep(0.5)'
  done
fi

echo "==> Testing $BASE"
BASE="$BASE" "$VENV/bin/python" - <<'PY'
import json, os, sys, urllib.error, urllib.request

BASE = os.environ["BASE"].rstrip("/")
FAIL = []


def get(path, timeout=30):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
        return r.status, r.read()


def analyze(fixture):
    body = json.dumps({"fixture": fixture, "wait": True}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/analyze?wait=true", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.status, json.loads(r.read())


try:
    status, raw = get("/api/health")
    health = json.loads(raw)
except Exception as exc:
    sys.exit(f"FAIL  /api/health unreachable: {exc}")
print(f"  health           ok (fixture_mode={health['fixture_mode']}, "
      f"{len(health['scene_templates'])} templates)")

fixtures = health.get("fixtures") or []
if not fixtures:
    sys.exit("FAIL  no fixtures in samples/")

for name in fixtures:
    try:
        code, job = analyze(name)
    except urllib.error.HTTPError as exc:
        FAIL.append(f"{name}: HTTP {exc.code} {exc.read()[:200]!r}")
        print(f"  {name:18} FAIL  HTTP {exc.code}")
        continue
    except Exception as exc:
        FAIL.append(f"{name}: {type(exc).__name__}: {exc}")
        print(f"  {name:18} FAIL  {type(exc).__name__}")
        continue

    problems = []
    if not (job.get("hint") or "").strip():
        problems.append("empty hint")

    vs = job.get("video_status")
    if vs == "ready":
        vid = job.get("job_id")
        try:
            vcode, blob = get(f"/api/video/{vid}", timeout=60)
            if vcode != 200 or len(blob) < 10_000:
                problems.append(f"video fetch {vcode}, {len(blob)} bytes")
        except Exception as exc:
            problems.append(f"video fetch failed: {exc}")
    elif vs == "not_needed":
        pass                      # nothing wrong in this work; explained, fine
    else:
        # These five fixtures are known to contain an error, so a render that
        # did not happen is a dead demo -- not an acceptable fallback. Report
        # the reason, but fail.
        why = job.get("video_error") or "; ".join(job.get("notes") or []) or "no reason given"
        problems.append(f"video_status={vs}: {why[:160]}")

    if problems:
        FAIL.append(f"{name}: " + "; ".join(problems))
        print(f"  {name:18} FAIL  {'; '.join(problems)}")
    else:
        note = "" if vs == "ready" else f" ({vs})"
        print(f"  {name:18} ok    {job.get('rendered_template') or vs}{note}"
              f"  {job.get('video_seconds') or 0}s")

# The lint is the thing standing between a hint and a spoiler, so check that it
# still catches a leak rather than trusting that it is wired up.
sys.path.insert(0, os.getcwd())
from backend.hints import lint_hint            # noqa: E402

leaks = [
    ("The bottom-left entry should be 14.", ["14"], ["2"]),
    ("The bottom-left entry is fourteen.", ["14"], ["2"]),
    ("The scalar is 0.5.", ["1/2"], ["2"]),
    ("The scalar is 50%.", ["1/2"], ["2"]),
]
safe = [("Watch the bottom-left entry of your step 2.", ["14"], ["2"])]
for text, forb, allow in leaks:
    if not lint_hint(text, forb, allow):
        FAIL.append(f"hint lint let a leak through: {text!r}")
for text, forb, allow in safe:
    if lint_hint(text, forb, allow):
        FAIL.append(f"hint lint blocked a safe hint: {text!r}")
print(f"  hint leak lint   ok ({len(leaks)} leaks blocked, {len(safe)} safe hints passed)")

print()
if FAIL:
    print(f"FAILED ({len(FAIL)}):")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print(f"PASS - {len(fixtures)} fixtures, all reached a video or an explained fallback.")
PY
