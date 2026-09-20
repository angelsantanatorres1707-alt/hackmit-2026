"""A located error -> (a) a scene template plus its filled parameters, and
(b) a POSITIONAL hint that points at the step without ever stating the correction.

Two rules govern this whole module.

1. Who fills what (SCENE_CATALOG.md §1.2). Every number in `params` is computed
   here from sympy values and formatted with `fmt_num`. No LLM retypes a matrix.
2. Hint discipline (SCENE_CATALOG.md §1.4). A hint names a LOCATION and a THING TO
   WATCH. It never contains the corrected value, in any form. `lint_hint` is the
   enforcement, and `plan()` runs it on itself before returning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Optional

import sympy as sp

from . import replay_route
from .extract import Extraction
from .verify import Val, Verdict, _col, val_json

MAX_ENTRY = 50.0
MIN_DET = 0.05


# --------------------------------------------------------------------------
# Formatting (SCENE_CATALOG.md §2.2) - there is no \frac without LaTeX
# --------------------------------------------------------------------------

def fmt_num(x: Any, max_den: int = 20) -> str:
    """int -> '3', nice rational -> '2/5', else '0.71'. Never str(float)."""
    try:
        val = float(sp.N(x))
    except Exception:
        return str(x)
    if abs(val) < 1e-12:
        return "0"
    if abs(val - round(val)) < 1e-9:
        return str(int(round(val)))
    frac = Fraction(val).limit_denominator(max_den)
    if abs(float(frac) - val) < 1e-9:
        return f"{frac.numerator}/{frac.denominator}"
    return f"{val:.2f}".rstrip("0").rstrip(".")


def real(e: Any) -> Optional[float]:
    """A sympy entry -> a finite real float, or None. Never raises.

    ``float(sp.N(e))`` raises TypeError on a free symbol ("lambda" written in a
    matrix), on anything complex, and on ``zoo`` (which an exact entry of "1/0"
    produces) -- and it silently returns inf/nan for ``oo`` and ``nan``. Every
    one of those reaches this module from a real extraction, and every one of
    them used to escape ``_rows`` as an uncaught TypeError, which turned "is
    this drawable?" into a 500 for the whole request. A value we cannot place on
    a plane is not an error, it is just not drawable, so it comes back as None
    and the caller steps down the fallback ladder.
    """
    try:
        val = complex(sp.N(e))
    except (TypeError, ValueError, AttributeError, OverflowError):
        return None
    # nan compares False against everything, so zoo (nan+nanj) falls through the
    # imaginary test and is caught by the `r != r` line below.
    if abs(val.imag) > 1e-9:
        return None
    r = val.real
    if r != r or r in (float("inf"), float("-inf")):
        return None
    return r


def _rows(v: Optional[Val]) -> Optional[list[list[float]]]:
    """All-or-nothing: one undrawable entry makes the whole matrix undrawable."""
    if v is None or not v.is_matrix:
        return None
    out: list[list[float]] = []
    try:
        for i in range(v.obj.rows):
            row: list[float] = []
            for e in v.obj.row(i):
                f = real(e)
                if f is None:
                    return None
                row.append(f)
            out.append(row)
    except Exception:
        return None
    return out


def _display(v: Optional[Val]) -> Optional[list[list[str]]]:
    if v is None or not v.is_matrix:
        return None
    try:
        return [[fmt_num(e) for e in v.obj.row(i)] for i in range(v.obj.rows)]
    except Exception:
        return None


def _flat(v: Optional[Val]) -> Optional[list[float]]:
    if v is None or not v.is_matrix:
        return None
    out: list[float] = []
    try:
        for e in _col(v.obj):
            f = real(e)
            if f is None:
                return None
            out.append(f)
    except Exception:
        return None
    return out


def _subject(env: dict) -> Optional[Val]:
    """The square matrix this problem is about, whatever the student called it.

    Four scene builders used to read env.get("M") directly. Students write "A"
    far more often, so every one of them got None, raised SceneUnavailable and
    fell back to StaticStepHighlight -- a static slide that TEMPLATE_AUDIT.md
    ranks 12th and describes as "not a demo animation". The mathematics was
    right; the animation was quietly the worst one available.
    """
    for name in ("M", "A"):
        v = env.get(name)
        if _is_square(v):
            return v
    square = [v for k, v in env.items() if _is_square(v)]
    return square[0] if len(square) == 1 else None


def _is_square(v: Optional[Val]) -> bool:
    if v is None or not getattr(v, "is_matrix", False):
        return False
    try:
        r, c = v.obj.shape
    except Exception:
        return False
    return r == c > 1


def _is_2x2(v: Optional[Val]) -> bool:
    return bool(v is not None and v.is_matrix and v.obj.shape == (2, 2))


def _finite(rows: Optional[list[list[float]]]) -> bool:
    if not rows:
        return False
    for row in rows:
        for e in row:
            if e != e or abs(e) == float("inf") or abs(e) > MAX_ENTRY:
                return False
    return True


def _det_ok(rows: list[list[float]]) -> bool:
    try:
        return abs(rows[0][0] * rows[1][1] - rows[0][1] * rows[1][0]) >= MIN_DET
    except Exception:
        return False


# --------------------------------------------------------------------------
# Hint bank. Positional and observational, one per taxonomy id.
# --------------------------------------------------------------------------

HINTS: dict[str, tuple[str, str]] = {
    # error_id: (full sentence for the student, short caption burned into the scene)
    "LA01": ("Both grids stretch by the same amount — watch where your first column sends "
             "the first basis vector in {step}.", "watch where your first column lands"),
    "LA02": ("Freeze both panels halfway: the intermediate grids are the same shape. Watch "
             "which panel stretches first in {step}.", "watch which one stretches first"),
    "LA03": ("Count the numbers across one row of your left matrix, then count down one "
             "column of your right one, in {step}.", "count across, then count down"),
    "LA04": ("The area counter stops well before your number. Watch what happens between "
             "the two products you formed in {step}.", "watch where the counter stops"),
    "LA05": ("Watch how little the volume actually changes. Look at what sits in front of "
             "the second minor in {step}.", "watch how little the volume changes"),
    "LA06": ("Watch which color the square is showing when it lands in {step}.",
             "watch which side lands face up"),
    "LA07": ("The grid comes back square and pointing the right way. Watch its size against "
             "the faint original in {step}.", "watch the size it comes back at"),
    "LA08": ("It almost comes home. Watch the two numbers on the main diagonal of {step} as "
             "the grid settles.", "watch the main diagonal"),
    "LA09": ("Your vector's line is drawn on screen. Watch whether the arrow stays on that "
             "line in {step}.", "watch whether it stays on its line"),
    "LA10": ("The direction you found is right. Watch how far along that line the vector "
             "actually travels in {step}.", "watch how far along the line it stops"),
    # "every vector of length 1" says the same thing but puts a digit in the
    # hint, which the leak lint then has to reject whenever 1 is an entry of the
    # correct answer -- costing a good hint to protect a number it never meant.
    "LA11": ("The circle on screen is every unit vector. Watch where your tip lands "
             "relative to it in {step}.", "watch where your tip lands"),
    "LA12": ("Watch whether your new line still passes through the point where the first two "
             "cross, in {step}.", "watch the point where they cross"),
    "LA13": ("Scaling a row should not move its line at all. Watch whether yours stays put "
             "in {step}.", "watch whether the line stays put"),
    "LA14": ("Watch how much thickness the solid your vectors make actually has, in {step}.",
             "watch the thickness of the solid"),
    "LA15": ("Watch how much of the plane actually fills in, and whether the marked point is "
             "ever reached, in {step}.", "watch how much of the plane fills in"),
    "LA16": ("Both panels shear by the same amount, one sideways and one upward. Watch which "
             "matrix acts first in {step}.", "watch which one acts first"),
    "LA17": ("Watch what your arrow does to the sheet the two vectors span, in {step}.",
             "watch it lean into the sheet"),
    "LA18": ("Count how many numbers are on each side of your equals sign in {step}.",
             "count the numbers on each side"),
    "LA19": ("A shadow cannot be longer than the thing casting it. Watch whether the corner "
             "marker closes in {step}.", "watch whether the corner closes"),
    # The misconception, not the slip: the directions overlap, so the shadows
    # you add overlap too. Says what to watch, never what the answer is.
    "LA20": ("Your directions are not square to each other, so the shadows you added share "
             "part of the same ground. Watch whether what is left over meets the plane "
             "squarely in {step}.", "watch whether the leftover meets it squarely"),
    "LA21": ("A projection leaves behind something square to the whole plane. Watch whether "
             "yours does, in {step}.", "watch the corner where it lands"),
    # Property claims: the numbers were right and the conclusion was not.
    "LA22": ("Equal lengths are not the same as equal angles. Watch what happens to the "
             "square corner between the two basis arrows in {step}.",
             "watch the corner between the arrows"),
    "LA23": ("Watch how long the basis arrows are after the map, against how long they "
             "started, in {step}.", "watch the arrows change length"),
    "LA24": ("Applying one map and then the other is not the same journey as applying "
             "them the other way round. Watch the plane under each order in {step}.",
             "watch each order in turn"),
    "LA25": ("A map that squashes the plane flat has no way back: nothing can unsquash "
             "it. Watch what your matrix does to the area of the unit square in {step}.",
             "watch the area it leaves behind"),
    "LA26": ("Square to each other is a statement about the dot product, not about the "
             "lengths. Look again at the product you formed in {step}.",
             "look again at the dot product"),
    "LA27": ("How many solutions there are is settled by how many independent conditions "
             "the rows really impose, against how many unknowns there are. Compare those "
             "two counts in {step}.", "compare conditions against unknowns"),
    "LA30": ("Every Ax you can possibly form is a combination of A's own columns, so "
             "the reachable set is only as big as the columns are different from each "
             "other. Watch how much of the plane stays dark, and where b sits, in "
             "{step}.", "watch how much stays dark, and where b sits"),
    "LA28": ("A vector can sit on an eigen-line and still belong to a different "
             "stretch. Watch how far along its own line {step} sends it, against how "
             "far the eigenvalue you paired it with would.",
             "watch how far along its line it lands"),
    "LA29": ("Coordinates in a basis are the amounts of each basis vector you need to "
             "rebuild the vector -- not the vector's own entries. Watch where your "
             "amounts actually land in {step}.", "watch where your amounts land"),
}

GENERIC_BASIS = ("Watch where the {which} basis vector lands in {step}.",
                 "watch the {which} basis vector")
GENERIC_ANY = ("Watch the left panel against the right one in {step}.",
               "watch the two panels")

BANNED = (
    # stating the correction outright
    "should be", "should have", "instead of", "rather than", "you forgot",
    "the correct", "correct value", "correct answer", "right answer",
    "actually is", "is actually", "in fact it", "is wrong because",
    "the answer is", "you needed to", "you should", "you meant", "you missed",
    "ought to be", "needs to be", "has to be", "must be", "was supposed",
    # imperatives that hand over the fix
    "change it to", "change the", "replace it", "replace the", "make it",
    "try", "you want", "the real answer", "the true value",
)

# Word boundaries, not substrings: a plain `"try " in hint` also fires on
# "the bottom-left entry is ...", which blocks a perfectly safe positional hint.
_BANNED_RE = re.compile(
    "|".join(r"\b" + re.escape(p) + r"\b" for p in BANNED), re.I
)

_STEP_REF = re.compile(r"\byour step [^\s.,;:!?]+|\bstep \d+\b|\bthis step\b", re.I)

# Leading digit optional so a bare ".5" is scanned; exponent and fraction tails
# are both matched so "1e2" and "3 / 4" cannot slip past as "1"/"2" and "3"/"4".
_NUMBER = re.compile(
    r"(?<![\w.])(-\s*)?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?%?"
)

_CARDINAL = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100,
}
_DENOM = {
    "half": 2, "halves": 2, "third": 3, "thirds": 3, "quarter": 4,
    "quarters": 4, "fourth": 4, "fourths": 4, "fifth": 5, "fifths": 5,
    "sixth": 6, "sixths": 6, "eighth": 8, "eighths": 8, "tenth": 10,
    "tenths": 10,
}
_VULGAR = {
    "½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25,
    "¾": 0.75, "⅕": 0.2, "⅖": 0.4, "⅗": 0.6, "⅘": 0.8,
    "⅙": 1 / 6, "⅚": 5 / 6, "⅛": 0.125, "⅜": 0.375,
    "⅝": 0.625, "⅞": 0.875,
}
# A cardinal is a VALUE ("is fourteen", "by ten times") rather than a determiner
# ("one sideways and one upward", "the first two cross") only in these frames.
# Without this distinction the bank's own LA16 and LA12 wordings lint as leaks.
_VALUE_BEFORE = {
    "is", "are", "was", "were", "be", "equals", "equal", "=", "to", "of", "by",
    "than", "gives", "give", "becomes", "become", "get", "gets", "got", "it",
    "negative", "minus", "plus", "times", "over", "about", "around", "exactly",
    "just", "only", "short", "off",
}
_VALUE_AFTER = {"times", "too", "greater", "larger", "smaller", "bigger"}
_WORDY = re.compile(r"[a-z¼-¾⅐-⅞]+|[¼-¾⅐-⅞]")


def _word_values(hint: str) -> list[tuple[str, float]]:
    """Numbers written as words or vulgar fractions, in value position.

    "The bottom-left entry is fourteen" leaks exactly as hard as "... is 14",
    and the digit scanner sees nothing at all in it.
    """
    out: list[tuple[str, float]] = []
    for ch, val in _VULGAR.items():
        if ch in hint:
            out.append((ch, val))
    toks = re.findall(r"[A-Za-z]+|[=]", hint.lower())
    for i, tok in enumerate(toks):
        if tok not in _CARDINAL:
            continue
        num = float(_CARDINAL[tok])
        prev = toks[i - 1] if i else ""
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if nxt in _DENOM:                       # "one half", "two thirds"
            out.append((f"{tok} {nxt}", num / _DENOM[nxt]))
            continue
        if nxt == "over" and i + 2 < len(toks) and toks[i + 2] in _CARDINAL:
            out.append((f"{tok} over {toks[i+2]}", num / _CARDINAL[toks[i + 2]]))
            continue
        if prev in ("negative", "minus"):
            out.append((f"{prev} {tok}", -num))
            continue
        if prev in _VALUE_BEFORE or nxt in _VALUE_AFTER:
            out.append((tok, num))
    return out


def _scan_values(hint: str) -> list[tuple[str, float]]:
    """Every number the hint states, in any notation, as (as-written, value)."""
    scanned = _STEP_REF.sub(" ", hint)
    scanned = re.sub(r"(?<=\d),(?=\d)", "", scanned)   # 1,024 -> 1024
    found: list[tuple[str, float]] = []
    for m in _NUMBER.finditer(scanned):
        tok = m.group(0)
        n = _num(tok)
        if n is None:
            continue
        # "minus 1" / "negative 1" carry the sign the digit scanner cannot see.
        head = scanned[max(0, m.start() - 12):m.start()].lower()
        if re.search(r"\b(minus|negative)\s*$", head):
            n = -n
        found.append((tok, n))
    return found + _word_values(scanned)


def derived_values(student: list[str], correct: list[str]) -> list[str]:
    """Differences and ratios between the two answers -- the arithmetic leaks.

    "You are twelve short in the bottom-left" never names 14, but a student who
    wrote 2 now knows the answer. So does "it is ten times too large". These are
    the corrections restated, and they belong in the forbidden set.
    """
    out: list[str] = []
    for s_raw, c_raw in zip(student, correct):
        s, c = _num(s_raw), _num(c_raw)
        if s is None or c is None:
            continue
        diff = c - s
        if abs(diff) > 1e-9 and abs(diff) < 1e6:
            out.append(fmt_num(diff))
        if abs(s) > 1e-9:
            ratio = c / s
            if abs(ratio - 1.0) > 1e-9 and abs(ratio) < 1e6:
                out.append(fmt_num(ratio))
    return out


def lint_hint(
    hint: str,
    forbidden_values: list[str],
    allowed_values: list[str] | None = None,
) -> list[str]:
    """-> list of problems. Empty means the hint is safe to show a student.

    Rejects the banned corrective phrasings, and any number that appears in the
    correct answer but not in what the student themselves wrote -- as a digit, a
    decimal, a fraction, a percentage, a vulgar fraction or an English word.
    Step references ("your step 2") are stripped first, so pointing at a line is
    never a leak, and values the student wrote themselves are always allowed:
    quoting the student back to them tells them nothing new.
    """
    problems: list[str] = []
    if not isinstance(hint, str) or not hint.strip():
        return ["hint is empty"]
    if not _WORDY.search(hint.lower()):
        return ["hint has no words in it"]

    for m in dict.fromkeys(m.group(0).lower() for m in _BANNED_RE.finditer(hint)):
        problems.append(f"hint states a correction: {m!r}")

    allowed_nums = {n for n in (_num(v) for v in (allowed_values or [])) if n is not None}
    forbidden_nums = [
        (v, n) for v, n in ((v, _num(v)) for v in forbidden_values) if n is not None
    ]
    seen: set[str] = set()
    for tok, n in _scan_values(hint):
        if any(abs(a - n) < 1e-9 for a in allowed_nums):
            continue
        for v, fv in forbidden_nums:
            if abs(fv - n) < 1e-9 and v not in seen:
                seen.add(v)
                problems.append(f"hint leaks the value {v!r} (as {tok!r})")
                break
    return problems


def _num(text: Any) -> Optional[float]:
    """'14' / '-1' / '1/2' / '0.5' / '50%' / '1e2' / '- 5' -> float, else None."""
    if text is None:
        return None
    s = str(text).strip().replace(" ", "").replace("−", "-")
    if not s:
        return None
    pct = s.endswith("%")
    if pct:
        s = s[:-1]
    try:
        if "/" in s:
            a, b = s.split("/", 1)
            val = float(a) / float(b)
        else:
            val = float(s)
    except (ValueError, ZeroDivisionError, TypeError):
        return None
    if val != val or val in (float("inf"), float("-inf")):
        return None
    return val / 100.0 if pct else val


def _forbidden(correct: Optional[Val]) -> list[str]:
    if correct is None:
        return []
    if correct.is_matrix:
        return [fmt_num(e) for e in correct.obj]
    if isinstance(correct.obj, list):
        return [fmt_num(e) for e in correct.obj]
    return [fmt_num(correct.obj)]


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------

@dataclass
class Plan:
    template: str
    params: dict[str, Any]
    hint: str
    forbidden_values: list[str] = field(default_factory=list)
    fallback: Optional[dict[str, Any]] = None   # {"template":..., "params":...}
    notes: list[str] = field(default_factory=list)
    # Present whenever the scene is a StepReplay: the ordered step list with a
    # time window each, so the frontend can show which step the video is on.
    replay: Optional[dict[str, Any]] = None
    # Rungs below `fallback`, so demoting a comparison template under StepReplay
    # keeps StaticStepHighlight as the never-raises bottom of the ladder.
    fallbacks: list[dict[str, Any]] = field(default_factory=list)

    def json(self) -> dict:
        return {
            "template": self.template,
            "params": self.params,
            "hint": self.hint,
            "fallback": self.fallback,
            "fallbacks": self.fallbacks,
            "notes": self.notes,
        }


def step_ref(verdict: Verdict) -> str:
    """Speak in the student's own numbering, never our array index (§R5)."""
    label = (verdict.student_label or "").strip()
    if label:
        clean = label.rstrip(").:").strip()
        clean = re.sub(r"^step\s*", "", clean, flags=re.I)
        # The label is transcribed ink, so it can be anything. Anything long or
        # arithmetic-looking is not a label, and would be pasted straight into
        # the hint (and past the step-reference strip) if we trusted it.
        if clean and len(clean) <= 8 and not re.search(r"[=+\-*/\[\]]", clean):
            return f"your step {clean}"
    if verdict.first_error_index is not None:
        return f"your step {verdict.first_error_index + 1}"
    return "your work"


