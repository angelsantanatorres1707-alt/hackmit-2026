# Handwriting Extraction: photo → verifiable steps

Owner of the boundary between **a phone photo of pencil on paper** and the structured
object `sympy_check` consumes. Everything downstream (`ERROR_TAXONOMY.md` §4, the scene
templates in §1) assumes the contract in §2 of this document.

Model ids, the vision request shape, and the image limits below were read from the Claude
API skill and `platform.claude.com/docs/en/build-with-claude/vision` on 2026-09-19. They
are not from memory. All arithmetic in the worked example (§4) was executed before being
written down.

**The one idea this document is built around:** the model is a *transcriber*, not a
solver. Its strongest instinct on a photo of botched matrix arithmetic is to fix the
arithmetic — to see `3·4 + 1·2 = 2` and write `14`, because 14 is correct. If it does
that even once, the app has nothing to find and nothing to animate. Every design choice
below (prompt, schema, the dual `raw_text`/`value` fields, the confirm screen) exists to
make transcription-without-correction the path of least resistance.

---

## 1. Pipeline

```
phone photo (HEIC/JPEG, 4032×3024, rotated)
  │
  ├─ 1a. normalize:  EXIF-rotate → convert to JPEG → downscale long edge to 2576px
  │                  (§5.2 — this exact image is also what the frontend displays,
  │                   so returned bounding boxes line up)
  │
  ├─ 1b. one vision call: claude-opus-5, image-then-text, structured output   (§5)
  │
  ├─ 1c. self-consistency guard: raw_text vs value  (§6.1 — catches silent correction)
  │
  ├─ 1d. CONFIRM SCREEN — "here's what I read"  (§7)
  │        └─ speculative verify+render starts here, before the student clicks
  │
  └─→ Extraction object → sympy_check (ERROR_TAXONOMY §4)
```

One API call. No separate OCR pass, no LaTeX intermediate, no second model. A page of
handwritten linear algebra at 2576px costs ~4784 visual tokens ≈ $0.024 on Opus 5 — the
budget is irrelevant, so spend it on one careful call rather than a cheap pipeline.

---

## 2. Output schema

### 2.1 Design decisions worth defending

**Numbers, not LaTeX — but with an exact escape hatch.** Matrices are `number[][]`.
Real linear algebra homework contains `1/3` and `√2/2`, which are not JSON numbers and
must not be silently rounded before sympy sees them. So each object carries:

| field | type | meaning |
|---|---|---|
| `rows` | `number[][]` | **always present.** Decimal value of every entry. Drives display and fast numeric checks. |
| `exact` | `string[][]` \| `null` | present **only if** some entry is not a finite decimal. sympy-parseable strings: `"1/3"`, `"sqrt(2)/2"`, `"-5"`, `"lambda"`. Never LaTeX. |

**Precedence rule, one line, no ambiguity:** if `exact` is non-null, `sympy_check` builds
`Matrix` from `exact` and treats `rows` as display-only. Otherwise it builds from `rows`.
There is never a case where both are authoritative.

**`wrote_decimals`** records whether the *student's pen* wrote a decimal (`0.71`) versus
whether our `rows` is a decimal shadow of an exact form the student wrote. This is exactly
the bit ERROR_TAXONOMY §4.4 tier 2 needs to decide whether to `nsimplify`. Without it the
verifier cannot tell `0.71` (rationalize, then grant rounding amnesty) from `1/√2`
(compare exactly).

**No recursion in the schema.** A basis or a list of eigenvectors is `kind:
"vector_list"` with one vector per row of `rows` — not a nested array of objects. Strict
structured-output schemas and recursive `$ref` are an unnecessary fight at 2 a.m.

**`raw_text` and `value` are both required, and they are redundant on purpose.** `raw_text`
is a literal character-level transcription; `value` is the parsed structure. A model that
quietly corrects arithmetic almost always corrects `value` while leaving `raw_text`
faithful, because `raw_text` is framed as copying and `value` as understanding. §6.1 turns
that redundancy into a cheap detector.

**`student_label`.** If the page says `3)`, the hint must say "your step 3" — the
student's numbering, never our array index. A hint that points at the wrong line is worse
than no hint.

### 2.2 JSON Schema

