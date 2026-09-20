"""photo bytes -> structured, verifiable steps.

Implements docs/EXTRACTION.md: the Pydantic mirror (§2.4), the system prompt (§3),
image preparation (§5.2), the vision call (§5.3), and the silent-correction guard
(§6.1).

The model is a TRANSCRIBER, not a solver. Everything here exists to keep it that way.

Fixture mode
------------
Set ``USE_FIXTURE=1`` (or pass ``fixture=<name>``) and this module returns a canned
extraction from ``samples/`` instead of calling the API. The whole pipeline
(verify -> hint -> render) then runs fully live with no API key and no network,
which is both how you develop at 3am and the demo insurance of §7.5.
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

# --------------------------------------------------------------------------
# Paths / configuration
# --------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = Path(os.environ.get("SAMPLES_DIR", REPO_ROOT / "samples"))

MODEL = os.environ.get("EXTRACTION_MODEL", "claude-opus-5")
MAX_TOKENS = int(os.environ.get("EXTRACTION_MAX_TOKENS", "16000"))
API_TIMEOUT = float(os.environ.get("EXTRACTION_TIMEOUT", "90"))

# Opus 5, high-resolution vision tier (docs/EXTRACTION.md §5.1/§5.2)
MAX_EDGE, MAX_VISUAL_TOKENS, PATCH = 2576, 4784, 28

# Non-Anthropic providers bill images in 512px tiles, and new OpenAI accounts
# start at 10k tokens per MINUTE. 2576px burns that budget on pixels that do not
# make handwriting more readable. Override with PROVIDER_MAX_EDGE.
PROVIDER_MAX_EDGE = int(os.environ.get("PROVIDER_MAX_EDGE", "1200"))

_TRUE = {"1", "true", "yes", "on"}


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


def _fixture_flag_set() -> bool:
    """True when fixture mode was ASKED for, as opposed to fallen back into."""
    return _flag("USE_FIXTURE") or _flag("EXTRACT_USE_FIXTURE")


def use_fixture_mode() -> bool:
    """Fixture mode is on if USE_FIXTURE is set, or if there is no API key."""
    if _fixture_flag_set():
        return True
    if _flag("USE_FIXTURE_OFF"):
        return False
    return not have_api_key()


def have_api_key() -> bool:
    """A key for ANY supported vision provider, not just Anthropic.

    A team on a free tier sets GEMINI_API_KEY instead; treating that as "no key"
    would silently drop them back into fixture mode and hand them a canned
    sample in place of their own photograph.
    """
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
    )


# --------------------------------------------------------------------------
# §2.4 Pydantic mirror of the output schema
# --------------------------------------------------------------------------

Kind = Literal[
    "matrix", "vector", "vector_list", "scalar", "scalar_list",
    "polynomial", "augmented", "text", "unknown",
]


class MathObject(BaseModel):
    kind: Kind
    shape: Optional[list[int]] = None
    orientation: Optional[Literal["row", "column", "unspecified"]] = None
    rows: Optional[list[list[float]]] = None
    exact: Optional[list[list[str]]] = None
    scalars: Optional[list[float]] = None
    exact_scalars: Optional[list[str]] = None
    var: Optional[str] = None
    text: Optional[str] = None
    wrote_decimals: bool = False

    # A characteristic matrix has no decimal form: the entries of A - lambda*I
    # are "2-lambda", not numbers. N2 asks for the decimal in `rows` as well,
    # which cannot be done for a purely symbolic entry, so the model puts the
    # symbol there and validation used to reject the whole extraction.
    #
    # `exact` is the field for this and verify.to_sympy() already prefers it
    # over `rows`, so the entries are simply moved across rather than refused.
    # Numeric extractions are untouched: this only fires when an entry is not
    # a number.
    @model_validator(mode="before")
    @classmethod
    def _symbols_belong_in_exact(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        def numeric(v: Any) -> bool:
            if isinstance(v, bool):
                return False
            if isinstance(v, (int, float)):
                return True
            try:
                float(str(v).strip())
                return True
            except (TypeError, ValueError):
                return False

        rows = data.get("rows")
        if isinstance(rows, list) and any(
            not numeric(e) for r in rows if isinstance(r, list) for e in r
        ):
            if not data.get("exact"):
                data["exact"] = [
                    [str(e).strip() for e in r] for r in rows if isinstance(r, list)
                ]
            data["rows"] = None

        scalars = data.get("scalars")
        if isinstance(scalars, list) and any(not numeric(e) for e in scalars):
            if not data.get("exact_scalars"):
                data["exact_scalars"] = [str(e).strip() for e in scalars]
            data["scalars"] = None

        return data


class BBox(BaseModel):
    x: int
    y: int
    w: int
    h: int


class Ambiguity(BaseModel):
    where: str
    entry: Optional[list[int]] = None
    read_as: str
    could_be: list[str] = Field(default_factory=list)
    kind: Literal[
        "digit_shape", "sign", "fraction_bar", "decimal_point",
        "subscript", "bracket_grouping", "smudge", "other",
    ] = "other"


class OpArgs(BaseModel):
    rows: Optional[list[int]] = None
    scalar: Optional[str] = None
    source_symbols: Optional[list[str]] = None
    note: Optional[str] = None


class Step(BaseModel):
    id: str
    student_label: Optional[str] = None
    page: int = 1
    reading_order: int = 0
    bbox: Optional[BBox] = None
    raw_text: str = ""
    claimed_expression: Optional[str] = None
    claimed_operation: str = "unknown"
    op_args: OpArgs = Field(default_factory=OpArgs)
    value: Optional[MathObject] = None
    alternates: list[MathObject] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    crossed_out: bool = False
    is_final_answer: bool = False
    parse_ok: bool = True
    confidence: float = Field(default=0.5, ge=0, le=1)
    confidence_reason: Optional[str] = None


class Given(BaseModel):
    symbol: str
    object: MathObject
    source: Literal["printed", "copied", "inferred"] = "printed"
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    alternates: list[MathObject] = Field(default_factory=list)
    confidence: float = Field(default=0.9, ge=0, le=1)


class Problem(BaseModel):
    present: bool = True
    statement: Optional[str] = None
    topic: str = "other"
    asks_for: Optional[str] = None
    givens: list[Given] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0, le=1)


class Document(BaseModel):
    page_count: int = 1
    legibility: Literal["clean", "usable", "poor", "unreadable"] = "usable"
    orientation_ok: bool = True
    multiple_problems_detected: bool = False
    notes: Optional[str] = None


class UnreadableRegion(BaseModel):
    page: int = 1
    bbox: Optional[BBox] = None
    why: str = ""
    between_steps: Optional[list[str]] = None


class ExtractionMeta(BaseModel):
    unreadable_regions: list[UnreadableRegion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FinalAnswer(BaseModel):
    step_id: Optional[str] = None
    object: Optional[MathObject] = None


class Extraction(BaseModel):
    document: Document = Field(default_factory=Document)
    problem: Problem = Field(default_factory=Problem)
    steps: list[Step] = Field(default_factory=list)
    final_answer: FinalAnswer = Field(default_factory=FinalAnswer)
    extraction: ExtractionMeta = Field(default_factory=ExtractionMeta)


# Hand-written and deliberately terse. Extraction.model_json_schema() is ~7000
# characters of $defs and validation metadata; as dense JSON that is most of a
# new OpenAI account's 10,000-tokens-per-MINUTE budget, so a second upload
# inside a minute got a 429. This says the same thing in a tenth of the space,
# and only the fields the pipeline actually reads. Anything extra the model
# emits is ignored, and anything missing has a default on the model.
_COMPACT_SCHEMA = """{
  "problem": {"statement": str, "topic": str, "asks_for": str,
              "givens": [{"symbol": str, "object": OBJ}]},
  "steps": [{"id": "s1", "student_label": "1)", "reading_order": int,
             "raw_text": "the line exactly as written",
             "claimed_operation": OP, "value": OBJ,
             "crossed_out": bool, "is_final_answer": bool,
             "parse_ok": bool, "confidence": 0..1,
             "ambiguities": [{"where": str, "read_as": str, "could_be": [str]}]}],
  "document": {"legibility": "clean|usable|poor|unreadable"}
}

