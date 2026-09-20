/* lib.js — pure logic, no DOM.
 *
 * Lives on its own so it can be unit-tested under node (see the bottom of the
 * file) and so the tricky part of this frontend — turning an edited read-back
 * screen back into a payload the verifier accepts — is readable in one place.
 *
 * THE ROUND-TRIP PROBLEM
 * ----------------------
 * /api/analyze answers with a *view* of the extraction (backend/app.py
 * _steps_view / _obj_view), not the extraction itself. The view is lossy:
 *   - obj.exact is collapsed into `display`, and `display` is fmt_num output,
 *     which rounds to 2 decimals. Sending `display` back as `exact` would turn
 *     0.7071 into 0.71 and can flip a verdict.
 *   - step.op_args, step.confidence and extraction.final_answer are absent.
 * So the rules here are:
 *   1. Prefer `rows` (full-precision floats). _sym() nsimplifies a float back
 *      to a rational, so 0.4 -> 2/5 survives; a 2-dp string would not.
 *   2. Only reach for `exact` strings when there is no numeric source, or when
 *      the student typed something that is not a plain number.
 *   3. Rebuild final_answer from the step carrying is_final_answer, which the
 *      view does keep. That restores _load_bearing and the final-answer
 *      fallback in verify.py.
 *   4. If the backend ever includes the raw extraction on the job payload
 *      (job.extraction), patch THAT instead and none of the above applies.
 *      buildExtraction feature-detects it.
 */