Strict-compatible: every property appears in `required`, `additionalProperties: false`
throughout, nullability expressed as a type union. `$defs` is used for `MathObject` and
is **not** recursive; if the API rejects `$defs`, inline it at its three use sites.

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["document", "problem", "steps", "final_answer", "extraction"],
  "properties": {

    "document": {
      "type": "object",
      "additionalProperties": false,
      "required": ["page_count", "legibility", "orientation_ok", "multiple_problems_detected", "notes"],
      "properties": {
        "page_count": {"type": "integer"},
        "legibility": {"type": "string", "enum": ["clean", "usable", "poor", "unreadable"]},
        "orientation_ok": {"type": "boolean"},
        "multiple_problems_detected": {"type": "boolean"},
        "notes": {"type": ["string", "null"]}
      }
    },

    "problem": {
      "type": "object",
      "additionalProperties": false,
      "required": ["present", "statement", "topic", "asks_for", "givens", "confidence"],
      "properties": {
        "present": {"type": "boolean"},
        "statement": {"type": ["string", "null"]},
        "topic": {
          "type": "string",
          "enum": ["matrix_multiply", "matrix_add", "scalar_multiply", "determinant",
                   "inverse", "transpose", "eigen", "rref", "solve_system", "span",
                   "dot_product", "cross_product", "projection", "norm", "other"]
        },
        "asks_for": {"type": ["string", "null"]},
        "givens": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["symbol", "object", "source", "ambiguities",
                         "alternates", "confidence"],
            "properties": {
              "symbol": {"type": "string"},
              "object": {"$ref": "#/$defs/MathObject"},
              "source": {"type": "string", "enum": ["printed", "copied", "inferred"]},
              "ambiguities": {"type": "array", "items": {"$ref": "#/$defs/Ambiguity"}},
              "alternates": {"type": "array", "maxItems": 2,
                             "items": {"$ref": "#/$defs/MathObject"}},
              "confidence": {"type": "number", "minimum": 0, "maximum": 1}
            }
          }
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
      }
    },

    "steps": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "student_label", "page", "reading_order", "bbox", "raw_text",
                     "claimed_expression", "claimed_operation", "op_args", "value",
                     "alternates", "ambiguities", "crossed_out", "is_final_answer",
                     "parse_ok", "confidence", "confidence_reason"],
        "properties": {
          "id": {"type": "string"},
          "student_label": {"type": ["string", "null"]},
          "page": {"type": "integer"},
          "reading_order": {"type": "integer"},
          "bbox": {"anyOf": [{"$ref": "#/$defs/BBox"}, {"type": "null"}]},
          "raw_text": {"type": "string"},
          "claimed_expression": {"type": ["string", "null"]},
          "claimed_operation": {
            "type": "string",
            "enum": ["copy_given", "multiply", "add", "subtract", "scalar_multiply",
                     "transpose", "determinant_expand", "cofactor", "inverse_formula",
                     "augment", "row_swap", "row_scale", "row_add_multiple",
                     "back_substitute", "char_poly", "solve_char_poly",
                     "eigenvector_solve", "normalize", "dot", "cross", "project",
                     "state_answer", "unknown"]
          },
          "op_args": {
            "type": "object",
            "additionalProperties": false,
            "required": ["rows", "scalar", "source_symbols", "note"],
            "properties": {
              "rows": {"type": ["array", "null"], "items": {"type": "integer"}},
              "scalar": {"type": ["string", "null"]},
              "source_symbols": {"type": ["array", "null"], "items": {"type": "string"}},
              "note": {"type": ["string", "null"]}
            }
          },
          "value": {"anyOf": [{"$ref": "#/$defs/MathObject"}, {"type": "null"}]},
          "alternates": {
            "type": "array",
            "maxItems": 2,
            "items": {"$ref": "#/$defs/MathObject"}
          },
          "ambiguities": {"type": "array", "items": {"$ref": "#/$defs/Ambiguity"}},
          "crossed_out": {"type": "boolean"},
          "is_final_answer": {"type": "boolean"},
          "parse_ok": {"type": "boolean"},
          "confidence": {"type": "number", "minimum": 0, "maximum": 1},
          "confidence_reason": {"type": ["string", "null"]}
        }
      }
    },

    "final_answer": {
      "type": "object",
      "additionalProperties": false,
      "required": ["step_id", "object"],
      "properties": {
        "step_id": {"type": ["string", "null"]},
        "object": {"anyOf": [{"$ref": "#/$defs/MathObject"}, {"type": "null"}]}
      }
    },

    "extraction": {
      "type": "object",
      "additionalProperties": false,
      "required": ["unreadable_regions", "warnings"],
      "properties": {
        "unreadable_regions": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["page", "bbox", "why", "between_steps"],
            "properties": {
              "page": {"type": "integer"},
              "bbox": {"anyOf": [{"$ref": "#/$defs/BBox"}, {"type": "null"}]},
              "why": {"type": "string"},
              "between_steps": {"type": ["array", "null"], "items": {"type": "string"}}
            }
          }
        },
        "warnings": {"type": "array", "items": {"type": "string"}}
      }
    }
  },

  "$defs": {
    "BBox": {
      "type": "object",
      "additionalProperties": false,
      "required": ["x", "y", "w", "h"],
      "properties": {
        "x": {"type": "integer"}, "y": {"type": "integer"},
        "w": {"type": "integer"}, "h": {"type": "integer"}
      }
    },

    "Ambiguity": {
      "type": "object",
      "additionalProperties": false,
      "required": ["where", "entry", "read_as", "could_be", "kind"],
      "properties": {
        "where": {"type": "string"},
        "entry": {"type": ["array", "null"], "items": {"type": "integer"}},
        "read_as": {"type": "string"},
        "could_be": {"type": "array", "items": {"type": "string"}},
        "kind": {
          "type": "string",
          "enum": ["digit_shape", "sign", "fraction_bar", "decimal_point",
                   "subscript", "bracket_grouping", "smudge", "other"]
        }
      }
    },

    "MathObject": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "shape", "orientation", "rows", "exact", "scalars",
                   "exact_scalars", "var", "text", "wrote_decimals"],
      "properties": {
        "kind": {
          "type": "string",
          "enum": ["matrix", "vector", "vector_list", "scalar", "scalar_list",
                   "polynomial", "augmented", "text", "unknown"]
        },
        "shape": {"type": ["array", "null"], "items": {"type": "integer"}},
        "orientation": {"type": ["string", "null"],
                        "enum": ["row", "column", "unspecified", null]},
        "rows": {
          "type": ["array", "null"],
          "items": {"type": "array", "items": {"type": "number"}}
        },
        "exact": {
          "type": ["array", "null"],
          "items": {"type": "array", "items": {"type": "string"}}
        },
        "scalars": {"type": ["array", "null"], "items": {"type": "number"}},
        "exact_scalars": {"type": ["array", "null"], "items": {"type": "string"}},
        "var": {"type": ["string", "null"]},
        "text": {"type": ["string", "null"]},
        "wrote_decimals": {"type": "boolean"}
      }
    }
  }
}
```

### 2.3 Field notes for whoever writes `sympy_check`

- **`scalar`** → `scalars: [6]`. **`polynomial`** → `scalars` are coefficients in
  descending powers of `var` (`λ² − 5λ + 6` is `scalars: [1,-5,6], var: "lambda"`).
  **`vector_list`** → one vector per row of `rows`; feed straight into
  `Matrix.hstack(*[Matrix(r) for r in rows])` for the span comparison in §4.3.
- **`orientation: "unspecified"`** means the student wrote `(1, 2, 3)` and the page does
  not say whether it is a row or a column. Be lenient on shape when you see this — it is
  a notation gap, not an LA03 shape error. Only flag LA03 when orientation is explicit.
- **`shape`** is what the student's brackets say, which may disagree with
  `len(rows) × len(rows[0])` when the handwriting is ragged. Shape mismatch is a
  parse-quality signal, not automatically a student error.
- **`alternates`** are complete alternative `MathObject`s for the whole step, so §4.7's
  "wrong only if all K candidates are wrong" is a plain loop over `[value] + alternates`.
  The model does the combinatorics; the verifier does not.
- **`crossed_out: true`** steps still appear in the array, in reading order. They feed the
  load-bearing test in §4.5 — do not drop them at ingest, or that test loses its evidence.

### 2.4 Pydantic mirror (backend)

```python
# backend/extraction_models.py
from typing import Literal, Optional
from pydantic import BaseModel, Field, conlist