OBJ is one of:
  {"kind":"matrix","rows":[[1,2],[3,4]]}
  {"kind":"vector","rows":[[3,4]]}
  {"kind":"scalar","scalars":[5]}          also "exact_scalars":["sqrt(5)"]
  {"kind":"text","text":"..."}             when it is not numeric

OP is one of: copy_given multiply add subtract scalar_multiply transpose
determinant_expand cofactor inverse_formula augment row_swap row_scale
row_add_multiple back_substitute char_poly solve_char_poly eigenvector_solve
normalize dot cross project state_answer unknown"""


def _free_tier_user_prompt() -> str:
    """The user turn for providers without structured-output support.

    Anthropic is handed the schema through the SDK and never sees this. OpenAI,
    Gemini and OpenRouter only guarantee "some JSON", so the shape has to be
    stated in the prompt -- and the transcriber-not-solver rule repeated, since
    it is the instruction most easily lost behind a wall of schema.
    """
    return (
        "Transcribe the handwritten work in the image(s) into JSON of this "
        "shape. Output ONLY the JSON object: no prose, no markdown fence.\n\n"
        f"{_COMPACT_SCHEMA}\n\n"
        "Record what is ON THE PAGE, mistakes included. Do not correct "
        "arithmetic, do not solve the problem, do not skip a step because it is "
        "wrong: a step you silently fix is a step the student never learns "
        "from. One step per written line, in reading order. Set parse_ok false "
        "and confidence low rather than guessing, and list every digit you are "
        "unsure of in ambiguities."
    )


class ExtractionError(RuntimeError):
    """Base for anything that stops us producing an Extraction."""


class ExtractionRefused(ExtractionError):
    pass


class ExtractionTruncated(ExtractionError):
    pass


# --------------------------------------------------------------------------
# §3 The system prompt (verbatim)
# --------------------------------------------------------------------------

EXTRACTION_SYSTEM = """\
You transcribe photographs of handwritten linear algebra homework into structured data.

