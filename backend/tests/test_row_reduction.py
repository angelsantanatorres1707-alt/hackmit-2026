"""Row reduction, end to end over HTTP.

A photographed row reduction used to come back with three "possible silent
correction" warnings and no animation at all, because:

  - the silent-correction guard flagged a PERFECT transcription of every row
    operation (students write pending arithmetic, so the evaluated row is made
    of numbers that are not literally on the page), and
  - nothing in verify.py checked a row operation, so first_error_index stayed
    None and the student was told nothing disagreed with work that was wrong.

Both halves are covered here: the guard must stay quiet on correct reading and
still fire on fabrication, and a planted error must be blamed on the step that
actually has it.

    .venv/bin/python backend/tests/test_row_reduction.py
    BASE=http://localhost:8000 .venv/bin/python backend/tests/test_row_reduction.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}{'' if cond else '  <- ' + detail}")
    if not cond:
        failures.append(label)


# -- the guard, in process -------------------------------------------------

def guard_cases() -> None:
    from backend.extract import MathObject, Step, silent_correction_suspected

    def mk(raw, rows, kind="augmented"):
        s = Step(id="s1", raw_text=raw, claimed_operation="row_op")
        s.value = MathObject(kind=kind, rows=rows)
        s.parse_ok = True
        return s

    print("\n1. the silent-correction guard")
    print("   correct transcription of pending arithmetic must NOT flag")
    for name, raw, rows in [
        ("R2 with an augmented bar", "R2 = [-3 -3 -2 + 3 -6 + 9 3 -3 | 13 - 12]", [[-6, 1, 3, 0, 1]]),
        ("R3, no bar", "R3 = [-2 + 2 2 + 2 3 -6 -2 + 2 1 + 8]", [[0, 4, -3, 0, 9]]),
        ("R4, tight spacing", "R4 = [1-1 0+1 -2+3 1-1 11-4]", [[0, 1, 1, 0, 7]]),
    ]:
        check(name, not silent_correction_suspected(mk(raw, rows)))

    print("   a model inventing a number must STILL flag")
    check("quietly fixing 2 into 14",
          silent_correction_suspected(mk("AB = [6 -5 2 5]", [[6, -5], [14, 5]], "matrix")))
    check("an entry from nowhere",
          silent_correction_suspected(mk("M = [1 2 3 4]", [[1, 2], [3, 99]], "matrix")))


# -- the verifier, over HTTP -----------------------------------------------

def mat(rows):
    return {"kind": "matrix", "shape": [len(rows), len(rows[0])], "rows": rows}


def given(sym, obj):
    return {"symbol": sym, "object": obj, "source": "printed", "confidence": 0.97}


def step(n, text, value, op="unknown", final=False):
    return {"id": f"s{n}", "student_label": f"{n})", "page": 1, "reading_order": n,
            "raw_text": text, "claimed_operation": op, "value": value,
            "is_final_answer": final, "confidence": 0.9}


PROBLEM = {
    "present": True,
    "statement": "Row-reduce [A|b], where A = [1 2 -1; 2 1 1; 3 3 0] and b = [2; 5; 7].",
    "topic": "rref", "asks_for": "rref([A|b])", "confidence": 0.95,
    "givens": [given("A", mat([[1, 2, -1], [2, 1, 1], [3, 3, 0]])),
               given("b", mat([[2], [5], [7]]))],
}
START = mat([[1, 2, -1, 2], [2, 1, 1, 5], [3, 3, 0, 7]])

# R2 - 2R1 = [0 -3 3 | 1];  R3 - 3R1 = [0 -3 3 | 1]
R2_TEXT = "R2 = R2 - 2R1 = [2-2 1-4 1+2 | 5-4]"
R3_TEXT = "R3 = R3 - 3R1 = [3-3 3-6 0+3 | 7-6]"

CASES = [
    ("a slip in the first row operation", "s2", [
        step(1, "[A|b] = [1 2 -1 | 2 ; 2 1 1 | 5 ; 3 3 0 | 7]", START),
        step(2, R2_TEXT, mat([[0, -3, 3, 2]]), op="row_op"),
        step(3, R3_TEXT, mat([[0, -3, 3, 1]]), op="row_op", final=True),
    ]),
    ("a slip in the second, first one sound", "s3", [
        step(1, "[A|b] = [1 2 -1 | 2 ; 2 1 1 | 5 ; 3 3 0 | 7]", START),
        step(2, R2_TEXT, mat([[0, -3, 3, 1]]), op="row_op"),
        step(3, R3_TEXT, mat([[0, -3, 9, 1]]), op="row_op", final=True),
    ]),
    ("a clean reduction is not accused", None, [
        step(1, "[A|b] = [1 2 -1 | 2 ; 2 1 1 | 5 ; 3 3 0 | 7]", START),
        step(2, R2_TEXT, mat([[0, -3, 3, 1]]), op="row_op"),
        step(3, R3_TEXT, mat([[0, -3, 3, 1]]), op="row_op", final=True),
    ]),
    ("a swap moves both rows, and is not itself blamed", "s3", [
        step(1, "[A|b] = [1 2 -1 | 2 ; 2 1 1 | 5 ; 3 3 0 | 7]", START),
        step(2, "R1 <-> R2", mat([[2, 1, 1, 5], [1, 2, -1, 2], [3, 3, 0, 7]]), op="row_swap"),
        step(3, "R2 = R2 - 3R1 = [1-6 2-3 -1-3 | 2-15]", mat([[-5, -1, -4, -12]]),
             op="row_op", final=True),
    ]),
    ("scaling a row correctly is not accused", None, [
        step(1, "[A|b] = [1 2 -1 | 2 ; 2 1 1 | 5 ; 3 3 0 | 7]", START),
        step(2, "R3 = 2R3 = [6 6 0 | 14]", mat([[6, 6, 0, 14]]), op="row_op", final=True),
    ]),
]


def post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=280) as r:
        return json.loads(r.read().decode())


def http_cases(base: str) -> None:
    print("\n2. a row operation is checked, and the right step is blamed")
    for name, expect, steps in CASES:
        try:
            job = post(base, "/api/analyze?wait=true", {"problem": PROBLEM, "steps": steps})
        except urllib.error.HTTPError as exc:
            check(name, False, f"HTTP {exc.code}: {exc.read().decode()[:140]}")
            continue
        got = job.get("first_error_step_id")
        check(name, got == expect, f"blamed {got}, expected {expect}")
        if expect is not None:
            check(f"{name} -> a hint that points",
                  bool((job.get("hint") or "").strip()), "empty hint")


def main() -> int:
    guard_cases()

    base = os.environ.get("BASE")
    own = None
    if not base:
        import socket
        s = socket.socket(); s.bind(("", 0)); port = s.getsockname()[1]; s.close()
        base = f"http://localhost:{port}"
        env = dict(os.environ, USE_FIXTURE="1")
        own = subprocess.Popen(
            [str(REPO / ".venv/bin/python"), "-m", "uvicorn", "backend.app:app",
             "--port", str(port), "--log-level", "warning"],
            cwd=str(REPO), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=2).read()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
    try:
        http_cases(base)
    finally:
        if own:
            own.terminate()

    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