Kind = Literal["matrix","vector","vector_list","scalar","scalar_list",
               "polynomial","augmented","text","unknown"]

class MathObject(BaseModel):
    kind: Kind
    shape: Optional[list[int]]
    orientation: Optional[Literal["row","column","unspecified"]]
    rows: Optional[list[list[float]]]
    exact: Optional[list[list[str]]]
    scalars: Optional[list[float]]
    exact_scalars: Optional[list[str]]
    var: Optional[str]
    text: Optional[str]
    wrote_decimals: bool

class BBox(BaseModel):
    x: int; y: int; w: int; h: int

class Ambiguity(BaseModel):
    where: str
    entry: Optional[list[int]]
    read_as: str
    could_be: list[str]
    kind: Literal["digit_shape","sign","fraction_bar","decimal_point",
                  "subscript","bracket_grouping","smudge","other"]

class OpArgs(BaseModel):
    rows: Optional[list[int]]
    scalar: Optional[str]
    source_symbols: Optional[list[str]]
    note: Optional[str]

class Step(BaseModel):
    id: str
    student_label: Optional[str]
    page: int
    reading_order: int
    bbox: Optional[BBox]
    raw_text: str
    claimed_expression: Optional[str]
    claimed_operation: str
    op_args: OpArgs
    value: Optional[MathObject]
    alternates: conlist(MathObject, max_length=2)
    ambiguities: list[Ambiguity]
    crossed_out: bool
    is_final_answer: bool
    parse_ok: bool
    confidence: float = Field(ge=0, le=1)
    confidence_reason: Optional[str]

class Given(BaseModel):
    symbol: str
    object: MathObject
    source: Literal["printed","copied","inferred"]
    ambiguities: list[Ambiguity]
    alternates: conlist(MathObject, max_length=2)
    confidence: float = Field(ge=0, le=1)

class Problem(BaseModel):
    present: bool
    statement: Optional[str]
    topic: str
    asks_for: Optional[str]
    givens: list[Given]
    confidence: float = Field(ge=0, le=1)

class Document(BaseModel):
    page_count: int
    legibility: Literal["clean","usable","poor","unreadable"]
    orientation_ok: bool
    multiple_problems_detected: bool
    notes: Optional[str]

class UnreadableRegion(BaseModel):
    page: int
    bbox: Optional[BBox]
    why: str
    between_steps: Optional[list[str]]

class ExtractionMeta(BaseModel):
    unreadable_regions: list[UnreadableRegion]
    warnings: list[str]

class FinalAnswer(BaseModel):
    step_id: Optional[str]
    object: Optional[MathObject]

class Extraction(BaseModel):
    document: Document
    problem: Problem
    steps: list[Step]
    final_answer: FinalAnswer
    extraction: ExtractionMeta
```

`problem.givens` is what becomes `G` in the `sympy_check` scope
(`G = {g.symbol: to_sympy(g.object) for g in problem.givens}`), so the symbol strings must
match the taxonomy's expectations — `A`, `B`, `M`, `u`, `v`, `b`, `V`. The system prompt
pins that naming (§3, rule G3).

---

## 3. The system prompt

Paste verbatim into `backend/prompts.py` as `EXTRACTION_SYSTEM`. It is static — cache it
(§5.4).

````text
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
    of what was asked — "Compute AB", "Find the inverse of M", the given matrices. The
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

R5. `student_label` is the student's own numbering exactly as written — "3)", "(ii)",
    "Step 2", "b." — or null. Never invent one. It is used to speak to the student in
    their own terms.

R6. `bbox` is `{x, y, w, h}` in pixels of the image as you received it, tight around the
    step's written line, padded by a few pixels. Approximate is fine; it is used to draw
    a highlight box, never to crop.

## Numbers

N1. Entries go in `rows` as JSON numbers. `[[6, -5], [2, 5]]`. Not strings, not LaTeX,
    no "\\frac", no "\\begin{pmatrix}".

N2. If any entry of an object is not a finite decimal — a fraction, a radical, a symbol,
    a repeating decimal — ALSO fill `exact` with the same shape, entries as plain
    sympy-parseable strings: "1/3", "-2/7", "sqrt(2)/2", "3*sqrt(5)", "lambda",
    "lambda - 2". Put the decimal value in `rows` as well. If every entry is a finite
    decimal, `exact` is null.

N3. `wrote_decimals` is true when the student's pen wrote a decimal point, false when
    they wrote an integer, fraction or radical. It describes their notation, not your
    encoding. 0.71 written by hand is true; 1/sqrt(2) encoded by you as rows 0.7071 is
    false.

N4. A vector written horizontally in parentheses, like (1, 2, 3), with no indication of
    row or column: `kind: "vector"`, `orientation: "unspecified"`, `rows` as a single
    row. Do not guess. Only use "row" or "column" when the page is explicit — bracket
    shape, a transpose mark, or the surrounding equation forces it.

N5. `shape` is what the student's brackets enclose. If their brackets and their entries
    disagree, report the brackets in `shape`, the entries in `rows`, and note it in
    `confidence_reason`.

## Ambiguity — this is the important part

Handwritten digits are genuinely ambiguous. 4 and 9 close the same way. 1 and 7 differ by
a stroke many people omit. A minus sign and a short fraction bar are the same mark. A
smudged 5 is a 6. Your job is to report the ambiguity, not to resolve it silently.

A1. Whenever a glyph could reasonably be read two ways, add an entry to `ambiguities`
    with what you read, what else it could be, the `kind`, and — for matrix entries —
    `entry: [row, col]` zero-indexed.

A2. If a different reading would produce a materially different object, also emit that
    whole alternative object in `alternates`. At most 2 alternates. Order them most
    plausible first. `value` stays your best reading.

A3. Emit an alternate only when you would genuinely not be surprised to be wrong. Do not
    pad the list. Three confident candidates are worse than one honest one, because the
    checker accepts a step if ANY candidate makes it correct — a fabricated alternate can
    hide a real mistake.

A4. Never resolve an ambiguity by checking which reading makes the arithmetic work. That
    is solving, and it is how a wrong answer gets laundered into a right one. Resolve by
    ink only: stroke shape, the student's other 4s and 9s elsewhere on the page, slant,
    pen pressure.

## Confidence

Per step, 0 to 1, and calibrated — a column of 0.9s is useless. Anchors:

  0.95-1.0  Every glyph unambiguous. You would bet the demo on it.
  0.80-0.94 Readable. One or two glyphs identified from stroke shape without hesitation.
  0.55-0.79 A glyph or two judged partly from context or from the student's other
            handwriting. There should be an `ambiguities` entry.
  0.30-0.54 Guessing at one or more entries. Emit alternates.
  < 0.30    Set `parse_ok: false`, put your best partial reading in `raw_text`, set
            `value` to null, and add an `extraction.unreadable_regions` entry naming the
            steps on either side in `between_steps`.

`confidence_reason` is one short clause when confidence is below 0.95 — "the 4 in the
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
    checked against these objects, so a misread given does not produce one wrong step —
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
````

### 3.1 The user turn

Image first, then text — images placed before text measurably outperform the reverse.
Multi-page work gets a short `Image N:` label before each image.

```
[ {"type": "text",  "text": "Image 1:"},
  {"type": "image", "source": {...}},
  {"type": "text",  "text": "Image 2:"},
  {"type": "image", "source": {...}},
  {"type": "text",  "text":
     "Transcribe this handwritten linear algebra work. Images are pages in order.\n"
     "Remember: copy what is written, including mistakes. Do not compute anything."} ]
