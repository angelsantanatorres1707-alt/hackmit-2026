/* app.js — state machine, API calls, rendering.
 *
 * Flow: input -> working -> readback -> result
 *
 * The render is fired speculatively by the backend the moment /api/analyze
 * returns (EXTRACTION.md 7.4), so the read-back screen is the render's dead
 * time. We poll the job in the background the whole time the student is
 * reading, which is why the video is usually already there when they click.
 *
 * ONE HARD RULE: this file never displays job.correct_value, job.scene_params
 * or anything derived from them. Those carry the answer. The student gets the
 * animation and a positional hint; the correction is theirs to make.
 */
(function () {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const POLL_MS = 1100;
  const POLL_TIMEOUT_MS = 180000;

  const S = {
    files: [],
    photoURL: null,
    job: null,
    edits: {},
    pollTimer: null,
    pollStart: 0,
    tickTimer: null,
    started: 0,
    recognizer: null,
    listening: false,
  };

  /* ── helpers ──────────────────────────────────────────────────────── */

  function setStage(name) {
    document.body.dataset.stage = name;
    $('#restart-btn').hidden = name === 'input';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  let toastTimer = null;
  function toast(msg, ms) {
    const node = $('#toast');
    node.textContent = msg;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, ms || 5200);
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body && body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      } catch (_) { /* not json */ }
      throw new Error(detail);
    }
    return res.json();
  }

  /* ── stage 1: input ───────────────────────────────────────────────── */

  function addFiles(list) {
    const incoming = Array.from(list || []).filter((f) => f && f.size > 0);
    if (!incoming.length) return;
    S.files = S.files.concat(incoming).slice(0, 4);
    renderThumbs();
  }

  function renderThumbs() {
    const box = $('#thumbs');
    clear(box);
    box.hidden = S.files.length === 0;
    S.files.forEach((file, i) => {
      const t = el('div', 'thumb');
      const img = el('img');
      img.alt = file.name || 'page';
      if (/^image\//.test(file.type)) img.src = URL.createObjectURL(file);
      const rm = el('button', null, '×');
      rm.title = 'Remove';
      rm.addEventListener('click', (e) => {
        e.stopPropagation();
        S.files.splice(i, 1);
        renderThumbs();
      });
      t.appendChild(img);
      t.appendChild(rm);
      box.appendChild(t);
    });
    $('#analyze-btn').disabled = S.files.length === 0;
    $('#analyze-btn').textContent = S.files.length > 1
      ? `Read my work (${S.files.length} pages)` : 'Read my work';
  }

  function wireInput() {
    const zone = $('#dropzone');
    const input = $('#file-input');

    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
    input.addEventListener('change', () => { addFiles(input.files); input.value = ''; });

    ['dragenter', 'dragover'].forEach((ev) =>
      zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('over'); }));
    ['dragleave', 'drop'].forEach((ev) =>
      zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove('over'); }));
    zone.addEventListener('drop', (e) => {
      if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
    });

    // paste anywhere on the input screen — the fastest path from phone to page
    document.addEventListener('paste', (e) => {
      if (document.body.dataset.stage !== 'input') return;
      const items = (e.clipboardData && e.clipboardData.items) || [];
      const files = [];
      for (const item of items) {
        if (item.kind === 'file') {
          const f = item.getAsFile();
          if (f) files.push(f);
        }
      }
      if (files.length) { e.preventDefault(); addFiles(files); toast('Pasted your screenshot.'); }
    });

    $('#analyze-btn').addEventListener('click', startFromFiles);
    $('#restart-btn').addEventListener('click', restart);
    $('#back-btn').addEventListener('click', () => setStage('input'));
    $('#again-btn').addEventListener('click', restart);
    $('#edit-btn').addEventListener('click', () => setStage('readback'));
    $('#confirm-btn').addEventListener('click', confirmReadback);
    $('#replay-btn').addEventListener('click', () => {
      const v = $('#video');
      if (!v.src) return;
      v.currentTime = 0;
      v.play().catch(() => {});
    });
    $('#sample-photo-btn').addEventListener('click', loadSamplePhoto);
  }

  async function loadSamplePhoto() {
    try {
      const res = await fetch('sample-work.jpg');
      if (!res.ok) throw new Error('sample image missing');
      const blob = await res.blob();
      S.files = [new File([blob], 'sample-work.jpg', { type: 'image/jpeg' })];
      renderThumbs();
      startFromFiles();
    } catch (e) {
      toast('Could not load the sample photo: ' + e.message);
    }
  }

  async function loadFixtures() {
    try {
      const data = await api('/api/fixtures');
      const box = $('#sample-chips');
      clear(box);
      (data.fixtures || []).forEach((f) => {
        const chip = el('button', 'chip');
        chip.type = 'button';
        const title = String(f.title || f.name);
        const dash = title.indexOf(' - ');
        if (dash > 0) {
          chip.appendChild(el('b', null, title.slice(0, dash)));
          chip.appendChild(document.createTextNode(' · ' + title.slice(dash + 3)));
        } else {
          chip.appendChild(el('b', null, title));
        }
        chip.addEventListener('click', () => startFromFixture(f.name));
        box.appendChild(chip);
      });
    } catch (e) {
      $('#sample-chips').appendChild(el('span', 'samples-label', 'Samples unavailable: ' + e.message));
    }
  }

  async function loadHealth() {
    try {
      const h = await api('/api/health');
      const pill = $('#health-pill');
      pill.hidden = false;
      if (h.fixture_mode) {
        pill.textContent = 'Fixture mode';
        pill.classList.add('warn');
        pill.title = 'No API key: canned extractions, live verification and live rendering.';
      } else {
        pill.textContent = 'Live vision';
        pill.title = 'Reading photos with ' + (h.model || 'the vision model');
      }
    } catch (_) { /* the page still works; the API call will report properly */ }
  }

  /* ── stage 2: working ─────────────────────────────────────────────── */

  const READ_MESSAGES = [
    [0, 'Reading your handwriting', 'Transcribing every line exactly as written — mistakes included.'],
    [7, 'Still reading', 'A full page of work is 10–20 seconds. It is copying the pen, not the mathematics.'],
    [22, 'Nearly there', 'Long pages take longer. Nothing has gone wrong.'],
  ];

  function startWorking(kind) {
    setStage('working');
    S.started = Date.now();
    setPhases(kind === 'recheck' ? 'check' : 'read');
    if (kind === 'recheck') {
      $('#work-title').textContent = 'Re-reading with your corrections';
      $('#work-sub').textContent = 'Checking every step again against the problem.';
    }
    clearInterval(S.tickTimer);
    S.tickTimer = setInterval(() => {
      const secs = (Date.now() - S.started) / 1000;
      $('#elapsed').textContent = secs.toFixed(1) + 's';
      if (kind !== 'recheck') {
        for (let i = READ_MESSAGES.length - 1; i >= 0; i--) {
          if (secs >= READ_MESSAGES[i][0]) {
            $('#work-title').textContent = READ_MESSAGES[i][1];
            $('#work-sub').textContent = READ_MESSAGES[i][2];
            break;
          }
        }
      }
    }, 200);
  }

  function stopWorking() { clearInterval(S.tickTimer); }

  function setPhases(active) {
    const order = ['read', 'check', 'render'];
    const idx = order.indexOf(active);
    order.forEach((name, i) => {
      const li = document.querySelector(`.phases li[data-phase="${name}"]`);
      if (!li) return;
      li.classList.toggle('active', i === idx);
      li.classList.toggle('done', i < idx);
    });
  }

  /* ── running the pipeline ─────────────────────────────────────────── */

  function startFromFiles() {
    if (!S.files.length) return;
    const fd = new FormData();
    S.files.forEach((f) => fd.append('images', f, f.name || 'page.jpg'));
    const note = $('#problem-text').value.trim();
    if (note) fd.append('problem_note', note); // ignored by the API today; harmless
    setPhoto(S.files[0]);
    run(() => api('/api/analyze', { method: 'POST', body: fd }), 'read');
  }

  function startFromFixture(name) {
    S.files = [];
    renderThumbs();
    setPhoto(null);
    run(() => api('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fixture: name }),
    }), 'read');
  }

  function setPhoto(file) {
    if (S.photoURL) { URL.revokeObjectURL(S.photoURL); S.photoURL = null; }
    const col = $('#photo-col');
    if (file && /^image\//.test(file.type)) {
      S.photoURL = URL.createObjectURL(file);
      $('#photo-preview').src = S.photoURL;
      col.hidden = false;
    } else {
      col.hidden = true;
    }
  }

  /** Returns the job on success, null on failure (so callers can chain). */
  async function run(request, kind) {
    stopPolling();
    startWorking(kind);
    try {
      const job = await request();
      stopWorking();
      // The API has no field for a typed/dictated problem (verify.py reads
      // problem.topic and the givens, never the statement), so it cannot change
      // the verdict. Rather than drop it silently, show it when the page itself
      // carried no problem statement, labelled as coming from the student.
      const typed = $('#problem-text').value.trim();
      if (typed && job.problem && !job.problem.statement) {
        job.problem.statement = typed;
        job.problem.from_typed = true;
      }
      S.job = job;
      S.edits = {};
      renderReadback(job);
      setStage('readback');
      startPolling(job.job_id); // the render is already going, server-side
      return job;
    } catch (e) {
      stopWorking();
      setStage('input');
      toast('Could not read that: ' + e.message + ' — try a sample below.', 9000);
      return null;
    }
  }

  async function confirmReadback() {
    const bad = LIB.invalidCells(S.edits);
    if (bad.length) { toast('One of the boxes is empty. Put the number back before continuing.'); return; }

    if (LIB.countEdits(S.edits) > 0) {
      const extraction = LIB.buildExtraction(S.job, S.edits);
      const job = await run(() => api('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ extraction }),
      }), 'recheck');
      if (job) showResult(); // straight through: they already confirmed the reading
      return;
    }
    showResult();
  }

  /* ── stage 3: read-back ───────────────────────────────────────────── */

  function renderReadback(job) {
    const problem = job.problem || {};
    const card = $('#problem-card');
    const hasProblem = problem.statement || (problem.givens || []).length;
    card.hidden = !hasProblem;
    const stmt = $('#problem-statement');
    clear(stmt);
    stmt.hidden = !problem.statement;
    if (problem.statement) {
      stmt.appendChild(document.createTextNode(problem.statement));
      if (problem.from_typed) stmt.appendChild(el('span', 'flag', 'from what you typed'));
    }

    const givens = $('#givens');
    clear(givens);
    (problem.givens || []).forEach((g) => {
      const row = el('div', 'given');
      row.appendChild(el('span', 'given-symbol', g.symbol + ' ='));
      row.appendChild(mobjEl(g.object, { editable: true, key: 'given:' + g.symbol }));
      givens.appendChild(row);
    });

    const list = $('#readback-steps');
    clear(list);
    (job.steps || []).forEach((s) => list.appendChild(stepEl(s, { editable: true })));
    $('#step-count').textContent = (job.steps || []).length + ' lines';

    const warnBox = $('#warnings');
    clear(warnBox);
    const warnings = (job.warnings || []).slice();
    const doc = job.document || {};
    if (doc.legibility === 'poor' || doc.legibility === 'unreadable') {
      warnings.push('The photo is hard to read — check the numbers below carefully.');
    }
    if (doc.multiple_problems_detected) warnings.push('More than one problem is on this page; only the first was read.');
    warnBox.hidden = warnings.length === 0;
    warnings.forEach((w) => warnBox.appendChild(el('div', 'warn-row', w)));

    updateDirty();
  }

  function stepEl(view, opts) {
    const li = el('li', 'step');
    li.dataset.id = view.id;
    li.appendChild(el('div', 'step-label', view.label || String(view.reading_order || '')));

    const body = el('div', 'step-body');

    if (opts.editable) {
      const raw = el('input', 'step-raw');
      raw.value = view.raw_text || '';
      raw.dataset.orig = view.raw_text || '';
      raw.setAttribute('aria-label', 'What the camera read on this line');
      raw.addEventListener('input', () => {
        const e = S.edits[view.id] || (S.edits[view.id] = {});
        if (raw.value === raw.dataset.orig) delete e.raw_text;
        else e.raw_text = raw.value;
        pruneEdits();
        updateDirty();
      });
      body.appendChild(raw);
    } else if (view.raw_text) {
      body.appendChild(el('div', 'step-raw', view.raw_text));
    }

    if (view.value) {
      const m = mobjEl(view.value, { editable: !!opts.editable, key: view.id });
      if (m) body.appendChild(m);
    }

    const flags = el('div', 'step-flags');
    if (opts.locate) {
      const look = el('span', 'look-here', 'Look here');
      flags.appendChild(look);
    }
    if (view.crossed_out) flags.appendChild(el('span', 'flag crossed', 'crossed out'));
    if (view.is_final_answer) flags.appendChild(el('span', 'flag', 'final answer'));
    if (view.status === 'SKIPPED_UNPARSED') flags.appendChild(el('span', 'flag review', "couldn't read this line"));
    else if (view.needs_review && opts.editable) flags.appendChild(el('span', 'flag review', 'camera unsure — check this'));
    (view.ambiguities || []).forEach((a) => {
      if (!a || !a.read_as) return;
      const alt = (a.could_be || []).join(' or ');
      flags.appendChild(el('span', 'flag review', `read "${a.read_as}"${alt ? ' — could be ' + alt : ''}`));
    });
    if (flags.childNodes.length) body.appendChild(flags);

    li.appendChild(body);
    if (opts.locate) li.classList.add('located');
    return li;
  }

  /** A matrix/vector/scalar drawn with CSS brackets. Same look as the
   *  TextMatrix in the animation, which is also LaTeX-free. */
  function mobjEl(view, opts) {
    if (!view) return null;
    const grid = LIB.cellGrid(view);

    if (!grid) {
      if (view.text) return el('div', 'mobj-text', view.text);
      return null;
    }

    const cols = Math.max.apply(null, grid.map((r) => r.length));
    // Brackets mean "matrix". A lone scalar, a list of eigenvalues and a
    // polynomial's coefficients are not matrices and must not wear them.
    const bracketed = !LIB.LIST_KINDS.has(view.kind) && view.kind !== 'scalar';
    const separated = !bracketed && cols > 1;

    const wrap = el('div', 'mobj');
    if (bracketed) wrap.appendChild(el('div', 'bracket left'));

    const g = el('div', 'mobj-grid');
    g.style.gridTemplateColumns = separated ? `repeat(${cols * 2 - 1}, auto)` : `repeat(${cols}, auto)`;

    grid.forEach((row, i) => {
      row.forEach((val, j) => {
        if (separated && j > 0) g.appendChild(el('span', 'cell sep', ','));
        const text = String(val);
        if (opts.editable) {
          const input = el('input', 'cell');
          input.value = text;
          input.dataset.orig = text;
          input.size = Math.max(2, text.length);
          input.setAttribute('aria-label', `row ${i + 1} column ${j + 1}`);
          input.addEventListener('input', () => {
            input.size = Math.max(2, input.value.length);
            recordCell(opts.key, i, j, input);
          });
          input.addEventListener('focus', () => input.select());
          g.appendChild(input);
        } else {
          g.appendChild(el('span', 'cell', text));
        }
      });
    });

    wrap.appendChild(g);
    if (bracketed) wrap.appendChild(el('div', 'bracket right'));
    if (view.kind === 'polynomial' && view.var) {
      wrap.appendChild(el('span', 'mobj-note', `coefficients in ${view.var}`));
    }
    return wrap;
  }

  function recordCell(key, i, j, input) {
    const entry = S.edits[key] || (S.edits[key] = {});
    entry.cells = entry.cells || {};
    const cellKey = i + ',' + j;
    const value = input.value;

    if (value === input.dataset.orig) delete entry.cells[cellKey];
    else entry.cells[cellKey] = value;

    const parsed = LIB.parseCell(value);
    input.classList.toggle('invalid', parsed.empty);
    input.classList.toggle('edited', value !== input.dataset.orig && !parsed.empty);

    pruneEdits();
    updateDirty();
  }

  function pruneEdits() {
    for (const key of Object.keys(S.edits)) {
      const e = S.edits[key];
      if (e.cells && !Object.keys(e.cells).length) delete e.cells;
      if (!e.cells && e.raw_text == null) delete S.edits[key];
    }
  }

  function updateDirty() {
    const n = LIB.countEdits(S.edits);
    $('#dirty-note').hidden = n === 0;
    $('#dirty-note').textContent = n === 1 ? '1 correction — I’ll re-read it' : n + ' corrections — I’ll re-read it';
    $('#confirm-btn').textContent = n ? 'Re-check with my corrections' : 'That’s my work — show me';
  }

  /* ── stage 4: result ──────────────────────────────────────────────── */

  const RENDER_SUB = 'Manim is drawing both transformations frame by frame. About 8 seconds.';

  function showResult() {
    const job = S.job;
    if (!job) return;
    setStage('result');

    const list = $('#result-steps');
    clear(list);
    (job.steps || []).forEach((s) => {
      list.appendChild(stepEl(s, { editable: false, locate: !!s.is_first_error }));
    });

    const noError = job.first_error_index === null || job.first_error_index === undefined;
    $('#hint-text').textContent = job.hint || '';
    $('#hint-card').hidden = !job.hint;
    document.querySelector('.hint-eyebrow').textContent = noError ? 'All clear' : 'Look here';

    const foot = $('#rail-foot');
    clear(foot);
    if (job.first_error_index === null || job.first_error_index === undefined) {
      foot.appendChild(el('span', null, 'Every line agrees with the problem as it was read.'));
    } else {
      const n = (job.steps || []).length;
      foot.appendChild(el('b', null, 'Checked ' + n + (n === 1 ? ' line' : ' lines') + '. '));
      foot.appendChild(document.createTextNode('The highlighted one is the first that disagrees with the problem.'));
    }

    S.resultAt = Date.now(); // the wait the student actually experiences
    $('#overlay-sub').textContent = RENDER_SUB;
    $('#render-elapsed').textContent = '';
    applyVideoState(job);
    if (!S.pollTimer && shouldPoll(job)) startPolling(job.job_id);
  }

  function shouldPoll(job) {
    return job.video_status === 'pending' || job.video_status === 'rendering';
  }

  function applyVideoState(job) {
    const overlay = $('#video-overlay');
    const fallback = $('#video-fallback');
    const frame = $('#video-frame');
    const video = $('#video');

    if (job.video_status === 'ready') {
      fallback.hidden = true;
      overlay.hidden = true;
      frame.hidden = false;
      const src = job.video_url || ('/api/video/' + job.job_id);
      if (video.getAttribute('src') !== src) {
        video.setAttribute('src', src);
        video.load();
      }
      const p = video.play();
      if (p && p.catch) p.catch(() => toast('Press "Play it again" to start the animation.'));
      return;
    }

    if (job.video_status === 'failed' || job.video_status === 'not_needed') {
      overlay.hidden = true;
      if (job.video_status === 'not_needed') {
        frame.hidden = true;
      } else {
        frame.hidden = false;
        fallback.hidden = false;
        $('#fallback-reason').textContent =
          'The hint below still points at the step. ' + (job.video_error || '');
      }
      return;
    }

    // pending / rendering
    frame.hidden = false;
    fallback.hidden = true;
    overlay.hidden = false;
    setPhases('render');
  }

  /* ── polling ──────────────────────────────────────────────────────── */

  function startPolling(jobId) {
    stopPolling();
    S.pollStart = Date.now();
    const started = Date.now();

    const tick = async () => {
      if (Date.now() - S.pollStart > POLL_TIMEOUT_MS) {
        stopPolling();
        if (S.job) { S.job.video_status = 'failed'; S.job.video_error = 'the render took too long'; }
        if (document.body.dataset.stage === 'result') applyVideoState(S.job);
        return;
      }
      try {
        const fresh = await api('/api/job/' + jobId);
        if (!S.job || S.job.job_id !== jobId) return; // a newer job took over
        S.job = fresh;
        if (document.body.dataset.stage === 'result') applyVideoState(fresh);
        if (!shouldPoll(fresh)) { stopPolling(); return; }
      } catch (_) { /* transient; keep polling */ }
      if (document.body.dataset.stage === 'result') {
        const waited = (Date.now() - (S.resultAt || started)) / 1000;
        $('#render-elapsed').textContent = waited.toFixed(1) + 's';
        if (waited > 14) {
          $('#overlay-sub').textContent =
            'This scene has more stages than most, so it takes a little longer. Still going.';
        }
      }
      S.pollTimer = setTimeout(tick, POLL_MS);
    };
    S.pollTimer = setTimeout(tick, 400);
  }

  function stopPolling() {
    clearTimeout(S.pollTimer);
    S.pollTimer = null;
  }

  /* ── voice (secondary path; never blocks the photo) ───────────────── */

  function wireVoice() {
    const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
    const btn = $('#mic-btn');
    const label = $('#mic-label');
    const status = $('#mic-status');

    if (!Rec) {
      btn.disabled = true;
      label.textContent = 'Voice needs Chrome';
      status.textContent = 'Dictation uses the Web Speech API — available in Chrome and Edge. Typing works everywhere.';
      return;
    }

    const rec = new Rec();
    S.recognizer = rec;
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = 'en-US';

    let base = '';

    rec.addEventListener('result', (event) => {
      let finalText = '';
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalText += chunk;
        else interim += chunk;
      }
      if (finalText) {
        base = (base ? base.replace(/\s*$/, ' ') : '') + finalText.trim();
        $('#problem-text').value = base;
      }
      status.textContent = interim ? '…' + interim : 'Listening…';
      status.className = 'mic-status live';
    });

    rec.addEventListener('error', (event) => {
      const map = {
        'not-allowed': 'Microphone blocked. Allow it in the address bar, or just type.',
        'service-not-allowed': 'Dictation needs https or localhost.',
        'no-speech': 'Heard nothing — try again.',
        'audio-capture': 'No microphone found.',
      };
      status.textContent = map[event.error] || ('Dictation stopped: ' + event.error);
      status.className = 'mic-status';
      stopListening();
    });

    rec.addEventListener('end', () => { if (S.listening) stopListening(); });

    btn.addEventListener('click', () => {
      if (S.listening) { stopListening(); return; }
      base = $('#problem-text').value.trim();
      try { rec.start(); } catch (_) { return; }
      S.listening = true;
      btn.classList.add('listening');
      label.textContent = 'Stop';
      status.textContent = 'Listening…';
      status.className = 'mic-status live';
    });

    function stopListening() {
      S.listening = false;
      try { rec.stop(); } catch (_) { /* already stopped */ }
      btn.classList.remove('listening');
      label.textContent = 'Speak it';
      if (status.textContent.indexOf('…') === 0 || status.textContent === 'Listening…') status.textContent = '';
      status.className = 'mic-status';
    }
  }

  /* ── reset ────────────────────────────────────────────────────────── */

  function restart() {
    stopPolling();
    stopWorking();
    const v = $('#video');
    v.pause();
    v.removeAttribute('src');
    v.load();
    S.job = null;
    S.edits = {};
    S.files = [];
    setPhoto(null);
    renderThumbs();
    $('#problem-text').value = '';
    setStage('input');
  }

  /* ── boot ─────────────────────────────────────────────────────────── */

  wireInput();
  wireVoice();
  renderThumbs();
  loadFixtures();
  loadHealth();

  window.__APP__ = { S, LIB, showResult, renderReadback, restart }; // debugging on stage
})();
