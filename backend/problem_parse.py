"""Pull the numbers and the task out of a problem written as a sentence.

A student types "Compute AB where A = [2 -1; 3 1] and B = [4 0; 2 5]." as one
line of prose. Nothing downstream could see the matrices in it, so the verifier
had no givens to check against, found nothing wrong, and answered "nothing in
this work disagrees with the problem" -- to work that was wrong.

Two jobs, both best-effort and both additive:

  givens_from_text   "A = [2 -1; 3 1]" wherever it appears, including mid-sentence
  topic_from_text    "compute AB" -> matrix_multiply, "det A" -> determinant, ...

This runs as a SUPPLEMENT, never a replacement. Whatever the vision model or the
frontend already extracted wins; this only fills gaps. A given it cannot parse is
skipped rather than guessed at, because a wrong given would make the app accuse
correct work -- worse than staying quiet.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# A = [1 2; 3 4]   A = [[1,2],[3,4]]   u = (3,4)   v = <1, 2>
# The symbol is a single letter, optionally subscripted (v1, A_2), because that
# is what people write. Longer names would swallow words like "and".
_DEF = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"([A-Za-z](?:_?\d)?)"                    # the symbol
    r"\s*=\s*"
    r"(\[[^\[\]]*(?:\[[^\]]*\][^\[\]]*)*\]|\([^()]*\)|<[^<>]*>)"
)

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:/[-+]?\d+\.?\d*)?")


def _numbers(chunk: str) -> list[float]:
    out = []
    for tok in _NUM.findall(chunk):
        try:
            if "/" in tok:
                a, b = tok.split("/", 1)
                out.append(float(a) / float(b))
            else:
                out.append(float(tok))
        except (ValueError, ZeroDivisionError):
            return []
    return out


def _rows_from(body: str) -> Optional[list[list[float]]]:
    """-> rows, or None when the text is not a clean rectangular literal."""
    inner = body.strip()[1:-1].strip()          # drop the outer bracket
    if not inner:
        return None

    # [[1,2],[3,4]] -- nested form
    nested = re.findall(r"\[([^\[\]]*)\]", inner)
    if nested:
        rows = [_numbers(r) for r in nested]
    else:
        # [1 2; 3 4] semicolons, or a single row / vector
        parts = re.split(r";|\n", inner)
        rows = [_numbers(p) for p in parts]

    rows = [r for r in rows if r]
    if not rows:
        return None
    width = len(rows[0])
    if width == 0 or any(len(r) != width for r in rows):
        return None                              # ragged: refuse rather than guess
    return rows


def givens_from_text(text: str) -> list[dict[str, Any]]:
    """Every "symbol = literal" in the text, as extraction Given dicts."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sym, body in _DEF.findall(text or ""):
        if sym in seen:
            continue
        rows = _rows_from(body)
        if rows is None:
            continue
        seen.add(sym)
        is_vector = len(rows) == 1 or all(len(r) == 1 for r in rows)
        out.append({
            "symbol": sym,
            "object": {
                "kind": "vector" if is_vector else "matrix",
                "shape": [len(rows), len(rows[0])],
                "orientation": "unspecified",
                "rows": rows,
                "wrote_decimals": "." in body,
            },
            "source": "printed",
            "ambiguities": [],
            "alternates": [],
            # Slightly below a vision read of a printed page: this is a regex over
            # prose, and downstream code weighs confidence.
            "confidence": 0.9,
        })
    return out


# (topic, pattern, ignore_case). Ordered: the more specific phrasings are tested
# first, or a bare "product" would swallow determinant and inverse questions.
#
# Case matters for the juxtaposition rules. "AB" means a matrix product, but
# under re.IGNORECASE the class [A-Z] also matches lowercase, so EVERY two-letter
# word -- "no", "is", "of" -- read as a matrix product and "no numbers here at
# all" came back as matrix_multiply.
_TOPIC_PATTERNS: list[tuple[str, str, bool]] = [
    ("determinant", r"\bdet(?:erminant)?\b", True),
    ("inverse", r"\binverse\b|\binvert\b|\^\s*-\s*1\b|\binvertible\b", True),
    ("eigen", r"\beigen(?:value|vector|s)?", True),
    # proj_a(b) is the common way to write it, and "_" is a word character, so
    # \bproj\b never matched the thing students actually type.
    ("projection", r"\bproj(?:ect(?:ion)?)?\b|\bproj_|\bshadow\b", True),
    ("dot_product", r"\bdot\b|\binner product\b|·", True),
    ("cross_product", r"\bcross\b", True),
    ("norm", r"\bnorm\b|\bunit vector\b|\bnormali[sz]e\b|\blength of\b|\|\|", True),
    ("transpose", r"\btranspose\b|\^\s*T\b", True),
    ("span", r"\bspan\b|\blinearly (in)?dependent\b|\bdimension\b|\bbasis\b", True),
    ("rref", r"\brref\b|\brow[- ]reduce\b|\brow echelon\b|\bgaussian\b", True),
    ("linear_system", r"\bAx\s*=\s*b\b|\bsolve\b[^.]*\bfor\s+x\b", False),
    ("matrix_add", r"\b[A-Z]\s*\+\s*[A-Z]\b", False),
    ("matrix_multiply", r"\bmultiply\b|\bproduct\b|\btimes\b|\b[A-Z]{2,3}\b", False),
]


def topic_from_text(text: str) -> Optional[str]:
    """The topic a problem statement is asking about, or None if unclear."""
    t = text or ""
    if not t.strip():
        return None
    for topic, pattern, ignore_case in _TOPIC_PATTERNS:
        if re.search(pattern, t, re.I if ignore_case else 0):
            return topic
    return None


def enrich(problem: Any) -> list[str]:
    """Fill in givens and topic from the statement. Returns notes for the user.

    Mutates ``problem`` in place and only ever ADDS: an existing given keeps its
    value, and a topic that is already known is left alone. Silent about doing
    nothing; a gap it cannot fill is simply left.
    """
    notes: list[str] = []
    statement = getattr(problem, "statement", None) or ""
    if not statement.strip():
        return notes

    have = {g.symbol for g in (problem.givens or [])}
    found = [g for g in givens_from_text(statement) if g["symbol"] not in have]
    if found:
        # Imported lazily: this module is also used by tests that never build a
        # full Extraction, and importing the models at module scope makes a
        # circular import through backend.extract.
        from .extract import Given

        problem.givens = list(problem.givens or []) + [Given.model_validate(g) for g in found]
        notes.append(
            "read " + ", ".join(g["symbol"] for g in found) + " from the problem you typed"
        )

    if (problem.topic or "other") in ("other", "unknown", ""):
        topic = topic_from_text(statement)
        if topic:
            problem.topic = topic

    return notes