def plan(verdict: Verdict, ext: Extraction) -> Plan:
    """Pick the scene, fill its parameters, and write a hint that cannot leak."""
    env = verdict.givens
    S, C = verdict.student_value, verdict.correct_value
    eid = verdict.error_id
    ref = step_ref(verdict)
    notes: list[str] = []

    builder = {
        "LA01": _grid_single, "LA16": _grid_single,
        "LA02": _grid_order,
        "LA07": _grid_roundtrip, "LA08": _grid_roundtrip,
        "LA03": _static, "LA18": _static,
        "LA04": _determinant, "LA05": _determinant, "LA06": _determinant,
        "LA09": _eigen_vector, "LA10": _eigen_value,
        "LA11": _vector_op, "LA17": _vector_op, "LA19": _vector_op,
        "LA20": _vector_op, "LA21": _vector_op,
        "LA22": _angle_property, "LA23": _angle_property,
        "LA24": _grid_order,
        "LA28": _eigen_vector,
        "LA29": _span_rebuild,
        "LA12": _line_system, "LA13": _line_system,
        "LA14": _span, "LA15": _span,
        "LA30": _column_space,
    }.get(eid or "", _grid_single)

    full, short = HINTS.get(eid or "", GENERIC_ANY)
    try:
        template, params = builder(verdict, ext, env, S, C)
    except Exception as exc:
        # SceneUnavailable is the designed way down the ladder, but a builder
        # that raises anything else must land in the same place: a template that
        # cannot draw this error is a degraded video, never a failed request.
        why = str(exc) if isinstance(exc, SceneUnavailable) else f"{type(exc).__name__}: {exc}"
        notes.append(f"{eid or 'generic'} -> StaticStepHighlight: {why}")
        try:
            template, params = _static(verdict, ext, env, S, C)
        except Exception as exc2:      # the bottom of the ladder has to hold
            notes.append(f"StaticStepHighlight -> minimal: {type(exc2).__name__}: {exc2}")
            template, params = _minimal(verdict)
        full, short = HINTS.get(eid or "", GENERIC_ANY)

    if eid is None and template == "GridTransformCompare":
        which = _diverging_basis(S, C)
        if which:
            full, short = GENERIC_BASIS[0].replace("{which}", which), GENERIC_BASIS[1].replace("{which}", which)

    hint = full.format(step=ref)
    short_hint = short.format(step=ref) if "{step}" in short else short

    allowed = _forbidden(S)
    forbidden = _forbidden(C)
    # The arithmetic leaks too: "twelve short" and "ten times too large" name the
    # correction without naming the answer.
    forbidden = forbidden + derived_values(allowed, forbidden)

    # The short caption is burned into the video frame, so it is every bit as
    # public as the sentence -- lint both, and fail them together.
    problems = lint_hint(hint, forbidden, allowed) + lint_hint(short_hint, forbidden, allowed)
    if problems:  # a leaked hint is a product failure: fall back to the safest wording
        notes.extend(problems)
        hint = f"Watch the highlighted part of {ref}."
        short_hint = "watch the highlighted part"
        if lint_hint(hint, forbidden, allowed):
            # Only reachable if the step reference itself carries the answer.
            notes.append("even the positional wording linted; dropping the step reference")
            hint = "Watch the highlighted part of your work."

    params["hint"] = short_hint
    params.setdefault("title", _title(template, ref))
    params.setdefault("student_label", "WHAT YOU WROTE")
    params.setdefault("correct_label", "WHAT THE STEP SHOULD DO")

    fallback = None
    if template != "StaticStepHighlight":
        try:
            _t, fb_params = _static(verdict, ext, env, S, C)
        except Exception as exc:
            notes.append(f"no StaticStepHighlight fallback: {type(exc).__name__}: {exc}")
            fb_params = None
        if fb_params is not None:
            fb_params["hint"] = short_hint
            fb_params.setdefault("title", params["title"])
            fallback = {"template": "StaticStepHighlight", "params": fb_params}

    # ---------------------------------------------------------------------
    # StepReplay is the DEFAULT. Everything above is the fallback tier.
    #
    # The seven comparison templates summarise where the student's work ENDED
    # UP: one before/after of their final claim beside the correct one. They
    # never replay the reasoning that got there, which is what the student
    # asked to see. When a replay can be built from the steps they actually
    # wrote, it wins, and the comparison we just built becomes the rung below
    # it. When it cannot, nothing here changes and the old ladder runs.
    # ---------------------------------------------------------------------
    replay = replay_route.build(ext, verdict, student_label="YOUR WORK")
    replay_block = None
    deeper: list[dict[str, Any]] = []
    if replay["ok"]:
        r_params = replay["params"]
        r_full, r_short = _replay_hint(replay["caption"], eid, ref)
        r_problems = lint_hint(r_full, forbidden, allowed) + lint_hint(r_short, forbidden, allowed)
        if r_problems:
            notes.extend(f"replay hint: {p}" for p in r_problems)
            r_full = f"Watch the highlighted part of {ref}."
            r_short = "watch the step the caret marks"
        r_params["hint"] = r_short
        r_params.setdefault("student_label", "YOUR WORK")
        r_params["title"] = "Your work, replayed step by step"
        # The comparison plan built above is the fallback: a real animation,
        # and a better rung than the static sheet when a replay cannot render.
        # The static sheet stays underneath it as the bottom of the ladder.
        if fallback is not None:
            deeper = [fallback]
        fallback = {"template": template, "params": params}
        replay_block = replay_route.replay_view(r_params, replay["result"], hint=r_full)
        notes.append(
            f"StepReplay: replaying {replay_block['step_count']} of the student's own "
            f"steps ({replay_block['motion_steps']} with geometry); "
            f"{template} demoted to fallback"
        )
        notes.extend(f"replay: {w}" for w in replay["warnings"])
        template, params, hint = "StepReplay", r_params, r_full
    elif replay["reason"]:
        notes.append(f"no StepReplay ({replay['reason']}); used {template}")

    return Plan(template, params, hint, forbidden, fallback, notes,
                replay_block, deeper)