```

For a single page, drop the `Image 1:` label and put the image first.

The closing reminder is deliberate repetition of the prime directive at the end of the
context, where it is closest to generation. It is worth the twenty tokens.

---

## 4. Worked example

### 4.1 The photo

A single sheet of college-ruled notebook paper, shot handheld under a desk lamp, about
3° off square, blue ballpoint. Top of the page, copied from the textbook in the student's
own hand:

> **Compute AB.**  A = [ 2  −1 ; 3  1 ]   B = [ 4  0 ; 2  5 ]

The `4` in B is written with a closed upper loop. It is a 4 — the student's other 4s on
the page close the same way — but it is one stroke from being a 9. This is exactly the
glyph that ruins demos.

Below, the work:

1. `1)` the student re-copies A and B side by side.
2. A first attempt at the product, two entries in, scratched out with three diagonal
   lines. Still legible underneath.
3. A margin column of dot products in smaller writing. The pen skipped on the second
   line and half of it is a dent in the paper rather than ink.
4. `2)` the answer, boxed:  `AB = [ 6  −5 ; 2  5 ]`

The correct product is `[[6, −5], [14, 5]]`. The bottom-left entry is `3·4 + 1·2 = 14`;
the student wrote `2`, having computed only the second term. The other three entries are
right.

### 4.2 Why this example is the one to build against

- **The error is real under every candidate reading.** If the ambiguous `4` were a `9`,
  the correct product would be `[[16, −5], [29, 5]]` — the student's `2` is still wrong.
  ERROR_TAXONOMY §4.7's "wrong only if all candidates are wrong" resolves to *flag it*,
  which is what we want on stage, and it resolves that way for a principled reason rather
  than by luck.
- **Only one basis vector moves.** Their matrix sends ĵ to (−5, 5), which is exactly
  where the correct one sends it. It sends î to (6, 2) instead of (6, 14). In
  `GridTransformCompare` the two panels agree completely on one arrow and diverge wildly
  on the other — and T1's t=6.2 beat, which `Indicate`s whichever basis arrow differs
  most, picks out î on its own. That is the single most legible thing this app can show,
  and the hint writes itself: *"watch where your first basis vector lands in step 2."*
  Location and a thing to watch, no correction.
- **It exercises four extraction paths in one photo**: a clean given, an ambiguous glyph
  on a given, a crossed-out abandoned step, and a partially unreadable scratch line.
- **Layer 2 of the taxonomy matches nothing.** "Dropped a term in one dot product" is not
  one of the 19 signatures. Layer 1 flags it anyway and routes to `GridTransformCompare`
  with a generic positional hint — which is ERROR_TAXONOMY §4.1's claim that coverage is
  not limited to the taxonomy, demonstrated end to end. Good thing to have working before
  you demo, because it is what happens on a stranger's homework.

### 4.3 The exact JSON that should come back

```json
{
  "document": {
    "page_count": 1,
    "legibility": "usable",
    "orientation_ok": true,
    "multiple_problems_detected": false,
    "notes": "Page is rotated ~3 degrees counter-clockwise. Margin column at right is scratch arithmetic serving step s4."
  },

  "problem": {
    "present": true,
    "statement": "Compute AB.",
    "topic": "matrix_multiply",
    "asks_for": "the product AB",
    "confidence": 0.86,
    "givens": [
      {
        "symbol": "A",
        "source": "printed",
        "confidence": 0.97,
        "ambiguities": [],
        "alternates": [],
        "object": {
          "kind": "matrix", "shape": [2, 2], "orientation": null,
          "rows": [[2, -1], [3, 1]],
          "exact": null, "scalars": null, "exact_scalars": null,
          "var": null, "text": null, "wrote_decimals": false
        }
      },
      {
        "symbol": "B",
        "source": "printed",
        "confidence": 0.72,
        "ambiguities": [
          {
            "where": "B, top-left entry",
            "entry": [0, 0],
            "read_as": "4",
            "could_be": ["9"],
            "kind": "digit_shape"
          }
        ],
        "alternates": [
          {
            "kind": "matrix", "shape": [2, 2], "orientation": null,
            "rows": [[9, 0], [2, 5]],
            "exact": null, "scalars": null, "exact_scalars": null,
            "var": null, "text": null, "wrote_decimals": false
          }
        ],
        "object": {
          "kind": "matrix", "shape": [2, 2], "orientation": null,
          "rows": [[4, 0], [2, 5]],
          "exact": null, "scalars": null, "exact_scalars": null,
          "var": null, "text": null, "wrote_decimals": false
        }
      }
    ]
  },

  "steps": [
    {
      "id": "s1",
      "student_label": "1)",
      "page": 1,
      "reading_order": 1,
      "bbox": {"x": 148, "y": 402, "w": 1180, "h": 190},
      "raw_text": "A = [2 -1 ; 3 1]   B = [4 0 ; 2 5]",
      "claimed_expression": "A, B",
      "claimed_operation": "copy_given",
      "op_args": {"rows": null, "scalar": null,
                  "source_symbols": ["A", "B"], "note": "re-copied from problem statement"},
      "value": {
        "kind": "matrix", "shape": [2, 2], "orientation": null,
        "rows": [[2, -1], [3, 1]],
        "exact": null, "scalars": null, "exact_scalars": null,
        "var": null, "text": null, "wrote_decimals": false
      },
      "alternates": [],
      "ambiguities": [
        {
          "where": "B as re-copied, top-left entry",
          "entry": [0, 0],
          "read_as": "4",
          "could_be": ["9"],
          "kind": "digit_shape"
        }
      ],
      "crossed_out": false,
      "is_final_answer": false,
      "parse_ok": true,
      "confidence": 0.74,
      "confidence_reason": "the top-left entry of B closes at the top and could be a 9"
    },

    {
      "id": "s2",
      "student_label": null,
      "page": 1,
      "reading_order": 2,
      "bbox": {"x": 160, "y": 636, "w": 520, "h": 170},
      "raw_text": "AB = [2 -1 ; ...]",
      "claimed_expression": "AB",
      "claimed_operation": "multiply",
      "op_args": {"rows": null, "scalar": null, "source_symbols": ["A", "B"],
                  "note": "abandoned after two entries, struck through with three diagonal lines"},
      "value": {
        "kind": "matrix", "shape": [2, 2], "orientation": null,
        "rows": [[2, -1], [0, 0]],
        "exact": null, "scalars": null, "exact_scalars": null,
        "var": null, "text": null, "wrote_decimals": false
      },
      "alternates": [],
      "ambiguities": [],
      "crossed_out": true,
      "is_final_answer": false,
      "parse_ok": false,
      "confidence": 0.40,
      "confidence_reason": "struck through and incomplete; only the first row was written, second row is empty and encoded as zeros"
    },

    {
      "id": "s3",
      "student_label": null,
      "page": 1,
      "reading_order": 3,
      "bbox": {"x": 1290, "y": 690, "w": 430, "h": 300},
      "raw_text": "(2)(4) + (-1)(2) = 6 / 3?4? + ... = ?",
      "claimed_expression": null,
      "claimed_operation": "dot",
      "op_args": {"rows": null, "scalar": null, "source_symbols": ["A", "B"],
                  "note": "margin scratch, dot products for the entries of AB"},
      "value": null,
      "alternates": [],
      "ambiguities": [],
      "crossed_out": false,
      "is_final_answer": false,
      "parse_ok": false,
      "confidence": 0.22,
      "confidence_reason": "pen skipped on the second line; most of it is an impression in the paper with no ink"
    },

    {
      "id": "s4",
      "student_label": "2)",
      "page": 1,
      "reading_order": 4,
      "bbox": {"x": 152, "y": 1046, "w": 640, "h": 210},
      "raw_text": "AB = [6  -5 ; 2  5]",
      "claimed_expression": "AB",
      "claimed_operation": "multiply",
      "op_args": {"rows": null, "scalar": null, "source_symbols": ["A", "B"], "note": null},
      "value": {
        "kind": "matrix", "shape": [2, 2], "orientation": null,
        "rows": [[6, -5], [2, 5]],
        "exact": null, "scalars": null, "exact_scalars": null,
        "var": null, "text": null, "wrote_decimals": false
      },
      "alternates": [],
      "ambiguities": [],
      "crossed_out": false,
      "is_final_answer": true,
      "parse_ok": true,
      "confidence": 0.96,
      "confidence_reason": null
    }
  ],

  "final_answer": {
    "step_id": "s4",
    "object": {
      "kind": "matrix", "shape": [2, 2], "orientation": null,
      "rows": [[6, -5], [2, 5]],
      "exact": null, "scalars": null, "exact_scalars": null,
      "var": null, "text": null, "wrote_decimals": false
    }
  },

  "extraction": {
    "unreadable_regions": [
      {
        "page": 1,
        "bbox": {"x": 1290, "y": 770, "w": 430, "h": 110},
        "why": "pen skipped; second scratch line is an impression in the paper with almost no ink",
        "between_steps": ["s2", "s4"]
      }
    ],
    "warnings": []
  }
}
```

### 4.4 What the verifier does with it, and what the student sees

`s1` copies the givens correctly → passes. `s2` is `crossed_out` → excluded from the
first-error search but kept for the load-bearing test. `s3` is `parse_ok: false` → §4.6
bridges the gap, because `s4` is reachable from `s1` and the unreadable region is not
load-bearing on its own. `s4` fails Layer 1: `A·B ≠ [[6,−5],[2,5]]` under the `4` reading
**and** under the `9` alternate, so §4.7 charity is exhausted and the step is genuinely
wrong.

Layer 2 matches no signature, so the fallback fires:

```json
{
  "first_error_index": 3,
  "confidence": "high",
  "error_id": null,
  "student_value": [[6, -5], [2, 5]],
  "correct_value": [[6, -5], [14, 5]],
  "scene_template": "GridTransformCompare",
  "scene_params": {
    "student_stages": [[[6, -5], [2, 5]]],
    "correct_stages": [[[6, -5], [14, 5]]],
    "student_display": [["6", "-5"], ["2", "5"]],
    "correct_display": [["6", "-5"], ["14", "5"]],
    "title": "Your step 2, applied to the plane",
    "student_label": "WHAT YOU WROTE",
    "correct_label": "WHAT THE STEP SHOULD DO",
    "hint": "watch the first basis vector",
    "ghost_reference": false,
    "track_vectors": [[1, 0], [0, 1]]
  },
  "positional_hint": "Watch where the first basis vector lands in your step 2.",
  "flags": ["load_bearing", "single_error"]
}
```

(Param names follow `SCENE_CATALOG.md` T1, which is the authority on scene payloads;
`ERROR_TAXONOMY.md` §1 lists an earlier, coarser shape.)

Both stage matrices clear T1's `abs(det) >= 0.05` guard — student 40, correct 100 — so
this routes to the animated template rather than falling back to `StaticStepHighlight`.
And the divergence-marking beat at t=6.2 does exactly the right thing unprompted: it
`Indicate`s the basis arrow that differs most, which here is î, which is the arrow the
hint names.

The animation shows two grids. The ĵ arrow lands on (−5, 5) in both panels — identical,
visibly so. The î arrow lands on (6, 14) on the right and (6, 2) on the left. Nobody has
to say the word "fourteen."

---

## 5. The API call

Everything in this section was read from the Claude API skill and the live vision docs on
2026-09-19, not recalled.

### 5.1 Model

**`claude-opus-5`.** Exact string, no date suffix — `claude-opus-5-20260401` and similar
are not real ids. Opus 5 is on the **high-resolution vision tier**: max long edge 2576 px,
max 4784 visual tokens per image, roughly 3× the fidelity of the standard 1568 px tier.
For dense pencil handwriting that resolution difference is the difference between reading
a 4 and guessing at it, so this is not an incidental choice.

Two properties of Opus 5 the code must respect:

- Thinking is **on by default**. Omitting `thinking` runs adaptive; `{"type":"adaptive"}`
  is equivalent and clearer. `budget_tokens` is gone and returns a 400.
- Safety classifiers can return `stop_reason: "refusal"` with HTTP 200. Handwritten
  linear algebra will not trip them, but **check `stop_reason` before reading `content`**
  or a stray refusal becomes an `IndexError` on stage.

If Opus 5 turns out to be slower than the demo tolerates, `claude-sonnet-5` is also on the
high-resolution tier and is the obvious latency lever — but measure first, and treat
transcription accuracy as the thing you are protecting.

### 5.2 Image preparation

Four things, in this order. Each one has bitten somebody.

**1. HEIC.** iPhones shoot HEIC by default and the API accepts only JPEG, PNG, GIF and
WebP. An AirDropped demo photo will be `.heic` and the request will fail with a media-type
error at the worst possible moment. Install `pillow-heif` and register it at import:

```python
from pillow_heif import register_heif_opener
register_heif_opener()
```

**2. EXIF rotation.** Phone photos carry orientation in EXIF, not in the pixels. Claude
does not read image metadata at all, so an un-transposed photo arrives sideways and
transcription quality collapses. `ImageOps.exif_transpose(img)` — one line, non-optional.

**3. Resize so the server does not.** Bounding boxes come back in pixels of the image
**as Claude saw it, after any server-side downscaling**. If we send an oversized image the
server resizes it, and every bbox is then wrong relative to the photo the frontend
displays. Pre-resize to satisfy *both* limits so no server-side resize happens, and serve
that exact resized file to the frontend:

```python
import math
from PIL import Image, ImageOps