## Your one job

You are a TRANSCRIBER, not a tutor and not a solver. You record what is physically on
the paper, including everything that is wrong with it. Another system checks the
mathematics. If you fix anything, that system has nothing to find and the student never
learns what they did.

This is the single way this task fails, so it is worth stating concretely:

  The page shows a 2x2 product where the bottom-left entry should be 3*4 + 1*2 = 14,
  and the student has written 2. You write 2. You do not write 14. You do not write 14
  with a note. You do not mention that 14 is correct. You write 2, with high confidence,
  and move on.

Copy the pen, not the mathematics. Never compute, never simplify, never reorder, never
normalize, never complete a half-finished line, never silently repair a shape mismatch.
If the student wrote a 3x2 matrix where a 2x2 was needed, you emit a 3x2 matrix.

You may reason internally about what a glyph is. You must not reason about whether the
mathematics is right, because that reasoning leaks into what you transcribe.

## Reading the page

R1. Order by geometry, not by importance: page, then top to bottom. If the work is in
    columns, finish the left column before starting the right one. If arrows or "cont."
    indicate a different flow, follow the arrows and say so in `document.notes`.

R2. Separate the PROBLEM from the WORK. The problem is the printed or copied statement
    of what was asked -- "Compute AB", "Find the inverse of M", the given matrices. The
    work is everything the student produced. Givens go in `problem.givens`; the
    student's own lines go in `steps`.

R3. A STEP is one line the student is claiming to be true: a labeled result, a matrix
    they wrote down, an equation, a row operation with its outcome. Scratch arithmetic
    off to the side (a lone "3*4=12" in the margin) is a step too, with
    `claimed_operation: "multiply"` and a low `reading_order` tie to the line it serves.
    Do not merge two written lines into one step, and do not split one line into two.

R4. Crossed-out, erased, or abandoned work is still transcribed, in position, with
    `crossed_out: true`. Students restart constantly and the downstream system needs to
    know which lines were abandoned so it does not accuse them of an error they already
    threw away.

R5. `student_label` is the student's own numbering exactly as written -- "3)", "(ii)",
    "Step 2", "b." -- or null. Never invent one. It is used to speak to the student in
    their own terms.

R6. `bbox` is `{x, y, w, h}` in pixels of the image as you received it, tight around the
    step's written line, padded by a few pixels. Approximate is fine; it is used to draw
    a highlight box, never to crop.

## Numbers

N1. Entries go in `rows` as JSON numbers. `[[6, -5], [2, 5]]`. Not strings, not LaTeX,
    no "\\frac", no "\\begin{pmatrix}".