def _replay_hint(caption: str, eid: Optional[str], ref: str) -> tuple[str, str]:
    """(sentence for the student, caption burned into the replay frame).

    The caption comes from the compiler and names what the replay actually
    draws, so it beats the comparison bank's wording, which describes two
    panels a replay does not have. The bank's full sentence is still the better
    prose when the taxonomy matched, and both are linted by the caller.
    """
    short = " ".join((caption or "").split())
    if not short:
        return "", ""
    bank = HINTS.get(eid or "")
    if bank:
        return bank[0].format(step=ref), short
    body = (short[0].upper() + short[1:]).rstrip(".")
    return f"{body}. Watch it happen in {ref}.", short


class SceneUnavailable(Exception):
    """This template's guards say it cannot tell an honest story about this error."""


_TITLES = {
    "GridTransformCompare": "{ref}, applied to the plane",
    "EigenRayTest": "{ref}, and the line it has to stay on",
    "DeterminantAreaCompare": "{ref}, as an area",
    "VectorOpCompare": "{ref}, and the property it must have",
    "LineSystemCompare": "{ref}, as lines in the plane",
    "SpanCompare": "{ref}, and everything it reaches",
    "StaticStepHighlight": "{ref}",
    "AnglePreservationCheck": "Your transformation, applied to the corner",
}