(function (root, factory) {
  const lib = factory();
  if (typeof module === 'object' && module.exports) module.exports = lib;
  else root.LIB = lib;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const GRID_KINDS = new Set(['matrix', 'vector', 'augmented', 'vector_list']);
  const LIST_KINDS = new Set(['scalar_list', 'polynomial']);

  /** Lossless float -> string. Mirrors fmt_num's *shape* (int, then small
   *  rational) but falls back to full precision instead of 2 decimals, because
   *  this feeds the verifier rather than the screen. */
  function fmtExact(x) {
    if (x === null || x === undefined || !isFinite(x)) return '0';
    if (Number.isInteger(x)) return String(x);
    for (let q = 2; q <= 20; q++) {
      const p = x * q;
      if (Math.abs(p - Math.round(p)) < 1e-9) return `${Math.round(p)}/${q}`;
    }
    return String(x); // JS prints the shortest round-tripping repr
  }

  /** Is this cell a plain number we can put in `rows`?
   *  Fractions count: 2/5 -> 0.4 -> nsimplify -> 2/5 again, domain intact. */
  function parseCell(raw) {
    const text = String(raw == null ? '' : raw).trim();
    if (!text) return { ok: false, empty: true, value: null, text };
    const plain = /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/;
    if (plain.test(text)) return { ok: true, empty: false, value: Number(text), text };
    const frac = /^([-+]?\d+)\s*\/\s*(-?\d+)$/.exec(text);
    if (frac) {
      const d = Number(frac[2]);
      if (d !== 0) return { ok: true, empty: false, value: Number(frac[1]) / d, text };
    }
    return { ok: false, empty: false, value: null, text }; // symbolic: sqrt(2), lambda...
  }

  /** The strings to *show* for an object. Uses the backend's own fmt_num
   *  output so the screen and the animation agree glyph for glyph. */
  function cellGrid(view) {
    if (!view) return null;
    if (GRID_KINDS.has(view.kind)) {
      if (view.display) return view.display;
      if (view.rows) return view.rows.map((r) => r.map(fmtExact));
      return null;
    }
    if (LIST_KINDS.has(view.kind) || view.kind === 'scalar') {
      if (view.scalars) return [view.scalars.slice()];
      if (view.rows) return view.rows.map((r) => r.map(fmtExact));
      return null;
    }
    return null;
  }

  const gridHasSymbolic = (grid) =>
    !!grid && grid.some((row) => row.some((s) => !parseCell(s).ok));

  /** Apply {"i,j" -> typed string} onto a numeric grid and/or a string grid.
   *  Returns the {rows, exact} pair to put on the MathObject.
   *
   *  `exact` is kept only when it carries something the floats cannot — a
   *  symbolic entry like 4*sqrt(5), or no numeric source at all. Otherwise it
   *  is dropped, because `display` is fmt_num output (2 decimals) while `rows`
   *  is full precision, and _sym() nsimplifies a float back to its rational. */
  function applyGridEdits(rows, exactStrings, edits) {
    let R = rows ? rows.map((r) => r.slice()) : null;
    let E = exactStrings ? exactStrings.map((r) => r.slice()) : null;
    const entries = edits ? Array.from(edits instanceof Map ? edits.entries() : Object.entries(edits)) : [];

    // A symbolic edit needs a string grid to live in; materialise one losslessly.
    if (!E && R && entries.some(([, t]) => !parseCell(t).ok)) E = R.map((r) => r.map(fmtExact));

    for (const [key, text] of entries) {
      const [i, j] = key.split(',').map(Number);
      const p = parseCell(text);
      if (E && E[i] && j < E[i].length) E[i][j] = p.text;
      if (R && R[i] && j < R[i].length && p.ok) R[i][j] = p.value;
    }

    return { rows: R, exact: (!R || gridHasSymbolic(E)) ? E : null };
  }

  /** view (from _obj_view) + cell edits -> MathObject for /api/analyze. */
  function objFromView(view, edits) {
    if (!view) return null;
    const out = {
      kind: view.kind,
      shape: view.shape || null,
      orientation: view.orientation || null,
      var: view.var || null,
      text: view.text || null,
      wrote_decimals: false,
    };
    const has = edits && (edits instanceof Map ? edits.size : Object.keys(edits).length);

    if (GRID_KINDS.has(view.kind)) {
      const { rows, exact } = applyGridEdits(view.rows || null, view.display || null, edits);
      out.rows = rows;
      out.exact = exact;
      return out;
    }
    if (LIST_KINDS.has(view.kind) || view.kind === 'scalar') {
      const src = view.scalars ? [view.scalars.slice()] : null;
      const { exact } = applyGridEdits(null, src, edits);
      out.scalars = null;
      out.exact_scalars = exact ? exact[0] : null;
      return out;
    }
    if (view.kind === 'text') {
      const first = has ? Array.from(edits instanceof Map ? edits.values() : Object.values(edits))[0] : null;
      out.text = first != null ? String(first) : (view.text || '');
      return out;
    }
    out.rows = view.rows || null;
    return out;
  }

  const editsFor = (edits, key) => (edits && edits[key] && edits[key].cells) || null;

  function rebuildStep(view, stepEdit) {
    const edited = !!(stepEdit && ((stepEdit.cells && Object.keys(stepEdit.cells).length) || stepEdit.raw_text != null));
    return {
      id: view.id,
      student_label: view.label || null,
      page: view.page == null ? 1 : view.page,
      reading_order: view.reading_order == null ? 0 : view.reading_order,
      bbox: view.bbox || null,
      raw_text: stepEdit && stepEdit.raw_text != null ? stepEdit.raw_text : (view.raw_text || ''),
      claimed_expression: view.claimed_expression || null,
      claimed_operation: view.claimed_operation || 'unknown',
      value: objFromView(view.value, stepEdit && stepEdit.cells),
      // A human just told us what the page says, so the camera's other guesses
      // are noise — but keep them when the step was left alone (charitable
      // reading, ERROR_TAXONOMY "a step is wrong only if ALL candidates are").
      alternates: edited ? [] : (view.alternates || []).filter(Boolean).map((a) => objFromView(a, null)),
      ambiguities: edited ? [] : (view.ambiguities || []),
      crossed_out: !!view.crossed_out,
      is_final_answer: !!view.is_final_answer,
      parse_ok: edited ? true : view.parse_ok !== false,
      confidence: edited ? 0.99 : (view.needs_review ? 0.5 : 0.9),
    };
  }

  /** The whole payload. Prefers the raw extraction when the backend sends one. */
  function buildExtraction(job, edits) {
    edits = edits || {};
    if (job && job.extraction && Array.isArray(job.extraction.steps)) {
      return patchRawExtraction(job.extraction, edits);
    }
    const problem = job.problem || {};
    const steps = (job.steps || []).map((s) => rebuildStep(s, edits[s.id]));
    const finalStep = steps.filter((s) => s.is_final_answer).pop() || null;

    return {
      document: job.document || {},
      problem: {
        present: problem.present !== false,
        statement: problem.statement || null,
        topic: problem.topic || 'other',
        asks_for: problem.asks_for || null,
        givens: (problem.givens || []).map((g) => ({
          symbol: g.symbol,
          object: objFromView(g.object, editsFor(edits, 'given:' + g.symbol)),
          source: g.source || 'printed',
          ambiguities: g.ambiguities || [],
          alternates: (g.alternates || []).filter(Boolean).map((a) => objFromView(a, null)),
          confidence: g.needs_review ? 0.6 : 0.95,
        })),
      },
      steps,
      // The view drops extraction.final_answer, but is_final_answer survives on
      // the step, so rebuild it: verify.py's _load_bearing and its final-answer
      // fallback both read this.
      final_answer: finalStep ? { step_id: finalStep.id, object: finalStep.value } : { step_id: null, object: null },
      extraction: { unreadable_regions: [], warnings: [] },
    };
  }

  function patchRawExtraction(raw, edits) {
    const ext = JSON.parse(JSON.stringify(raw));
    for (const step of ext.steps || []) {
      const e = edits[step.id];
      if (!e) continue;
      if (e.raw_text != null) step.raw_text = e.raw_text;
      if (e.cells && Object.keys(e.cells).length && step.value) {
        const v = step.value;
        if (GRID_KINDS.has(v.kind)) {
          const { rows, exact } = applyGridEdits(v.rows || null, v.exact || null, e.cells);
          v.rows = rows;
          v.exact = exact;
        } else if (LIST_KINDS.has(v.kind) || v.kind === 'scalar') {
          const src = v.exact_scalars ? [v.exact_scalars.slice()]
            : (v.scalars ? [v.scalars.map(fmtExact)] : null);
          const { exact } = applyGridEdits(null, src, e.cells);
          if (exact) { v.exact_scalars = exact[0]; v.scalars = null; }
        }
        step.alternates = [];
        step.ambiguities = [];
        step.confidence = 0.99;
        step.parse_ok = true;
        if (ext.final_answer && ext.final_answer.step_id === step.id) {
          ext.final_answer.object = step.value;
        }
      }
    }
    for (const g of (ext.problem && ext.problem.givens) || []) {
      const e = edits['given:' + g.symbol];
      if (!e || !e.cells || !g.object) continue;
      const { rows, exact } = applyGridEdits(g.object.rows || null, g.object.exact || null, e.cells);
      g.object.rows = rows;
      g.object.exact = exact;
      g.confidence = 0.99;
      g.alternates = [];
    }
    return ext;
  }

  function countEdits(edits) {
    let n = 0;
    for (const k of Object.keys(edits || {})) {
      const e = edits[k];
      if (e.raw_text != null) n++;
      n += e.cells ? Object.keys(e.cells).length : 0;
    }
    return n;
  }

  /** Every cell the student typed has to be something sympy can read. */
  function invalidCells(edits) {
    const bad = [];
    for (const key of Object.keys(edits || {})) {
      const cells = (edits[key] || {}).cells || {};
      for (const cell of Object.keys(cells)) {
        const p = parseCell(cells[cell]);
        if (p.empty) bad.push({ key, cell, why: 'empty' });
      }
    }
    return bad;
  }

  return {
    GRID_KINDS, LIST_KINDS,
    fmtExact, parseCell, cellGrid, applyGridEdits, gridHasSymbolic, objFromView,
    rebuildStep, buildExtraction, patchRawExtraction, countEdits, invalidCells,
  };
});