N2. If any entry of an object is not a finite decimal -- a fraction, a radical, a symbol,
    a repeating decimal -- ALSO fill `exact` with the same shape, entries as plain
    sympy-parseable strings: "1/3", "-2/7", "sqrt(2)/2", "3*sqrt(5)", "lambda",
    "lambda - 2". Put the decimal value in `rows` as well WHEN THERE IS ONE. A purely
    symbolic entry has none -- the entries of a characteristic matrix A - lambda*I are
    "2-lambda", not numbers -- so in that case fill `exact` and set `rows` to null
    rather than putting the symbol in `rows`. If every entry is a finite decimal,
    `exact` is null.

N3. `wrote_decimals` is true when the student's pen wrote a decimal point, false when
    they wrote an integer, fraction or radical. It describes their notation, not your
    encoding. 0.71 written by hand is true; 1/sqrt(2) encoded by you as rows 0.7071 is
    false.

N4. A vector written horizontally in parentheses, like (1, 2, 3), with no indication of
    row or column: `kind: "vector"`, `orientation: "unspecified"`, `rows` as a single
    row. Do not guess. Only use "row" or "column" when the page is explicit -- bracket
    shape, a transpose mark, or the surrounding equation forces it.

N5. `shape` is what the student's brackets enclose. If their brackets and their entries
    disagree, report the brackets in `shape`, the entries in `rows`, and note it in
    `confidence_reason`.

## Ambiguity -- this is the important part

Handwritten digits are genuinely ambiguous. 4 and 9 close the same way. 1 and 7 differ by
a stroke many people omit. A minus sign and a short fraction bar are the same mark. A
smudged 5 is a 6. Your job is to report the ambiguity, not to resolve it silently.

A1. Whenever a glyph could reasonably be read two ways, add an entry to `ambiguities`
    with what you read, what else it could be, the `kind`, and -- for matrix entries --
    `entry: [row, col]` zero-indexed.

A2. If a different reading would produce a materially different object, also emit that
    whole alternative object in `alternates`. At most 2 alternates. Order them most
    plausible first. `value` stays your best reading.

A3. Emit an alternate only when you would genuinely not be surprised to be wrong. Do not
    pad the list. Three confident candidates are worse than one honest one, because the
    checker accepts a step if ANY candidate makes it correct -- a fabricated alternate can
    hide a real mistake.

A4. Never resolve an ambiguity by checking which reading makes the arithmetic work. That
    is solving, and it is how a wrong answer gets laundered into a right one. Resolve by
    ink only: stroke shape, the student's other 4s and 9s elsewhere on the page, slant,
    pen pressure.

## Confidence

Per step, 0 to 1, and calibrated -- a column of 0.9s is useless. Anchors:

  0.95-1.0  Every glyph unambiguous. You would bet the demo on it.
  0.80-0.94 Readable. One or two glyphs identified from stroke shape without hesitation.
  0.55-0.79 A glyph or two judged partly from context or from the student's other
            handwriting. There should be an `ambiguities` entry.
  0.30-0.54 Guessing at one or more entries. Emit alternates.
  < 0.30    Set `parse_ok: false`, put your best partial reading in `raw_text`, set
            `value` to null, and add an `extraction.unreadable_regions` entry naming the
            steps on either side in `between_steps`.

`confidence_reason` is one short clause when confidence is below 0.95 -- "the 4 in the
lower left could be a 9", "faint pencil, second row inferred from spacing". Null above
0.95.

Be pessimistic. Understated confidence costs a click on a confirmation screen.
Overstated confidence costs a wrong accusation.

## The givens

G1. Extract every object the problem hands the student into `problem.givens`.

G2. `source` is "printed" if it is in the problem statement in print, "copied" if the
    student re-copied it into their work, "inferred" if the page never states it and you
    reconstructed it from the work. Inferred givens are treated with suspicion
    downstream; never mark something inferred as printed.

G3. Use the symbol the page uses. Where the page uses none, follow this convention:
    two matrices being multiplied are A and B in written order; a single matrix being
    inverted, or having its determinant or eigenvectors taken, is M; vectors are u and v
    in written order; a right-hand side of a linear system is b; a set of vectors whose
    span or independence is in question is V.