MAX_EDGE, MAX_VISUAL_TOKENS, PATCH = 2576, 4784, 28   # Opus 5, high-resolution tier

def visual_tokens(w: int, h: int) -> int:
    return math.ceil(w / PATCH) * math.ceil(h / PATCH)

def fit_for_model(img: Image.Image) -> Image.Image:
    """Largest size that trips neither the long-edge nor the visual-token limit."""
    w, h = img.size
    scale = min(1.0, MAX_EDGE / max(w, h))          # never upscale
    while True:
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        if visual_tokens(nw, nh) <= MAX_VISUAL_TOKENS:
            return img.resize((nw, nh), Image.LANCZOS)
        scale *= 0.97

def prepare(path: str) -> tuple[bytes, str, tuple[int, int]]:
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img = fit_for_model(img)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92, optimize=True)   # NOT 60 — see below
    return buf.getvalue(), "image/jpeg", img.size
```

A 3024×4032 phone photo lands at **1659×2212, 4740 visual tokens ≈ $0.024** on Opus 5.
Cost is irrelevant; fidelity is not.

**4. Do not over-compress.** JPEG quality 92, not 60. Compression artifacts attack
exactly the thin low-contrast strokes that distinguish a 4 from a 9. Saving 200 KB on a
localhost demo is worth nothing; losing a digit costs everything.

**One more, free:** tell the user in the capture UI to fill the frame with the page. Half
a photo of desk means half the resolution spent on desk. This is the cheapest accuracy
win available and it costs one line of placeholder text.

Hard limits worth knowing: 10 MB per image base64 on the Claude API, 8000×8000 px max
dimensions, 32 MB per request, up to 600 images per request (100 on 200K-context models).
None of these bind after the resize above.

### 5.3 The call

Base64 is plain standard base64 of the file bytes, decoded to `str`, **no newlines**:

```python
import base64, io, math
import anthropic
from .extraction_models import Extraction
from .prompts import EXTRACTION_SYSTEM

