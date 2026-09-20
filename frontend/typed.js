/* Noema — typed working -> the §2.4 extraction schema.
 *
 * /api/analyze already accepts a JSON body carrying `steps`, which skips the
 * vision model entirely and goes straight to verify -> locate -> hint ->
 * render. So typed work does not need a backend change: it needs someone to
 * produce that payload. That is all this file does.
 *
 * It is deliberately STRICT. A parser that guesses would hand the verifier a
 * confident wrong reading of work the student never wrote, and the whole
 * product rests on only ever blaming a step that is genuinely wrong. So a line
 * it does not fully understand is returned as parse_ok:false with no `value`,
 * which the backend already treats charitably (unparseable is not wrong), and
 * the UI shows the reading back before anything is analysed.
 *
 * Grammar, one step per line:
 *
 *   A = [1 2; 3 4]        a given, or any named object
 *   AB = [...]            product, in the order written
 *   A*B = [...]           the same
 *   A + B = [...]         sum
 *   det(A) = -2           determinant
 *   A^-1 = [...]          inverse ( inv(A) also works )
 *   u . v = 11            dot product ( dot(u,v) also works )
 *   [1 2; 3 4]            a bare value, operation unknown
 *
 * Entries may be integers, decimals or fractions (3/4). Rows are separated by
 * ';' and entries by spaces or commas. A line with no '=' and no bracket is
 * taken as the problem statement.
 */