def _title(template: str, ref: str) -> str:
    return _TITLES.get(template, "{ref}").format(ref=ref[0].upper() + ref[1:])


def _diverging_basis(S: Optional[Val], C: Optional[Val]) -> Optional[str]:
    """Which basis vector do the two matrices disagree about most? (T1's t=6.2 beat
    Indicates it on its own; the hint should name the same one.)"""
    a, b = _rows(S), _rows(C)
    if not a or not b or len(a) != 2 or len(b) != 2:
        return None
    gaps = []
    for j in range(min(len(a[0]), len(b[0]))):
        gaps.append(sum(abs(a[i][j] - b[i][j]) for i in range(2)))
    if not gaps or max(gaps) < 1e-9:
        return None
    return ["first", "second"][gaps.index(max(gaps))] if len(gaps) >= 2 else "first"


# --------------------------------------------------------------------------
# Builders. Each raises SceneUnavailable rather than emitting a scene that lies.
# --------------------------------------------------------------------------

def _need_2x2(v: Optional[Val], what: str) -> list[list[float]]:
    rows = _rows(v)
    if not _is_2x2(v) or not _finite(rows):
        raise SceneUnavailable(f"{what} is not a drawable 2x2 matrix")
    return rows


def _grid_single(verdict, ext, env, S, C):
    student = _need_2x2(S, "the student's value")
    correct = _need_2x2(C, "the correct value")
    for stage in (student, correct):
        if not _det_ok(stage):
            raise SceneUnavailable("a stage is near-singular; the grid would collapse to a line")
    return "GridTransformCompare", {
        "student_stages": [student],
        "correct_stages": [correct],
        "student_display": _display(S),
        "correct_display": _display(C),
        "stage_labels": [],
        "ghost_reference": False,
        "pause_between_stages": 0.0,
        "track_vectors": [[1, 0], [0, 1]],
    }