G4. If the page shows only work and no problem statement, set `problem.present: false`,
    infer `asks_for` from the work if you can, mark reconstructed givens "inferred", and
    lower `problem.confidence` accordingly.

G5. Givens carry their own `ambiguities`, `alternates` and `confidence`, under the same
    rules as steps (A1-A4). Apply them even harder here. Everything the student wrote is
    checked against these objects, so a misread given does not produce one wrong step --
    it produces a page of them, and the app accuses a student who did nothing wrong.

## raw_text

Required on every step. The closest plain-text rendering of the ink, in the order it
appears, before any interpretation:

  "AB = [6  -5 ; 2  5]"
  "R2 -> R2 - 2R1"
  "det = (2)(5) - (-1)(3)"

Use `;` between matrix rows, `->` for arrows, `|` for an augmentation bar. `raw_text`
and `value` must agree digit for digit. They are cross-checked. If you find yourself
writing different numbers in the two fields, the one in `raw_text` is right and you are
about to correct the student's arithmetic.

## Refusals

Every required field must be filled, but "I could not read this" is always expressible:
`parse_ok: false`, `value: null`, low confidence, an `unreadable_regions` entry. Use it.
A null is a fact. An invented matrix is a lie that survives all the way to the animation.

If the photo contains no mathematics, is blank, or is too dark or blurred to read at all:
`document.legibility: "unreadable"`, `problem.present: false`, `steps: []`, and one
plain sentence in `extraction.warnings` describing what you see and what would fix it
("photo is out of focus", "page is cut off at the right edge").