(function (global) {
  'use strict';

  var MATRIX_RE = /^[\[\(]([^\[\]\(\)]*)[\]\)]$/;

  function num(tok) {
    tok = String(tok).trim();
    if (!tok) return null;
    var frac = tok.match(/^(-?\d+(?:\.\d+)?)\s*\/\s*(-?\d+(?:\.\d+)?)$/);
    if (frac) {
      var d = parseFloat(frac[2]);
      if (!d) return null;
      return parseFloat(frac[1]) / d;
    }
    if (!/^-?\d+(\.\d+)?$/.test(tok)) return null;
    return parseFloat(tok);
  }

  // "[0 -1 ; 1 0]" -> {kind, shape, rows, ...}, or null if it is not one.
  function parseValue(text) {
    text = String(text).trim();

    var m = text.match(MATRIX_RE);
    if (m) {
      var body = m[1].trim();
      if (!body) return null;
      var rowTexts = body.split(';');
      var rows = [];
      var exact = [];
      var sawDecimal = false;
      var sawExact = false;

      for (var i = 0; i < rowTexts.length; i++) {
        var toks = rowTexts[i].trim().split(/[\s,]+/).filter(Boolean);
        if (!toks.length) return null;
        var row = [];
        var erow = [];
        for (var j = 0; j < toks.length; j++) {
          var v = num(toks[j]);
          if (v === null) return null;           // one bad entry fails the line
          if (/\./.test(toks[j])) sawDecimal = true;
          if (/\//.test(toks[j])) sawExact = true;
          row.push(v);
          erow.push(toks[j]);
        }
        rows.push(row);
        exact.push(erow);
      }

      var width = rows[0].length;
      for (var k = 1; k < rows.length; k++) if (rows[k].length !== width) return null;

      // A single row in brackets, with nothing saying row or column: N4 says
      // report it as unspecified rather than guessing.
      if (rows.length === 1 && width > 1) {
        return {
          kind: 'vector', shape: [1, width], orientation: 'unspecified',
          rows: rows, exact: sawExact ? exact : null, wrote_decimals: sawDecimal,
        };
      }
      if (rows.length > 1 && width === 1) {
        return {
          kind: 'vector', shape: [rows.length, 1], orientation: 'unspecified',
          rows: rows, exact: sawExact ? exact : null, wrote_decimals: sawDecimal,
        };
      }
      return {
        kind: 'matrix', shape: [rows.length, width], orientation: null,
        rows: rows, exact: sawExact ? exact : null, wrote_decimals: sawDecimal,
      };
    }

    var s = num(text);
    if (s !== null) {
      return {
        kind: 'scalar', scalars: [s],
        exact_scalars: /\//.test(text) ? [text.trim()] : null,
        wrote_decimals: /\./.test(text),
      };
    }
    return null;
  }

  // The left-hand side decides the operation and which givens it draws on.
  function parseLhs(lhs) {
    lhs = lhs.trim();
    var m;

    if ((m = lhs.match(/^det\s*[\(\|]\s*([A-Za-z]\w*)\s*[\)\|]$/i)))
      return { op: 'det', syms: [m[1]], expr: 'det(' + m[1] + ')' };

    if ((m = lhs.match(/^(?:inv\s*\(\s*([A-Za-z]\w*)\s*\)|([A-Za-z]\w*)\s*\^?\s*-\s*1)$/i)))
      return { op: 'inverse', syms: [m[1] || m[2]], expr: (m[1] || m[2]) + '^-1' };

    if ((m = lhs.match(/^dot\s*\(\s*([A-Za-z]\w*)\s*,\s*([A-Za-z]\w*)\s*\)$/i)))
      return { op: 'dot', syms: [m[1], m[2]], expr: m[1] + '.' + m[2] };

    if ((m = lhs.match(/^([A-Za-z]\w*)\s*[.·]\s*([A-Za-z]\w*)$/)))
      return { op: 'dot', syms: [m[1], m[2]], expr: m[1] + '.' + m[2] };

    if ((m = lhs.match(/^([A-Za-z]\w*)\s*\+\s*([A-Za-z]\w*)$/)))
      return { op: 'add', syms: [m[1], m[2]], expr: m[1] + '+' + m[2] };

    if ((m = lhs.match(/^([A-Za-z]\w*)\s*[*x×]\s*([A-Za-z]\w*)$/i)))
      return { op: 'multiply', syms: [m[1], m[2]], expr: m[1] + m[2] };

    // Juxtaposition: AB, ABC. Only single capitals, so "det" and friends above
    // have already had their chance and a word like "Area" is not split up.
    if ((m = lhs.match(/^([A-Z])([A-Z])([A-Z])?$/)))
      return {
        op: 'multiply',
        syms: [m[1], m[2]].concat(m[3] ? [m[3]] : []),
        expr: lhs,
      };

    if (/^[A-Za-z]\w*$/.test(lhs))
      return { op: 'copy_given', syms: [lhs], expr: lhs };

    return null;
  }

  /* parse(text) -> {ok, problem, givens, steps, notes[]} */
  // The last bracketed matrix or parenthesised tuple on a line, allowing a
  // full stop after it.
  var TAIL_VALUE_RE = /(\[[^\]]*\]|\((?:\s*-?\d+(?:\.\d+)?(?:\s*\/\s*-?\d+)?\s*,)+\s*-?\d+(?:\.\d+)?(?:\s*\/\s*-?\d+)?\s*\))\s*\.?\s*$/;

  function parse(text) {
    var lines = String(text || '').split(/\n+/).map(function (l) { return l.trim(); })
                                  .filter(Boolean);
    var problem = '';
    var givens = [];
    var seen = {};
    var steps = [];
    var notes = [];
    var order = 0;

    lines.forEach(function (line) {
      // Strip a leading "1)" / "2." label and keep it as the student's own.
      var label = null;
      var lm = line.match(/^(\(?\d+[\).]?)\s+(.*)$/);
      if (lm) { label = lm[1].replace(/[^\d)]/g, '') || lm[1]; line = lm[2].trim(); }

      var eq = line.indexOf('=');
      if (eq === -1) {
        var bare = parseValue(line);
        if (!bare) {
          // Prose that still carries a claim -- "proj of v onto the x axis is
          // (0,2)" -- is work, not commentary. Keep the sentence as what they
          // wrote and lift the value out of the end of it, instead of filing
          // the whole line as unreadable and rendering nothing.
          var tail = line.match(TAIL_VALUE_RE);
          if (tail) bare = parseValue(tail[1]);
        }
        if (bare) {
          order++;
          steps.push(mkStep(order, label, line, null, bare, true));
        } else if (!problem) {
          problem = line;                      // prose before the working
        } else {
          notes.push('Could not read: "' + line + '"');
          order++;
          steps.push(mkStep(order, label, line, null, null, false));
        }
        return;
      }

      var lhsText = line.slice(0, eq);
      var rhsText = line.slice(eq + 1);
      var lhs = parseLhs(lhsText);
      var value = parseValue(rhsText);

      if (!lhs || !value) {
        notes.push('Could not read: "' + line + '"');
        order++;
        steps.push(mkStep(order, label, line, lhs, null, false));
        return;
      }

      // A bare "A = <value>" the first time it appears is a given: it is the
      // problem's data, not a claim the student is making.
      if (lhs.op === 'copy_given' && !seen[lhs.syms[0]]) {
        seen[lhs.syms[0]] = true;
        givens.push({ symbol: lhs.syms[0], object: value, source: 'printed', confidence: 0.99 });
      }
      order++;
      steps.push(mkStep(order, label, line, lhs, value, true));
    });

    if (!steps.length) {
      return { ok: false, error: 'Nothing to analyse. Write one step per line, like  AB = [0 -3; 1 0]', notes: notes };
    }
    if (!steps.some(function (s) { return s.parse_ok; })) {
      return { ok: false, error: 'None of those lines parsed. Entries go in brackets, rows split by ";", like  A = [0 -1; 1 0]', notes: notes };
    }

    steps[steps.length - 1].is_final_answer = true;
    return { ok: true, problem: problem, givens: givens, steps: steps, notes: notes };
  }

  function mkStep(order, label, raw, lhs, value, ok) {
    return {
      id: 's' + order,
      student_label: label ? String(label) : String(order) + ')',
      page: 1,
      reading_order: order,
      bbox: null,
      raw_text: raw,
      claimed_expression: lhs ? lhs.expr : null,
      claimed_operation: lhs ? lhs.op : 'unknown',
      op_args: { rows: null, scalar: null, source_symbols: lhs ? lhs.syms : [], note: null },
      value: value,
      alternates: [],
      ambiguities: [],
      crossed_out: false,
      is_final_answer: false,
      parse_ok: !!ok,
      // Typed text is not a photograph: there is no glyph to misread, so this
      // is certainty about the transcription, not about the mathematics.
      confidence: ok ? 1 : 0,
      confidence_reason: ok ? 'typed directly, not transcribed' : 'could not parse this line',
    };
  }

  /* -> the JSON body /api/analyze accepts on its no-vision path */
  function toPayload(parsed) {
    var last = parsed.steps[parsed.steps.length - 1];
    return {
      document: { page_count: 1, legibility: 'usable', orientation_ok: true, multiple_problems_detected: false },
      problem: {
        present: !!parsed.problem || parsed.givens.length > 0,
        statement: parsed.problem || '',
        topic: 'unknown',
        asks_for: '',
        confidence: parsed.problem ? 0.9 : 0.4,
        givens: parsed.givens,
      },
      steps: parsed.steps,
      final_answer: { present: true, step_id: last.id, value: last.value },
      meta: {
        unreadable_regions: [],
        warnings: parsed.notes.slice(),
        source: 'typed',
      },
    };
  }


  /* ── a question, not working ───────────────────────────────────────────
   *
   * "i reduced it but don't understand what it says about how many solutions
   * there are" has no '=' and no brackets, so parse() finds no steps and the
   * box used to answer with a syntax lecture. There is no model behind this
   * box, so it cannot answer the question -- but it can work out WHICH piece
   * of work would let it show the answer, and ask for that.
   *
   * Matched against the question and the kept problem together, because the
   * problem statement is usually the thing that names the task.
   */

  var ASKS = [
    { wants: 'your reduced row echelon form',
      words: ['row echelon', 'rref', 'row reduce', 'row-reduce', 'row reduction',
              'augmented', 'echelon', 'how many solutions', 'no solution',
              'one solution', 'infinitely many', 'consistent', 'inconsistent',
              'gaussian', 'gauss'] },
    { wants: 'your eigenvector work',  words: ['eigen'] },
    { wants: 'your inverse',           words: ['inverse', 'invert', 'adjugate'] },
    { wants: 'your determinant',       words: ['determinant', 'det('] },
    { wants: 'your projection',        words: ['projection', 'project ', 'orthogonal', 'perpendicular'] },
    { wants: 'your row reduction',     words: ['rank', 'independent', 'independence', 'basis', 'span'] },
    { wants: 'your product',           words: ['multiply', 'multiplication', 'product', 'compose', 'composition', 'order'] },
  ];

  var OUT_OF_SCOPE = ['derivative', 'differentiate', 'integral', 'integrate',
                      'calculus', 'limit', 'chain rule', 'taylor'];

  /* Is this a question to answer, or work to check?
   *
   * The old test was "no = and no brackets means a question", which sent every
   * typed solution written in prose -- "proj of v onto the x axis is (0,2)" --
   * down the ask-for-an-upload path, so it could never produce a video. A line
   * carrying an equation, a vector or a matrix is WORK, whatever words are
   * wrapped around it; a line that opens interrogatively, or ends in a question
   * mark, or carries no numbers at all, is a question.
   */
  var TUPLE_RE = /\(\s*-?\d+(?:\.\d+)?(?:\s*,\s*-?\d+(?:\.\d+)?)+\s*\)/;
  var ASKING_RE = /^\s*(?:how|what|why|when|which|who|where|can|could|would|should|do|does|did|is|are|explain|help|show|tell|walk|give|teach)\b/i;

  function isQuestion(text) {
    var t = String(text || '').trim();
    if (!t) return true;
    if (/\?\s*$/.test(t)) return true;             // asked outright
    if (/[=\[\]]/.test(t) || TUPLE_RE.test(t)) return false;   // carries a claim
    if (ASKING_RE.test(t)) return true;
    return !/\d/.test(t);                          // no numbers: nothing to check
  }

  /* whatToAsk(question, problem) -> {ask} | {outOfScope, term} */
  function whatToAsk(question, problem) {
    var q = String(question || '').toLowerCase();
    var both = (q + ' ' + String(problem || '')).toLowerCase();

    for (var i = 0; i < OUT_OF_SCOPE.length; i++) {
      if (q.indexOf(OUT_OF_SCOPE[i]) !== -1) return { outOfScope: OUT_OF_SCOPE[i] };
    }
    for (var j = 0; j < ASKS.length; j++) {
      for (var k = 0; k < ASKS[j].words.length; k++) {
        if (both.indexOf(ASKS[j].words[k]) !== -1) return { ask: ASKS[j].wants };
      }
    }
    return { ask: 'your work' };
  }

  global.NoemaTyped = { parse: parse, toPayload: toPayload, parseValue: parseValue,
    isQuestion: isQuestion, whatToAsk: whatToAsk };
})(window);