def _grid_order(verdict, ext, env, S, C):
    """LA02: the same two maps in both panels, applied in opposite orders."""
    A, B = env.get("A"), env.get("B")
    a, b = _rows(A), _rows(B)
    if not (_is_2x2(A) and _is_2x2(B) and _finite(a) and _finite(b) and _det_ok(a) and _det_ok(b)):
        return _grid_single(verdict, ext, env, S, C)
    # Stages are APPLIED in order, so [X, Y] draws the composite Y*X. Which
    # order belongs in the student's panel is decided by which one reproduces
    # the value they actually wrote -- not by the order they LABELLED it with.
    # A student who writes "BAv" and computes A(Bv) has the two the other way
    # round from one who writes "AB" and computes BA, and guessing from the
    # label alone puts the correct order under "WHAT YOU WROTE".
    stages = _order_matching(env, S, a, b) or [a, b]
    other = [b, a] if stages == [a, b] else [a, b]
    return "GridTransformCompare", {
        "student_stages": stages,
        "correct_stages": other,
        "student_display": _display(S),
        "correct_display": _display(C),
        "stage_labels": ["first", "then"],
        "ghost_reference": False,
        "pause_between_stages": 0.8,
        "track_vectors": [[1, 0], [0, 1]],
    }


def _order_matching(env, S, a, b):
    """Which stage order actually reproduces the student's written value?"""
    rows = _rows(S)
    if not rows:
        return None
    try:
        A, B = sp.Matrix(a), sp.Matrix(b)
        Sm = sp.Matrix(rows)
    except Exception:
        return None
    options = [([a, b], B * A), ([b, a], A * B)]
    for stages, comp in options:
        try:
            if comp.shape == Sm.shape and sp.simplify(comp - Sm).is_zero_matrix:
                return stages
        except Exception:  # noqa: BLE001
            continue
    # The claim may be the IMAGE of a given vector rather than the matrix.
    vec = None
    for name in ("v", "x", "u", "w"):
        got = _flat(env.get(name))
        if got:
            vec = sp.Matrix(got)
            break
    if vec is None:
        return None
    target = Sm.T if Sm.rows == 1 else Sm
    for stages, comp in options:
        try:
            if comp.shape[1] == vec.rows and sp.simplify(comp * vec - target).is_zero_matrix:
                return stages
        except Exception:  # noqa: BLE001
            continue
    return None


def _grid_roundtrip(verdict, ext, env, S, C):
    """LA07/LA08: apply M, then the claimed inverse. Does the grid come home?"""
    M = _subject(env)
    m = _rows(M)
    if not (_is_2x2(M) and _finite(m) and _det_ok(m)):
        return _grid_single(verdict, ext, env, S, C)
    student = _need_2x2(S, "the claimed inverse")
    correct = _need_2x2(C, "the true inverse")
    return "GridTransformCompare", {
        "student_stages": [m, student],
        "correct_stages": [m, correct],
        "student_display": _display(S),
        "correct_display": _display(C),
        "stage_labels": ["apply M", "then undo it"],
        "ghost_reference": True,     # the ruler that makes "10x too big" readable
        "pause_between_stages": 0.8,
        "track_vectors": [[1, 0], [0, 1]],
        "student_label": "YOUR ROUND TRIP",
        "correct_label": "A ROUND TRIP",
    }


def _determinant(verdict, ext, env, S, C):
    M = _subject(env)
    m = _rows(M)
    if m is None or not _finite(m) or len(m) not in (2, 3) or len(m) != len(m[0]):
        raise SceneUnavailable("no square given matrix to stretch")
    claimed = S.obj if S is not None and not S.is_matrix else None
    actual = C.obj if C is not None and not C.is_matrix else None
    if claimed is None or actual is None:
        raise SceneUnavailable("the determinant claim is not a single number")
    claimed_f, actual_f = real(claimed), real(actual)
    if claimed_f is None or actual_f is None:
        raise SceneUnavailable("a determinant is not a finite real number")
    if abs(claimed_f - actual_f) <= 1e-9:
        raise SceneUnavailable("the two determinants agree; there is no story here")
    return "DeterminantAreaCompare", {
        "M": m,
        "M_display": _display(M),
        "claimed_det": fmt_num(claimed),
        "actual_det": fmt_num(actual),
        "show_ghost_scale": abs(claimed_f) <= 60,
        "student_label": "YOUR ANSWER",
        "correct_label": "AREA ON SCREEN" if len(m) == 2 else "VOLUME ON SCREEN",
    }


def _eigen_vector(verdict, ext, env, S, C):
    M = _subject(env)
    m = _rows(M)
    if not (_is_2x2(M) and _finite(m)):
        raise SceneUnavailable("eigen ray test needs a 2x2 given matrix")
    v_claimed, v_correct = _flat(S), _flat(C)
    if not v_claimed or not v_correct or len(v_claimed) != 2 or len(v_correct) != 2:
        raise SceneUnavailable("the vectors are not 2D")
    if max(abs(x) for x in v_claimed) < 1e-9 or max(abs(x) for x in v_correct) < 1e-9:
        raise SceneUnavailable("a zero vector has no direction to draw")
    return "EigenRayTest", {
        "M": m, "M_display": _display(M),
        "v_claimed": v_claimed, "v_correct": v_correct,
        "lambda_claimed": None, "lambda_correct": None,
        "mode": "vector",
        "student_label": "YOUR VECTOR", "correct_label": "AN EIGENVECTOR",
    }