Output only the JSON object described by the schema.
"""

USER_CLOSER = (
    "Transcribe this handwritten linear algebra work. "
    "Remember: copy what is written, including mistakes. Do not compute anything."
)
USER_CLOSER_MULTI = (
    "Transcribe this handwritten linear algebra work. Images are pages in order. "
    "Remember: copy what is written, including mistakes. Do not compute anything."
)


# --------------------------------------------------------------------------
# §5.2 Image preparation
# --------------------------------------------------------------------------

def _pil():
    from PIL import Image, ImageOps  # noqa: WPS433 (deferred: PIL is heavy)

    try:  # iPhones shoot HEIC by default and the API will not take it.
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except Exception:  # pragma: no cover - optional dependency
        pass
    return Image, ImageOps


def visual_tokens(w: int, h: int) -> int:
    return math.ceil(w / PATCH) * math.ceil(h / PATCH)


def fit_for_model(img, max_edge: int | None = None):
    """Largest size that trips neither the long-edge nor the visual-token limit."""
    Image, _ = _pil()
    w, h = img.size
    scale = min(1.0, (max_edge or MAX_EDGE) / max(w, h))  # never upscale
    while True:
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        if visual_tokens(nw, nh) <= MAX_VISUAL_TOKENS:
            if (nw, nh) == (w, h):
                return img
            return img.resize((nw, nh), Image.LANCZOS)
        scale *= 0.97


def prepare(data: bytes, *, max_edge: int | None = None) -> tuple[bytes, str, tuple[int, int]]:
    """EXIF-rotate, convert to RGB JPEG, downscale to exactly what the model will see.

    The returned bytes are also what the frontend should display, so the bounding
    boxes the model returns line up with the pixels on screen (§5.2 point 3).
    """
    Image, ImageOps = _pil()
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    # convert("RGB") composites transparency onto BLACK. A PDF page rendered in
    # the browser arrives as a PNG whose background is transparent, so this one
    # line turned every uploaded PDF into black ink on a black field: the model
    # saw a blank sheet, transcribed nothing, and the student was told their
    # wrong work was fine. Flatten onto white -- the colour paper actually is --
    # before dropping the alpha.
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        img = img.convert("RGBA")
        img = Image.alpha_composite(Image.new("RGBA", img.size, (255, 255, 255, 255)), img)
    img = img.convert("RGB")
    img = fit_for_model(img, max_edge)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92, optimize=True)  # NOT 60: thin strokes
    return buf.getvalue(), "image/jpeg", img.size


# --------------------------------------------------------------------------
# §6.1 The failure that kills the product: silent correction
# --------------------------------------------------------------------------

NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _derivable(nums: list[float]) -> set[float]:
    """Results a student could reach by combining two numbers written side by side.

    Row reduction is written as PENDING ARITHMETIC: "R2 = [-3 -3  -2 + 3 | 13 - 12]".
    The evaluated row -- -6, 1, 1 -- is by definition made of numbers that are not
    literally on the page, so a guard that only looks for literal digits flags a
    PERFECT transcription of every row operation a student has ever written.

    So count what the written numbers can produce, not just the written numbers.
    Adjacent pairs under + - * covers how row arithmetic is actually laid out,
    without needing to know which spacing groups with which.
    """
    out: set[float] = set()
    for a, b in zip(nums, nums[1:]):
        out.update((abs(a + b), abs(a - b), abs(b - a), abs(a * b)))
    return out


def silent_correction_suspected(step: Step) -> bool:
    """value contains a number the pen never wrote AND could not have worked out."""
    if not step.parse_ok or step.value is None:
        return False
    if step.value.kind not in ("matrix", "vector", "vector_list", "augmented"):
        return False
    if "[" not in step.raw_text:  # value wasn't literally written on this line
        return False
    nums = [float(x) for x in NUM.findall(step.raw_text)]
    written = {abs(x) for x in nums} | _derivable(nums)
    claimed = {abs(float(v)) for row in (step.value.rows or []) for v in row}
    # Still fires on real fabrication: a model that quietly fixes [6 -5; 2 5] to
    # [6 -5; 14 5] cannot get 14 out of any pair on that line.
    return bool(claimed - written)


def audit(extraction: Extraction) -> list[str]:
    """Non-fatal quality notes. Fires the §6.1 guard and floors confidence."""
    notes: list[str] = []
    for step in extraction.steps:
        if silent_correction_suspected(step):
            step.confidence = min(step.confidence, 0.3)
            notes.append(
                f"step {step.id}: transcribed value contains a number that is not in "
                f"raw_text ({step.raw_text!r}) - possible silent correction, flagged for review"
            )
    if extraction.document.legibility == "unreadable":
        notes.append("photo was not readable")
    for given in extraction.problem.givens:
        if given.source == "inferred":
            notes.append(f"given {given.symbol} was inferred, not read from the page")
    return notes


# --------------------------------------------------------------------------
# Fixtures (§7.5 demo insurance, and how you develop with no API key)
# --------------------------------------------------------------------------

def _fixture_path(name: str) -> Path:
    name = re.sub(r"[^A-Za-z0-9_.-]", "", name)
    if name.endswith(".json"):
        name = name[:-5]
    return SAMPLES_DIR / f"{name}.json"


def list_fixtures() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not SAMPLES_DIR.is_dir():
        return out
    for path in sorted(SAMPLES_DIR.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            blob = json.loads(path.read_text())
        except Exception:
            continue
        meta = blob.get("_meta", {}) if isinstance(blob, dict) else {}
        out.append(
            {
                "name": path.stem,
                "title": meta.get("title", path.stem),
                "error_id": meta.get("error_id"),
                "topic": meta.get("topic"),
                "expect": meta.get("expect"),
            }
        )
    return out


def load_fixture(name: str) -> Extraction:
    path = _fixture_path(name)
    if not path.is_file():
        available = ", ".join(f["name"] for f in list_fixtures()) or "(none)"
        raise ExtractionError(f"no fixture named {name!r} in {SAMPLES_DIR} (have: {available})")
    blob = json.loads(path.read_text())
    blob.pop("_meta", None)
    return Extraction.model_validate(blob)


DEFAULT_FIXTURE = os.environ.get("FIXTURE_NAME", "la_multiply")


def _fixture_for(filenames: list[str] | None, explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("FIXTURE_NAME")
    if env:
        return env
    known = {f["name"] for f in list_fixtures()}
    for fn in filenames or []:
        stem = Path(fn).stem
        if stem in known:
            return stem
    return DEFAULT_FIXTURE


# --------------------------------------------------------------------------
# §5.3 The call
# --------------------------------------------------------------------------

def _image_blocks(images: list[bytes]) -> tuple[list[dict], list[tuple[int, int]]]:
    content: list[dict] = []
    sizes: list[tuple[int, int]] = []
    multi = len(images) > 1
    for i, raw in enumerate(images, start=1):
        try:
            data, media_type, size = prepare(raw)
        except Exception as exc:
            # PIL's own message ("cannot identify image file") reaches the
            # student as a stack trace and tells them nothing to do about it.
            raise ExtractionError(
                f"could not read image {i} of {len(images)} - it is not a photo we "
                f"can open (JPEG, PNG and HEIC all work). Try taking the picture "
                f"again. [{type(exc).__name__}: {exc}]"
            ) from exc
        sizes.append(size)
        if multi:
            content.append({"type": "text", "text": f"Image {i}:"})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(data).decode("utf-8"),
                },
            }
        )
    content.append({"type": "text", "text": USER_CLOSER_MULTI if multi else USER_CLOSER})
    return content, sizes


def _call_api(images: list[bytes]) -> tuple[Extraction, dict[str, Any]]:
    # A team without a card on file can run this on a free tier instead; see
    # backend/vision_providers.py. Anthropic keeps its own path below because it
    # is the only one with real structured-output support.
    from . import vision_providers

    try:
        provider = vision_providers.active_provider()
    except vision_providers.ProviderError as exc:
        raise ExtractionError(str(exc)) from exc

    if provider and provider != "anthropic":
        # The Anthropic branch below runs every image through _image_blocks ->
        # prepare(), which EXIF-rotates and downscales. This branch sent the RAW
        # bytes, so a 4000x3000 phone photo went out at full size and a single
        # request cost ~7000 tokens -- over a 10k-per-minute account limit in two
        # uploads. Downscale here too, harder: OpenAI bills images in 512px
        # tiles, so past roughly 1200px the extra pixels cost tokens without
        # making handwriting any more legible.
        try:
            prepared = [prepare(b, max_edge=PROVIDER_MAX_EDGE)[0] for b in images]
        except Exception:
            prepared = images          # unreadable by PIL: let the API judge it

        try:
            raw, meta = vision_providers.extract_json(
                prepared, EXTRACTION_SYSTEM, _free_tier_user_prompt(), provider
            )
        except vision_providers.ProviderError as exc:
            raise ExtractionError(str(exc)) from exc
        return Extraction.model_validate(raw), meta

    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError(
            "the anthropic SDK is not installed - run: bash scripts/setup.sh"
        ) from exc

    if not have_api_key():
        # Without this the SDK raises "Could not resolve authentication method",
        # which names neither the variable nor the fix.
        raise ExtractionError(
            "ANTHROPIC_API_KEY is not set, so photographs cannot be read. Either "
            "export ANTHROPIC_API_KEY=sk-ant-... and restart, or run in fixture "
            "mode (USE_FIXTURE=1, which is what scripts/run.sh does by default)."
        )

    content, _sizes = _image_blocks(images)
    client = anthropic.Anthropic()
    system = [{"type": "text", "text": EXTRACTION_SYSTEM, "cache_control": {"type": "ephemeral"}}]
    kwargs: dict[str, Any] = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive"},
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }

    meta: dict[str, Any] = {"model": MODEL}
    opts = client.with_options(timeout=API_TIMEOUT)

    parse = getattr(opts.messages, "parse", None)
    resp = None
    parsed: Extraction | None = None
    if parse is not None:
        try:
            resp = parse(output_format=Extraction, **kwargs)
            parsed = getattr(resp, "parsed_output", None)
        except TypeError:
            resp, parsed = None, None
        except Exception as exc:
            if _is_transport_error(exc):
                raise ExtractionError(f"vision call failed: {exc}") from exc
            resp, parsed = None, None

    if parsed is None:
        # Explicit-schema fallback (§5.3 tail): structured outputs without the helper.
        schema = Extraction.model_json_schema()
        try:
            resp = opts.messages.create(
                output_config={"format": {"type": "json_schema", "schema": schema}}, **kwargs
            )
        except TypeError:
            resp = opts.messages.create(**kwargs)
        except Exception as exc:
            raise ExtractionError(f"vision call failed: {exc}") from exc

    stop_reason = getattr(resp, "stop_reason", None)
    if stop_reason == "refusal":  # HTTP 200 with a refusal; never IndexError on stage
        raise ExtractionRefused(str(getattr(resp, "stop_details", "refusal")))
    if stop_reason == "max_tokens":
        raise ExtractionTruncated("response hit max_tokens; retry with a bigger budget")

    usage = getattr(resp, "usage", None)
    if usage is not None:
        meta["cache_read_input_tokens"] = getattr(usage, "cache_read_input_tokens", None)
        meta["input_tokens"] = getattr(usage, "input_tokens", None)
        meta["output_tokens"] = getattr(usage, "output_tokens", None)

    if parsed is None:
        parsed = Extraction.model_validate(_first_json(resp))
    return parsed, meta


def _is_transport_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    return any(k in name for k in ("connection", "timeout", "apistatus", "authentication", "ratelimit"))


def _first_json(resp: Any) -> dict:
    for block in getattr(resp, "content", []) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        text = text.strip()
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
    raise ExtractionError("no JSON object in the model response")


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def extract(
    images: list[bytes] | None = None,
    *,
    filenames: list[str] | None = None,
    fixture: str | None = None,
) -> tuple[Extraction, dict[str, Any]]:
    """Photo bytes -> Extraction.

    Returns ``(extraction, meta)``. ``meta`` carries ``source`` ("api" | "fixture"),
    elapsed seconds, and any audit notes. Never raises for a recoverable problem when
    a fixture fallback is available - the demo always produces something.
    """
    started = time.time()
    forced_fixture = fixture or (None if images else _fixture_for(filenames, None))

    if forced_fixture or use_fixture_mode() or not images:
        name = _fixture_for(filenames, fixture)
        ext = load_fixture(name)
        meta = {
            "source": "fixture",
            "fixture": name,
            "seconds": round(time.time() - started, 3),
            "notes": audit(ext),
        }
        # Someone photographed real work and we are about to hand back a canned
        # sample of somebody else's. That silently showed the wrong student the
        # wrong mistake, with nothing on screen to say so. Say so.
        # Warn whenever a photo came in and a canned sample goes out, whatever the
        # reason. Suppressing this when USE_FIXTURE was set deliberately covered
        # the most confusing case of all: scripts/run.sh sets USE_FIXTURE=1 by
        # default, so someone photographing a projection problem was shown a
        # matrix-multiply sample with nothing to say it was not their work.
        if images and not fixture:
            meta["substituted_for_photo"] = True
            if not have_api_key():
                meta["no_api_key"] = True
                meta["fell_back_because"] = (
                    f"Your photo was NOT read. This is the bundled sample '{name}'. "
                    "ANTHROPIC_API_KEY is not set: export it and restart with "
                    "scripts/run.sh --live to analyse real photographs."
                )
            else:
                meta["fell_back_because"] = (
                    f"Your photo was NOT read. This is the bundled sample '{name}'. "
                    "The server is in fixture mode; restart with "
                    "scripts/run.sh --live to analyse real photographs."
                )
        return ext, meta

    try:
        ext, api_meta = _call_api(images)
    except Exception as exc:
        if _flag("FIXTURE_ON_ERROR", True):
            name = _fixture_for(filenames, None)
            try:
                ext = load_fixture(name)
            except Exception:
                raise exc
            meta = {
                "source": "fixture",
                "fixture": name,
                "fell_back_because": f"{type(exc).__name__}: {exc}",
                "seconds": round(time.time() - started, 3),
                "notes": audit(ext),
            }
            return ext, meta
        raise

    meta = {"source": "api", "seconds": round(time.time() - started, 3), **api_meta}
    meta["notes"] = audit(ext)
    return ext, meta


def extraction_digest(ext: Extraction) -> str:
    """Stable hash of the *math* in an extraction - the speculative-render key (§7.4).

    Deliberately ignores prose (statement, notes, confidence) so that fixing a typo in
    the problem statement does not throw away a good render.
    """
    import hashlib

    payload = {
        "topic": ext.problem.topic,
        "givens": [
            {"symbol": g.symbol, "object": g.object.model_dump(include={"kind", "rows", "exact", "shape"})}
            for g in ext.problem.givens
        ],
        "steps": [
            {
                "id": s.id,
                "op": s.claimed_operation,
                "expr": s.claimed_expression,
                "crossed_out": s.crossed_out,
                "parse_ok": s.parse_ok,
                "value": s.value.model_dump(include={"kind", "rows", "exact", "shape"}) if s.value else None,
            }
            for s in ext.steps
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