client = anthropic.Anthropic()          # picks up ANTHROPIC_API_KEY or an `ant auth login` profile

def extract(image_paths: list[str]) -> Extraction:
    content = []
    multi = len(image_paths) > 1
    for i, path in enumerate(image_paths, start=1):
        data, media_type, _size = prepare(path)
        if multi:
            content.append({"type": "text", "text": f"Image {i}:"})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(data).decode("utf-8"),
            },
        })
    content.append({"type": "text", "text":
        "Transcribe this handwritten linear algebra work. "
        + ("Images are pages in order. " if multi else "")
        + "Remember: copy what is written, including mistakes. Do not compute anything."})

    resp = client.with_options(timeout=90.0).messages.parse(
        model="claude-opus-5",
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=[{
            "type": "text",
            "text": EXTRACTION_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": content}],
        output_format=Extraction,          # Pydantic model from §2.4
    )

    if resp.stop_reason == "refusal":
        raise ExtractionRefused(resp.stop_details)
    if resp.stop_reason == "max_tokens":
        raise ExtractionTruncated()        # raise max_tokens and retry

    return resp.parsed_output              # a validated Extraction
```

**Images before text.** Claude works best with the image first; text-then-image still
works but is measurably weaker. The structure above puts the label before each image only
in the multi-page case, which is what the docs recommend for referring to pages later.

If `messages.parse()` gives trouble, the equivalent without the helper is
`client.messages.create(..., output_config={"format": {"type": "json_schema", "schema":
<the §2.2 schema>}})`, then `json.loads` the first text block and
`Extraction.model_validate(...)` it yourself. `output_config.format` guarantees the first
content block is text containing schema-valid JSON. Use the deprecated top-level
`output_format=` parameter on `create()` for nothing; on `parse()` it is the correct
Pydantic argument.

### 5.4 Structured outputs, not tool use

**Use `output_config.format` / `messages.parse()`. Do not use a tool with
`tool_choice: {"type": "tool"}` to force JSON.** The tool-use trick is a workaround from
before structured outputs existed, and it has since become actively fragile: forced
`tool_choice` values `any` and `tool` return a 400 on the newest models. There is no
upside here — nothing is being executed, we just want a typed object back — and
`messages.parse()` hands us a validated Pydantic instance with no parsing code of our own.

One consequence of a strict schema deserves a design response rather than a workaround:
**a required field must be filled, so a model that cannot read an entry is structurally
pressured to invent one.** That is why every uncertain field in §2.2 is nullable and why
`parse_ok`, `unreadable_regions` and null `value` exist. Refusing to guess has to be
representable *inside* the schema, or the schema will manufacture confident garbage. This
is the single most important thing to get right about combining strict outputs with OCR.

### 5.5 Caching and latency

The system prompt is ~2000 tokens and byte-identical on every request, so mark it
`cache_control: {"type": "ephemeral"}` (Opus 5's cache minimum is 512 tokens, so it
qualifies). It pays for itself on the §6.3 retry call and on every repeat of the demo.
Confirm it is working with `resp.usage.cache_read_input_tokens` — if that is 0 across
repeated runs, something in the prefix is varying.

Effort: leave `output_config.effort` at its default (`high`) for the hero path.
Transcription accuracy is the whole product and this is not a task to economize on. If
measured latency hurts, `"medium"` is the lever — pull it after measuring, not before.

Expect roughly 10-25 s for one page. That is dwarfed by Manim rendering, which is why the
confirm screen in §7 starts the render speculatively rather than waiting for a click.

### 5.6 Optional hardening

The Claude API skill recommends enabling server-side refusal fallbacks by default on
Opus 5 (`betas: ["server-side-fallback-2026-07-01"]`, `fallbacks: "default"`). Those live
on `client.beta.messages.*`; whether the `parse()` helper is available on the beta
namespace has not been verified here, so if you want fallbacks, use the
`beta.messages.create` + explicit-schema form from §5.3 and validate with Pydantic
yourself. The `stop_reason == "refusal"` guard is the part that is genuinely
non-optional; the fallback is belt-and-braces for a path that should never fire on
homework photos.

---

## 6. Failure handling

### 6.1 The failure that kills the product: silent correction

Everything else in this section is recoverable. This one is not, because it fails
*successfully* — a clean extraction, a confident confidence score, and a student whose
mistake has been quietly erased before anyone looked for it. The app then either finds no
error (and has nothing to show) or finds a later, downstream one (and points at the wrong
line).

Prompting handles most of it (§3, the opening block and the `raw_text` rule). The
remaining risk is caught for free by the redundancy already in the schema:

```python
import re
NUM = re.compile(r'-?\d+(?:\.\d+)?')

def silent_correction_suspected(step) -> bool:
    """value contains a number the pen never wrote -> the model computed something."""
    if not step.parse_ok or step.value is None:
        return False
    if step.value.kind not in ("matrix", "vector", "vector_list", "augmented"):
        return False
    if "[" not in step.raw_text:          # value wasn't literally written on this line
        return False
    written = {abs(float(x)) for x in NUM.findall(step.raw_text)}
    claimed = {abs(v) for row in (step.value.rows or []) for v in row}
    return bool(claimed - written)
```

The guard is deliberately narrow — it runs only on steps where the student wrote a
bracketed object on the line, so a row-operation label like `R2 -> R2 - 2R1` never trips
it. When it fires: drop that step's confidence to 0.3, mark it for review in the confirm
screen, and log it. Do not try to auto-repair; the student is about to look at it anyway.

If this guard fires more than occasionally during testing, the prompt is losing and the
fix is prompt-side, not code-side.

### 6.2 Everything else

| Failure | Detected by | Extraction does | App does |
|---|---|---|---|
| Photo blank, too dark, or not mathematics | `legibility: "unreadable"`, `steps: []` | one plain sentence in `warnings` saying what is wrong | Retake screen quoting that sentence verbatim, plus the "type it instead" path |
| Ambiguous digit (4/9, 1/7, 5/6) | `ambiguities` + `alternates` | best reading in `value`, rivals in `alternates`, confidence 0.55–0.79 | Confirm screen shows a one-tap swap chip; verifier tries all candidates (§4.7) |
| Ambiguous minus vs fraction bar | `ambiguities` with `kind: "sign"` | both readings as alternates | same; sign errors are the highest-value thing to get right, since half the taxonomy is sign errors |
| One step unreadable, neighbours fine | `parse_ok: false`, `unreadable_regions.between_steps` | `value: null` | §4.6 bridge or bracket; **render from the next parseable step regardless** — the animation needs their claimed object, never a parse of their reasoning |
| Several consecutive steps unreadable | same, one region spanning them | `value: null` on each | One §6.3 retry on the region; then bracket the error to the region and hint at region level |
| Only the final answer readable | every intermediate `parse_ok: false`, `final_answer.object` non-null | fill `final_answer` | §4.6 final-answer fallback: animate their answer against the correct one with a generic hint. **Wire this path first** — it is what guarantees the demo always produces a video |
| No problem statement on the page | `problem.present: false` | infer `asks_for`, mark givens `"inferred"` | One text field: "What was the problem?" Pre-filled with the inference |
| Givens misread | `givens[].confidence` low, `alternates` non-empty | alternates on the given | Confirm screen puts givens **first and largest** — a wrong given poisons every check (§4.2) |
| Two problems on one page | `multiple_problems_detected: true` | extract the one with the most work | Chip row: "I focused on problem 2 — switch?" |
| Photo rotated 90°/180° | `orientation_ok: false` | transcribe anyway if possible | Rotate server-side and re-extract once; EXIF handling in §5.2 prevents most of this |
| Model returns `stop_reason: "refusal"` | `resp.stop_reason` | — | Generic "something went wrong, try again or type it" — never surface a classifier category to a student |
| Response truncated | `stop_reason: "max_tokens"` | — | Retry once at `max_tokens=32000` |
| Model invents a matrix | §6.1 guard | — | Confidence floor + flag for review |

### 6.3 The one retry

Per ERROR_TAXONOMY §4.6.4: **one** re-ask per unreadable step, **two** per image. The
retry is a second call with the region cropped out of the *original* full-resolution
photo — not the resized one — with generous padding (≈25% of the region's dimensions on
each side, so the model keeps context) and then run through the same `prepare()`. A crop
of a page spends the whole 4784-token budget on a few lines instead of the whole sheet,
which is a genuine several-fold increase in effective resolution on that region and is
why the retry is worth making at all.

The retry uses the same system prompt (so the cache hits) with a different closing text
block:

```
"This is a crop of one line from the page you just read. Transcribe only this line,
 using the same schema, as a single step. Copy what is written, including mistakes."
```

Cap it. Two retries per image, hard. Every retry is 10-25 s the render does not get.

### 6.4 The rule underneath all of it

**A null is a fact. An invented matrix is a lie that survives to the animation.** Every
unreadable path above ends in an honest null plus a UI affordance, never in a plausible
guess. The app is allowed to say "I couldn't read this." It is not allowed to show a
student an animation of a matrix they never wrote.

---

## 7. The confirm screen

### 7.1 Why it is a feature

Pitch it as the product working, not as the OCR apologizing: *"Here's your work as I read
it — fix anything I got wrong."* Three true things make that framing honest rather than
spin:

1. **It is what a good tutor does.** "So you've got six, minus five, two, five — is that
   right?" is the first thing a human says before critiquing someone's algebra. Reading
   the work back is a pedagogical move, not an error dialog.
2. **It is where the student re-reads their own work.** Several students will spot their
   own mistake on this screen, before any animation runs. That is the product's actual
   goal achieved for free, and it is a good line to have ready for the judges.
3. **It makes the demo un-killable.** On stage the OCR either works, in which case the
   screen is a two-second beat, or it stumbles, in which case fixing one digit is a
   deliberate-looking interaction rather than a crash. A demo whose worst case is "the
   presenter taps a chip" has no worst case.

Never show the word "confidence", never show a number, never apologize. Uncertainty is
communicated as a dotted underline and a tappable alternative, nothing more.

### 7.2 Layout

Two panes, photo on the left, structured read on the right, aligned by `bbox`.

```
┌───────────────────────────┬────────────────────────────────────┐
│                           │  THE PROBLEM                       │
│   the student's photo,    │  Compute AB                        │
│   with a highlight box    │      ⎡ 2  -1 ⎤      ⎡ 4̲  0 ⎤       │
│   on the hovered step     │  A = ⎣ 3   1 ⎦  B = ⎣ 2   5 ⎦      │
│                           │                   ↑ 4 or 9?        │
│   (this is the EXACT      │                                    │
│    resized image sent     │  YOUR WORK                         │
│    to the model, so the   │  1)  copied A and B          ✓     │
│    boxes line up — §5.2)  │  ⌀   crossed out                   │
│                           │  —   couldn't read this line  [?]  │
│                           │  2)  AB = ⎡ 6  -5 ⎤                │
│                           │          ⎣ 2   5 ⎦                 │
│                           │                                    │
│                           │     [ Looks right — show me ▸ ]    │
│                           │     type it instead                │
└───────────────────────────┴────────────────────────────────────┘
```

### 7.3 Interaction rules

- **Givens first, biggest.** They are rendered above the work and in a larger cell grid,
  because §4.2 checks everything against them. A wrong given is the one error that makes
  the whole app wrong at once.
- **Tap-to-swap, don't type.** An `ambiguities` entry renders as a dotted underline on
  that entry; tapping it shows the `could_be` values as chips. One tap swaps it. Typing is
  the fallback, not the primary path — on a phone, at a demo booth, typing a matrix is a
  disaster and tapping "9" is instant.
- **Edit in a grid, never in a text box.** Matrices are `<input>` cells in a CSS grid, one
  per entry. Nobody should ever be asked to retype `[[6,-5],[2,5]]`.
- **Autofocus the lowest-confidence editable entry** so the thing most likely to be wrong
  already has the cursor in it. Never sort the list by confidence — reading order must
  match the photo or the two panes stop corresponding.
- **Unreadable steps show as a dimmed row with a `[?]`**, not as a gap. A gap looks like
  the app missed a line. A visible "couldn't read this" row is honest and, since §4.6
  bridges or brackets around it, usually costs the student nothing.
- **Crossed-out steps render collapsed and greyed**, behind a "show scratch work" toggle.
  They are in the data (they matter for the load-bearing test), but they are visual noise.
- **The continue button is never disabled.** Not on low confidence, not on unreadable
  steps, not on a missing problem statement. There is always a path forward, even if that
  path is the final-answer fallback.

### 7.4 Start rendering before they click

The Manim render is the long pole (see `RENDERING.md`). The confirm screen is dead time —
10 to 20 seconds of a human reading. Use it:

1. Extraction returns → show the confirm screen **and** immediately fire verify + render
   on the unedited extraction, keyed by a hash of it.
2. Student clicks **Looks right** with no edits (the common case) → the video is already
   rendered or nearly so. It appears instantly. This is what makes the app feel fast on
   stage.
3. Student edits something → hash changes, cancel the in-flight job, re-run. They paid for
   the delay with their own edit, which feels causal rather than slow.

Key by the hash of the *extraction*, not of the image, so an edit that does not change the
math (a typo in `statement`) does not throw away a good render.

### 7.5 Demo insurance

Because the student confirms the extraction anyway, a pre-computed extraction for the
rehearsed demo photo is indistinguishable from a live one — same screen, same
interactions, same edits possible. Ship `samples/` with one known-good extraction JSON
per sample photo, and have the endpoint fall back to it on API error or timeout for those
specific images. This is not cheating the demo: the student still confirms, still edits,
and the verification and animation downstream are fully live. It only removes one network
call from the critical path of a presentation you cannot re-run.

---

## 8. Build order

Fourteen hours. In this order, and stop when the clock says so:

1. **`prepare()` + one hardcoded call + print the JSON.** (§5.2, §5.3) Until you have seen
   a real extraction of a real photo, every other decision here is theory. 45 minutes.
2. **The Pydantic models** (§2.4) and `to_sympy(MathObject)`. The `exact`-over-`rows`
   precedence rule is four lines; get it right once.
3. **The final-answer fallback path end to end** — photo → `final_answer` → verify →
   `GridTransformCompare` → video. This is the spine. Once it works, the app always
   produces something, and everything after it is improvement rather than risk.
4. **The confirm screen, read-only.** Photo, boxes, steps listed. No editing yet.
5. **Per-step verification** (ERROR_TAXONOMY §4) replacing the final-answer shortcut.
6. **Tap-to-swap on `ambiguities`.** The single highest-value interaction in the app, and
   about 30 lines.
7. **Grid editing** of givens and of the flagged step.
8. **Speculative render** (§7.4).
9. **The §6.3 retry.** Genuinely optional. Cut it without regret.

Things that look like work and are not: a LaTeX renderer for `raw_text` (use a monospace
grid), multi-page support (the demo is one page), a second cheaper model for triage (one
call costs two cents).