def _eigen_value(verdict, ext, env, S, C):
    M = _subject(env)
    m = _rows(M)
    if not (_is_2x2(M) and _finite(m)):
        raise SceneUnavailable("eigen ray test needs a 2x2 given matrix")
    claimed = _first_scalar(S)
    correct = _first_scalar(C)
    if claimed is None or correct is None:
        raise SceneUnavailable("no single claimed eigenvalue to draw")
    claimed_f, correct_f = real(claimed), real(correct)
    if claimed_f is None:
        # A complex or symbolic eigenvalue has nothing to draw on a real plane.
        raise SceneUnavailable("the claimed eigenvalue is not a real number")
    if correct_f is None:
        raise SceneUnavailable("the true eigenvalue is not a real number")
    vec = _real_eigenvector(M.obj)
    if vec is None:
        raise SceneUnavailable("no real eigenvector to travel along")
    return "EigenRayTest", {
        "M": m, "M_display": _display(M),
        "v_claimed": vec, "v_correct": vec,
        "lambda_claimed": claimed_f, "lambda_correct": correct_f,
        "mode": "eigenvalue",
        "student_label": "YOUR EIGENVALUE", "correct_label": "WHERE IT LANDS",
    }


def _first_scalar(v: Optional[Val]):
    if v is None:
        return None
    if isinstance(v.obj, list):
        return v.obj[0] if v.obj else None
    if v.is_matrix:
        return None
    return v.obj


def _real_eigenvector(M: sp.Matrix) -> Optional[list[float]]:
    try:
        for val, _m, vecs in M.eigenvects():
            if real(val) is None:
                continue
            out = [real(x) for x in sp.Matrix(vecs[0])]
            if any(x is None for x in out):
                continue
            return out
    except Exception:
        return None
    return None


def _vector_op(verdict, ext, env, S, C):
    eid = verdict.error_id
    op = {"LA11": "normalize", "LA17": "cross", "LA19": "projection",
          "LA20": "projection", "LA21": "projection"}.get(eid or "", "generic")
    u = _flat(env.get("u")) or _flat(env.get("v"))
    v = _flat(env.get("v")) or _flat(env.get("u"))
    w_claimed, w_correct = _flat(S), _flat(C)
    if not (u and v and w_claimed and w_correct):
        raise SceneUnavailable("missing one of the vectors this comparison needs")
    dim = len(w_correct)
    if dim not in (2, 3) or len({len(u), len(v), len(w_claimed), len(w_correct)}) != 1:
        raise SceneUnavailable("the vectors are not all the same drawable dimension")
    if op == "projection" and max(abs(x) for x in v) < 1e-9:
        raise SceneUnavailable("cannot project onto the zero vector")
    if op == "cross" and _parallel(u, v):
        raise SceneUnavailable("u and v are parallel; the sheet they span is degenerate")

    readouts = []
    if op == "projection":
        readouts = [
            ["your residual . v", fmt_num(_dotf([a - b for a, b in zip(u, w_claimed)], v))],
            ["a projection's residual . v", "0"],
        ]
    elif op == "normalize":
        readouts = [["your length", fmt_num(_normf(w_claimed))], ["a unit vector's length", "1"]]
    elif op == "cross":
        readouts = [
            ["u . your answer", fmt_num(_dotf(u, w_claimed))],
            ["v . your answer", fmt_num(_dotf(v, w_claimed))],
            ["a normal's dot products", "0"],
        ]
    return "VectorOpCompare", {
        "op": op, "u": u, "v": v,
        "w_claimed": w_claimed, "w_correct": w_correct,
        "labels": {"u": "u", "v": "v"},
        "readouts": readouts,
        "ambient": dim,
        "student_label": "YOUR ANSWER", "correct_label": "THE PROPERTY IT MUST HAVE",
    }


