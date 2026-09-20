"""Problem in, wrong derivation in, animation out.

The acceptance test for the whole product. Every case here is a problem plus a
derivation with a deliberate mistake, posted to the real ``/api/analyze`` over
HTTP, and each one must come back with:

  * the FIRST wrong step located, and it must be the step we planted;
  * a scene template chosen;
  * an mp4 that actually exists, has a real duration and plausible size;
  * a hint that does not contain the correct answer.

None of these are the bundled fixtures -- they are fresh problems, so this
exercises verify -> hint -> compile -> render rather than replaying a canned
extraction. The last case is a CORRECT derivation, which must not be accused.

Runs in fixture mode: typed steps never touch a vision API, so no key is needed
and the OpenAI path is untouched.

    bash scripts/run.sh                      # in one terminal, or let this start one
    .venv/bin/python backend/tests/test_wrong_derivation.py [--port 8000]
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

PORT = int(os.environ.get("TEST_PORT", "8086"))
BASE = f"http://127.0.0.1:{PORT}"


# --------------------------------------------------------------------------
# Building a derivation without writing the full extraction schema by hand
# --------------------------------------------------------------------------

def vec(*xs):
    return {"kind": "vector", "shape": [1, len(xs)], "rows": [list(xs)]}


def mat(rows):
    return {"kind": "matrix", "shape": [len(rows), len(rows[0])], "rows": rows}


def scalar(x):
    return {"kind": "scalar", "scalars": [x]}


def step(n, text, value, *, op="unknown", final=False):
    return {
        "id": f"s{n}",
        "student_label": f"{n})",
        "page": 1,
        "reading_order": n,
        "raw_text": text,
        "claimed_operation": op,
        "value": value,
        "is_final_answer": final,
        "parse_ok": True,
        "confidence": 0.95,
    }


def given(symbol, obj):
    return {"symbol": symbol, "object": obj, "source": "printed", "confidence": 0.97}


def problem(statement, topic, asks, givens):
    return {
        "present": True,
        "statement": statement,
        "topic": topic,
        "asks_for": asks,
        "confidence": 0.95,
        "givens": givens,
    }


# --------------------------------------------------------------------------
# The cases. Every "wrong" value below is a mistake a student actually makes.
# --------------------------------------------------------------------------

CASES = [
    {
        "name": "matrix product, one entry wrong",
        # A=[[2,-1],[3,1]] B=[[4,0],[2,5]] -> AB=[[6,-5],[14,5]].
        # Bottom-left computed as 3*4 + 1*2 = 14, written as 2.
        "expect_wrong": "s2",
        "answer_tokens": ["14"],
        "problem": problem("Compute AB.", "matrix_multiply", "AB",
                           [given("A", mat([[2, -1], [3, 1]])),
                            given("B", mat([[4, 0], [2, 5]]))]),
        "steps": [
            step(1, "A = [2 -1 ; 3 1]   B = [4 0 ; 2 5]", mat([[2, -1], [3, 1]])),
            step(2, "AB = [6 -5 ; 2 5]", mat([[6, -5], [2, 5]]),
                 op="matrix_multiply", final=True),
        ],
    },
    {
        "name": "inverse, adjugate without 1/det",
        # A=[[4,7],[2,6]], det=10. Inverse is (1/10)[[6,-7],[-2,4]].
        # Adjugate written without dividing.
        "expect_wrong": "s3",
        "answer_tokens": ["0.6", "0.4", "-0.7"],
        "problem": problem("Find the inverse of A.", "inverse", "A^-1",
                           [given("A", mat([[4, 7], [2, 6]]))]),
        "steps": [
            step(1, "A = [4 7 ; 2 6]", mat([[4, 7], [2, 6]])),
            step(2, "det A = 4(6) - 7(2) = 10", scalar(10.0), op="determinant"),
            step(3, "A^-1 = [6 -7 ; -2 4]", mat([[6, -7], [-2, 4]]),
                 op="inverse", final=True),
        ],
    },
    {
        "name": "claimed eigenvector is not one",
        # A=[[2,1],[1,2]] has eigenvectors (1,1) and (1,-1). (1,0) is neither:
        # A(1,0) = (2,1), which is off its own line.
        "expect_wrong": "s2",
        "answer_tokens": ["(1, 1)", "1 1"],
        "problem": problem("Is (1,0) an eigenvector of A?", "eigen", "eigenvector",
                           [given("A", mat([[2, 1], [1, 2]]))]),
        "steps": [
            step(1, "A = [2 1 ; 1 2]", mat([[2, 1], [1, 2]])),
            step(2, "v = (1,0) is an eigenvector", vec(1, 0),
                 op="eigenvector", final=True),
        ],
    },
    {
        "name": "projection divided by ||v|| instead of v.v",
        # u=(3,4), v=(1,2). u.v=11, v.v=5, proj=(11/5)(1,2)=(2.2,4.4).
        # Dividing by ||v||=sqrt(5) instead gives (11/sqrt5)(1,2).
        "expect_wrong": "s4",
        "answer_tokens": ["2.2", "4.4"],
        "problem": problem("Find proj_v(u).", "projection", "proj_v(u)",
                           [given("u", vec(3, 4)), given("v", vec(1, 2))]),
        "steps": [
            step(1, "u = (3,4)   v = (1,2)", vec(3, 4)),
            step(2, "u . v = 3(1) + 4(2) = 11", scalar(11.0), op="dot_product"),
            step(3, "||v|| = sqrt(5)", scalar(2.2360679), op="norm"),
            step(4, "proj = (11/sqrt5)(1,2) = (4.92, 9.84)", vec(4.92, 9.84),
                 op="projection", final=True),
        ],
    },
    {
        "name": "determinant, sign dropped",
        # det [[3,5],[2,4]] = 12 - 10 = 2. Written as 22 (added instead).
        "expect_wrong": "s2",
        "answer_tokens": ["2"],
        "problem": problem("Compute det A.", "determinant", "det A",
                           [given("A", mat([[3, 5], [2, 4]]))]),
        "steps": [
            step(1, "A = [3 5 ; 2 4]", mat([[3, 5], [2, 4]])),
            step(2, "det A = 3(4) + 5(2) = 22", scalar(22.0),
                 op="determinant", final=True),
        ],
    },
    {
        "name": "CONTROL: a correct derivation",
        # Nothing wrong here. The app must not invent an error.
        "expect_wrong": None,
        "answer_tokens": [],
        "problem": problem("Compute AB.", "matrix_multiply", "AB",
                           [given("A", mat([[1, 0], [0, 1]])),
                            given("B", mat([[2, 3], [4, 5]]))]),
        "steps": [
            step(1, "A = I   B = [2 3 ; 4 5]", mat([[2, 3], [4, 5]])),
            step(2, "AB = [2 3 ; 4 5]", mat([[2, 3], [4, 5]]),
                 op="matrix_multiply", final=True),
        ],
    },
]


# --------------------------------------------------------------------------

failures: list[str] = []


def check(case: str, label: str, cond: bool, detail: str = "") -> None:
    print(f"      {'ok  ' if cond else 'FAIL'}  {label}{'' if cond else '  <- ' + detail}")
    if not cond:
        failures.append(f"{case}: {label}")


def post(path: str, body: dict, timeout: float = 240.0) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def probe_video(url: str) -> tuple[int, float]:
    """Fetch the mp4 and return (bytes, duration). Duration 0 means unreadable."""
    with urllib.request.urlopen(BASE + url, timeout=60) as r:
        blob = r.read()
    tmp = Path("/tmp/_wd_probe.mp4")
    tmp.write_bytes(blob)
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(tmp)],
            capture_output=True, text=True, timeout=30,
        )
        return len(blob), float(out.stdout.strip() or 0)
    except Exception:
        return len(blob), 0.0


def wait_for_server(proc) -> bool:
    for _ in range(60):
        if proc and proc.poll() is not None:
            return False
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=2).read()
            return True
        except Exception:
            time.sleep(1)
    return False


def main() -> int:
    env = {**os.environ, "USE_FIXTURE": "1"}
    proc = subprocess.Popen(
        [str(REPO / ".venv/bin/python"), "-m", "uvicorn", "backend.app:app",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=str(REPO), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if not wait_for_server(proc):
        print("the server did not start:")
        print((proc.stderr.read() or b"").decode()[-1500:])
        return 1

    try:
        for c in CASES:
            print(f"\n  {c['name']}")
            try:
                job = post("/api/analyze?wait=true",
                           {"problem": c["problem"], "steps": c["steps"]})
            except urllib.error.HTTPError as exc:
                check(c["name"], "HTTP 200", False,
                      f"{exc.code}: {exc.read().decode()[:160]}")
                continue

            check(c["name"], "analysis returned", bool(job.get("job_id")))

            wrong = job.get("first_error_step_id")
            if c["expect_wrong"] is None:
                check(c["name"], "correct work is not accused",
                      wrong is None, f"blamed {wrong}")
                continue

            check(c["name"], f"located the planted error ({c['expect_wrong']})",
                  wrong == c["expect_wrong"], f"got {wrong}")
            check(c["name"], "chose a scene", bool(job.get("scene_template")),
                  str(job.get("scene_template")))

            status = job.get("video_status")
            check(c["name"], "video rendered", status == "ready",
                  f"status={status} err={job.get('video_error')}")
            if status == "ready":
                size, dur = probe_video(job["video_url"])
                check(c["name"], "mp4 is a real video", size > 50_000 and dur > 3.0,
                      f"{size}B {dur}s")
                # Three acts now, so anything much under 10s means the prologue
                # silently did not play.
                check(c["name"], "runs the full three acts", dur > 10.0, f"{dur}s")

            hint = (job.get("hint") or "").strip()
            check(c["name"], "hint present", bool(hint))
            # "your step 2" is a POSITIONAL reference, not the answer. Strip step
            # references before looking for leaks, and match on word boundaries,
            # or every single-digit answer is a false positive.
            scrubbed = re.sub(r"\bstep\s*\d+", "step", hint, flags=re.I)
            leaked = [t for t in c["answer_tokens"]
                      if t and re.search(r"(?<![\d.])" + re.escape(t) + r"(?![\d.])", scrubbed)]
            check(c["name"], "hint does not state the answer", not leaked,
                  f"leaked {leaked} in {hint!r}")
            print(f"      -> {job.get('scene_template')}: {hint[:66]}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if failures:
        print(f"{len(failures)} FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"ALL PASS ({len(CASES)} derivations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