def _dotf(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _normf(a: list[float]) -> float:
    return sum(x * x for x in a) ** 0.5


def _parallel(a: list[float], b: list[float]) -> bool:
    try:
        return sp.Matrix.hstack(sp.Matrix(a), sp.Matrix(b)).rank() <= 1
    except Exception:
        return False


def _angle_property(verdict, ext, env, S, C):
    """LA22/LA23 -- every number is right and the conclusion is not.

    There is no student value to contrast here, so the comparison templates
    have nothing to draw. What can be drawn is the claim itself: the basis,
    and what the student's own map does to the corner (LA22) or to the lengths
    (LA23).
    """
    a, b = _images(env)
    if a is None or b is None:
        raise SceneUnavailable("no 2D map given by where the basis vectors land")
    if abs(a[0] * b[1] - a[1] * b[0]) < 1e-9:
        raise SceneUnavailable("the two images are parallel; there is no corner to watch close")
    if max(abs(x) for x in a + b) > 6.0:
        raise SceneUnavailable("the images are too long to draw beside a unit square")
    return "AnglePreservationCheck", {
        "e1_image": a, "e2_image": b,
        "show": "length" if verdict.error_id == "LA23" else "angle",
    }


def _images(env: dict):
    """Where e1 and e2 land, from either spelling: the givens may name the
    images directly, or give the matrix whose COLUMNS they are."""
    a, b = _flat(env.get("T(e1)")), _flat(env.get("T(e2)"))
    if not (a and b):
        rows = _rows(_subject(env))
        if rows and len(rows) == 2 and all(len(r) == 2 for r in rows):
            a, b = [rows[0][0], rows[1][0]], [rows[0][1], rows[1][1]]
    if not a or not b or len(a) != 2 or len(b) != 2:
        return None, None
    if not all(abs(x) < 1e6 for x in a + b):
        return None, None
    return a, b


def _span_rebuild(verdict, ext, env, S, C):
    """LA29: the claimed coordinates, used as weights, against the vector itself.

    Drawn with the vector-op comparison rather than a bespoke scene: the
    readouts say plainly that one combination lands on v and the other does not,
    without ever printing the coordinates that would be the answer.
    """
    basis = [_flat(env.get(n)) for n in sorted(env) if re.fullmatch(r"b\d+", n, re.I)]
    basis = [b for b in basis if b]
    target = _flat(env.get("v")) or _flat(env.get("x")) or _flat(env.get("w"))
    claimed, correct = _flat(S), _flat(C)
    if len(basis) != 2 or not target or not claimed or not correct:
        raise SceneUnavailable("no basis pair and vector to rebuild")
    if len({len(basis[0]), len(basis[1]), len(target)}) != 1 or len(target) not in (2, 3):
        raise SceneUnavailable("the basis and the vector are not the same drawable size")
    if len(claimed) != 2:
        raise SceneUnavailable("the claimed coordinates are not a pair of weights")
    built = [claimed[0] * basis[0][i] + claimed[1] * basis[1][i] for i in range(len(target))]
    return "VectorOpCompare", {
        "op": "generic", "u": basis[0], "v": basis[1],
        "w_claimed": built, "w_correct": target,
        "labels": {"u": "b1", "v": "b2"},
        "readouts": [["where your amounts land", "not v"],
                     ["where the coordinates must land", "v"]],
        "ambient": len(target),
        "student_label": "YOUR AMOUNTS, REBUILT",
        "correct_label": "THE VECTOR THEY MUST REBUILD",
    }


def _line_system(verdict, ext, env, S, C):
    eqs = _equations(env)
    if not eqs or len(eqs) < 2:
        raise SceneUnavailable("no 2-variable system to draw as lines")
    det = eqs[0][0] * eqs[1][1] - eqs[0][1] * eqs[1][0]
    if abs(det) < 1e-9:
        raise SceneUnavailable("the two lines do not meet; there is no hinge to pivot about")
    claimed, correct = _flat(S), _flat(C)
    if claimed and correct and len(claimed) == 2 and len(correct) == 2 and verdict.error_id != "LA13":
        subs = [[fmt_num(row[0] * claimed[0] + row[1] * claimed[1]), fmt_num(row[2])] for row in eqs]
        return "LineSystemCompare", {
            "mode": "solution", "equations": eqs,
            "x_claimed": claimed, "x_correct": correct,
            "substitutions": subs, "op_label": "",
            "student_result_line": None, "correct_result_line": None,
            "student_label": "YOUR SOLUTION", "correct_label": "WHERE THE LINES CROSS",
        }
    s_rows, c_rows = _rows(S), _rows(C)
    if not s_rows or not c_rows or len(s_rows[0]) < 3:
        raise SceneUnavailable("the claimed row is not an augmented row of three numbers")
    return "LineSystemCompare", {
        "mode": "row_op", "equations": eqs,
        "student_result_line": s_rows[-1][:3], "correct_result_line": c_rows[-1][:3],
        "op_label": (ext.steps[verdict.first_error_index].op_args.note or "row operation")
        if verdict.first_error_index is not None and verdict.first_error_index < len(ext.steps) else "row operation",
        "x_claimed": None, "x_correct": None, "substitutions": [],
        "student_label": "YOUR ROW", "correct_label": "THE ROW OPERATION",
    }


def _equations(env: dict[str, Val]) -> list[list[float]]:
    aug = env.get("Aug")
    if aug is not None and aug.is_matrix and aug.obj.cols >= 3:
        rows = [[real(x) for x in aug.obj.row(i)][:3] for i in range(aug.obj.rows)]
        return [r for r in rows if len(r) >= 3 and not any(x is None for x in r)]
    A, b = env.get("A"), env.get("b")
    if A is not None and A.is_matrix and b is not None and b.is_matrix and A.obj.cols == 2:
        bv = _col(b.obj)
        rows = [
            [real(A.obj[i, 0]), real(A.obj[i, 1]), real(bv[i])]
            for i in range(min(A.obj.rows, bv.rows))
        ]
        return [r for r in rows if not any(x is None for x in r)]
    return []


def _span(verdict, ext, env, S, C):
    vecs = _vector_list(env)
    if not vecs:
        raise SceneUnavailable("no set of vectors to sweep")
    ambient = len(vecs[0])
    if ambient not in (2, 3) or any(len(v) != ambient for v in vecs):
        raise SceneUnavailable("the vectors are not all 2D or all 3D")
    M = sp.Matrix.hstack(*[sp.Matrix(v) for v in vecs])
    actual = int(M.rank())
    claimed = _first_scalar(S)
    claimed_f = real(claimed) if claimed is not None else None
    claimed_dim = int(round(claimed_f)) if claimed_f is not None else len(vecs)
    if claimed_dim == actual:
        raise SceneUnavailable("the claimed dimension is the true one; no story")
    probe = _unreachable_probe(M, ambient)
    if probe is None:
        raise SceneUnavailable("could not verify a probe vector outside the span")
    return "SpanCompare", {
        "vectors": vecs, "claimed_dim": claimed_dim, "actual_dim": actual,
        "probe": probe, "ambient": ambient,
        "student_label": "YOUR CLAIM", "correct_label": "WHAT IS REACHED",
    }


def _column_space(verdict, ext, env, S, C):
    """LA30: everything Ax can reach is a combination of A's COLUMNS.

    Reuses the span sweep, fed from the matrix rather than from a loose list of
    vectors: the columns are the vectors, and b is the probe that is already
    known to be out of reach -- which is exactly why the system has no
    solution, shown rather than said.
    """
    A = env.get("A") or env.get("M")
    bv = env.get("b")
    if A is None or not A.is_matrix or bv is None or not bv.is_matrix:
        raise SceneUnavailable("no A and b to draw a column space from")
    M = A.obj
    ambient = int(M.rows)
    if ambient not in (2, 3):
        raise SceneUnavailable("only 2D and 3D column spaces are drawable")
    cols = [[real(x) for x in M.col(j)] for j in range(M.cols)]
    cols = [c for c in cols if c and not any(x is None for x in c)]
    if not (1 <= len(cols) <= 3):
        raise SceneUnavailable("between one and three columns are drawable")
    probe = _flat(bv)
    if not probe or len(probe) != ambient:
        raise SceneUnavailable("b is not a drawable vector of the right size")
    actual = int(sp.Matrix.hstack(*[sp.Matrix(c) for c in cols]).rank())
    if actual >= ambient:
        raise SceneUnavailable("the columns already reach everything; nothing is missed")
    return "SpanCompare", {
        "vectors": cols, "claimed_dim": ambient, "actual_dim": actual,
        "probe": probe, "ambient": ambient,
        "student_label": "WHAT YOU ASSUMED A REACHES",
        "correct_label": "WHAT A ACTUALLY REACHES",
    }


def _vector_list(env: dict[str, Val]) -> list[list[float]]:
    V = env.get("V")
    if V is not None and V.is_matrix:
        M = V.obj
        if V.kind == "vector_list":
            raw = [[real(x) for x in M.row(i)] for i in range(M.rows)]
        else:
            raw = [[real(x) for x in M.col(j)] for j in range(M.cols)]
        return [r for r in raw if r and not any(x is None for x in r)]
    out = []
    for key in ("v1", "v2", "v3", "u", "v", "w"):
        val = env.get(key)
        if val is not None and val.is_matrix and min(val.obj.shape) == 1:
            cand = [real(x) for x in _col(val.obj)]
            if cand and not any(x is None for x in cand):
                out.append(cand)
    return out


def _unreachable_probe(M: sp.Matrix, ambient: int) -> Optional[list[float]]:
    """A vector VERIFIED outside the span - an animated search that could succeed is a lie."""
    rank = M.rank()
    for cand in [sp.eye(ambient).col(i) for i in range(ambient)]:
        if sp.Matrix.hstack(M, cand).rank() > rank:
            out = [real(x) for x in cand]
            return None if any(x is None for x in out) else out
    return None


def _minimal(verdict: Verdict) -> tuple[str, dict[str, Any]]:
    """The floor. Built from nothing but the step id, so it cannot fail.

    ``_static`` is meant to be the bottom of the ladder, but it still reads the
    extraction, and anything that reads the extraction can be surprised by it.
    This one reads nothing.
    """
    return "StaticStepHighlight", {
        "lines": [{"kind": "text", "text": "your work"}],
        "focus": {"line": 0, "chars": [0, 9]},
        "annotation": "look again at this step",
        "pairing": None,
        "student_label": "WHAT YOU WROTE",
        "correct_label": "WHAT TO LOOK AT",
    }


def _static(verdict, ext, env, S, C):
    """The bottom of the ladder. Guards that cannot fail (SCENE_CATALOG.md T3)."""
    lines: list[dict[str, Any]] = []
    idx = verdict.first_error_index
    steps = sorted(ext.steps, key=lambda s: (s.page, s.reading_order))
    window = steps[max(0, (idx or 0) - 2): (idx or 0) + 1] if steps else []
    focus_line = 0
    for i, st in enumerate(window):
        disp = None
        if st.value is not None and st.value.rows:
            disp = [[fmt_num(x) for x in row] for row in st.value.rows]
        if disp and len(disp) <= 4 and len(disp[0]) <= 4:
            prefix = (st.claimed_expression or "").strip()[:12]
            lines.append({"kind": "matrix", "rows": disp, "prefix": f"{prefix} =" if prefix else ""})
        else:
            lines.append({"kind": "text", "text": (st.raw_text or "")[:60]})
        if idx is not None and st.id == verdict.step_id:
            focus_line = i
    if not lines:
        lines = [{"kind": "text", "text": "your work"}]
        focus_line = 0

    focus: dict[str, Any] = {"line": focus_line}
    cell = _first_differing_cell(S, C)
    if cell and lines[focus_line]["kind"] == "matrix":
        focus["cell"] = cell
    else:
        focus["chars"] = [0, min(len(lines[focus_line].get("text", "") or "x"), 40)]

    failing = next((st for st in steps if st.id == verdict.step_id), None)
    operands = list(getattr(getattr(failing, "op_args", None), "source_symbols", None) or [])
    pairing = _pairing(verdict, env, S, C, operands)
    annotation = _annotation(verdict, S, C, pairing)
    params: dict[str, Any] = {
        "lines": lines[:6],
        "focus": focus,
        "annotation": annotation,
        "pairing": pairing,
        "student_label": "WHAT YOU WROTE",
        "correct_label": "WHAT TO LOOK AT",
    }
    return "StaticStepHighlight", params


def _first_differing_cell(S: Optional[Val], C: Optional[Val]) -> Optional[list[int]]:
    a, b = _rows(S), _rows(C)
    if not a or not b:
        return None
    for i in range(min(len(a), len(b))):
        for j in range(min(len(a[i]), len(b[i]))):
            if abs(a[i][j] - b[i][j]) > 1e-9:
                return [i, j]
    return None


def _annotation(verdict: Verdict, S: Optional[Val], C: Optional[Val],
                pairing: Optional[dict] = None) -> str:
    if verdict.error_id == "LA03":
        return "count the inner dimensions"
    if verdict.error_id == "LA18":
        return "one side is a number, the other is an arrow"
    if S is not None and C is not None and S.is_matrix and C.is_matrix and S.obj.shape != C.obj.shape:
        return "the shapes on the two sides do not match"
    # When the sweep is about to run, name the row and column it sweeps. "look
    # again at the marked entry" made the student hunt for what was marked and
    # why -- and it says nothing a box around the cell has not already said.
    if pairing:
        i, j = pairing["target"]
        return f"this entry comes from row {i + 1} and column {j + 1}"
    if _first_differing_cell(S, C):
        cell = _first_differing_cell(S, C)
        return f"check the entry in row {cell[0] + 1}, column {cell[1] + 1}"
    return "look again at the marked entry"


def _pairing(verdict: Verdict, env: dict[str, Val], S: Optional[Val], C: Optional[Val],
             operands: Optional[list[str]] = None):
    """The sweep that shows WHERE a product entry came from: row i across the
    left operand, column j down the right one, landing on the cell that differs.

    This used to require error_id == "LA01" and both operands exactly 2x2, so a
    3x3 product with one wrong entry -- a computation error, and the case the
    animation is for -- got the static highlight and a generic caption instead.
    The scene itself was never 2x2-only: it reads A.n_rows / B.n_cols and sweeps
    whatever it is given. So the size test is gone and the operands are taken
    from the step rather than assumed to be called A and B.

    Still refused when more than one entry differs: two wrong cells are not one
    mis-paired row, and sweeping a single cell would misrepresent that.
    """
    A = B = None
    if operands and len(operands) >= 2:
        A, B = env.get(operands[0]), env.get(operands[1])
    if A is None or B is None:
        A, B = env.get("A"), env.get("B")

    cell = _first_differing_cell(S, C)
    if cell is None or A is None or B is None:
        return None
    if not (A.is_matrix and B.is_matrix and S is not None and S.is_matrix):
        return None

    # The sweep claims "row i of the left, column j of the right". That is only
    # true if the shapes really compose that way.
    if A.obj.shape[1] != B.obj.shape[0]:
        return None
    if S.obj.shape != (A.obj.shape[0], B.obj.shape[1]):
        return None
    if not (0 <= cell[0] < A.obj.shape[0] and 0 <= cell[1] < B.obj.shape[1]):
        return None
    if _differing_cell_count(S, C) != 1:
        return None

    a_rows, b_rows = _display(A), _display(B)
    s_rows, c_rows = _display(S), _display(C)
    if not (a_rows and b_rows and s_rows and c_rows):
        return None
    return {
        "A_rows": a_rows, "B_rows": b_rows,
        "target": cell,
        "student_entry": s_rows[cell[0]][cell[1]],
        "correct_entry": c_rows[cell[0]][cell[1]],
        # Only LA01 means "you ran along a row where a column belonged". For
        # any other slip we know WHERE the entry came from but not how they
        # got it wrong, and the scene must not invent a path.
        "wrong_source": "row" if verdict.error_id == "LA01" else None,
    }


def _differing_cell_count(S: Optional[Val], C: Optional[Val]) -> int:
    a, b = _rows(S), _rows(C)
    if not a or not b:
        return 0
    n = 0
    for i in range(min(len(a), len(b))):
        for j in range(min(len(a[i]), len(b[i]))):
            if abs(a[i][j] - b[i][j]) > 1e-9:
                n += 1
    return n


# --------------------------------------------------------------------------
# For the API layer
# --------------------------------------------------------------------------

def summarize(verdict: Verdict, plan_obj: Plan) -> dict[str, Any]:
    """The §4.9 output contract, JSON-ready."""
    return {
        "first_error_index": verdict.first_error_index,
        "step_id": verdict.step_id,
        "student_label": verdict.student_label,
        "confidence": verdict.confidence,
        "error_id": verdict.error_id,
        "student_value": val_json(verdict.student_value),
        "correct_value": val_json(verdict.correct_value),
        "scene_template": plan_obj.template,
        "scene_params": plan_obj.params,
        "positional_hint": plan_obj.hint,
        "flags": verdict.flags,
    }
