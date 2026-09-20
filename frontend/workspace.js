/* Noema — workspace page.
 *
 * Deliberately standalone: this file does NOT share state with app.js. The
 * classic four-stage flow still lives in classic.html and is still driven by
 * app.js, untouched, so the demo has a fallback if this page misbehaves.
 *
 * What is real here and what is not:
 *   - upload -> /api/analyze -> poll /api/job/{id} -> play /api/video/{id}
 *     is the genuine pipeline, same endpoints the classic flow uses.
 *   - the prompt box is carried to the API as `problem_note`, which the API
 *     accepts and currently ignores (app.js does the same and says so). It is
 *     NOT yet steering the renderer; that needs a backend endpoint.
 *   - PDFs are accepted by the picker because the product asks for them, but
 *     backend/extract.py opens every upload with PIL and has no PDF path, so
 *     we say so up front instead of letting it 502 at the worst moment.
 */
(function () {
  'use strict';

  var $ = function (sel) { return document.querySelector(sel); };

  var POLL_MS = 900;
  var POLL_TIMEOUT_MS = 150000;

  var S = {
    files: [],
    job: null,
    pollTimer: null,
    pollStart: 0,
    fps: 30,
    busy: false,
  };

  /* ── tiny helpers ──────────────────────────────────────────────────── */

  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      if (!r.ok) {
        return r.json().then(
          function (b) { throw new Error(b.detail || r.statusText); },
          function () { throw new Error(r.statusText || ('HTTP ' + r.status)); }
        );
      }
      return r.json();
    });
  }

  var toastTimer = null;
  function toast(msg) {
    var el = $('#ws-toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 5200);
  }

  function mmss(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    var m = Math.floor(sec / 60), s = Math.floor(sec % 60);
    return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  function kb(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return Math.round(n / 1024) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }

  function isPdf(f) {
    return f.type === 'application/pdf' || /\.pdf$/i.test(f.name || '');
  }

  /* ── status chips ──────────────────────────────────────────────────── */

  var FPS_BY_QUALITY = {
    low_quality: 15, medium_quality: 30, high_quality: 60,
    production_quality: 60, fourk_quality: 60,
  };

  function setChip(id, cls, value) {
    var el = $(id);
    el.className = 'ws-chip ' + cls;
    el.querySelector('b').textContent = value;
  }

  function loadHealth() {
    api('/api/health').then(function (h) {
      if (h.fixture_mode) setChip('#chip-extract', 'warn', 'fixture');
      else if (h.vision && h.vision.active) setChip('#chip-extract', 'ok', String(h.vision.active));
      else setChip('#chip-extract', 'warn', 'no key');

      var tpl = (h.scene_templates || []).length;
      setChip('#chip-engine', tpl ? 'ok' : 'bad', tpl ? 'ready' : 'unavailable');
      S.fps = FPS_BY_QUALITY[h.render_quality] || 30;
      $('#viz-badge').textContent = (h.render_quality || 'manim').replace('_quality', '') + ' · ' + S.fps + ' fps';
    }).catch(function () {
      setChip('#chip-extract', 'bad', 'offline');
      setChip('#chip-engine', 'bad', 'offline');
    });
  }

  function loadSamples() {
    api('/api/fixtures').then(function (d) {
      var row = $('#ws-samples');
      (d.fixtures || []).forEach(function (f) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'ws-sample';
        b.textContent = f.title || f.name;
        b.title = f.expect || '';
        b.addEventListener('click', function () { runFixture(f.name, f.title || f.name); });
        row.appendChild(b);
      });
    }).catch(function () { /* samples are a convenience, not the product */ });
  }

  /* ── files ─────────────────────────────────────────────────────────── */

  function addFiles(list) {
    var added = 0;
    Array.prototype.forEach.call(list, function (f) {
      if (!f) return;
      var ok = isPdf(f) || /^image\//.test(f.type) || /\.(hei[cf])$/i.test(f.name || '');
      if (!ok) return;
      S.files.push(f);
      added++;
    });
    if (added) renderFiles();
  }

  function renderFiles() {
    var ul = $('#ws-files');
    ul.textContent = '';
    S.files.forEach(function (f, i) {
      var li = document.createElement('li');
      li.className = 'ws-file' + (isPdf(f) ? ' bad' : '');

      var kind = document.createElement('span');
      kind.className = 'kind';
      kind.textContent = isPdf(f) ? 'pdf' : ((f.name || '').split('.').pop() || 'img').slice(0, 4);

      var nm = document.createElement('span');
      nm.className = 'nm';
      nm.textContent = f.name || 'upload';

      var sz = document.createElement('span');
      sz.className = 'sz';
      sz.textContent = kb(f.size);

      var x = document.createElement('button');
      x.className = 'x';
      x.type = 'button';
      x.setAttribute('aria-label', 'Remove ' + (f.name || 'file'));
      x.textContent = '×';
      x.addEventListener('click', function () {
        S.files.splice(i, 1);
        renderFiles();
      });

      li.appendChild(kind); li.appendChild(nm); li.appendChild(sz); li.appendChild(x);
      ul.appendChild(li);
    });

    // Say the honest thing about PDFs rather than letting the API 502.
    var pdfs = S.files.filter(isPdf).length;
    var notice = $('#ws-notice');
    if (pdfs) {
      notice.hidden = false;
      notice.innerHTML =
        '<b>PDFs are not readable yet.</b> The extractor opens uploads as images ' +
        '(backend/extract.py), so a PDF will come back as an extraction error. ' +
        'Export the page as PNG or JPEG for now, or drop a photo of it.';
    } else {
      notice.hidden = true;
    }

    $('#stat-input').textContent = S.files.length
      ? 'input :: ' + S.files.length + ' file' + (S.files.length > 1 ? 's' : '')
      : 'input :: awaiting';
    $('#ws-path').innerHTML = S.files.length
      ? '~/workspace/<b>' + escapeHtml(S.files[0].name || 'upload') + '</b>'
      : '~/workspace/<b>untitled</b>';
    syncRun();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function syncRun() {
    $('#ws-run').disabled = S.busy || !S.files.length;
  }

  /* ── the conversation log ──────────────────────────────────────────── */

  function log(who, msg, mine) {
    var li = document.createElement('li');
    if (mine) li.className = 'you';
    var w = document.createElement('span'); w.className = 'who'; w.textContent = who;
    var m = document.createElement('span'); m.className = 'msg'; m.textContent = msg;
    li.appendChild(w); li.appendChild(m);
    var ol = $('#ws-log');
    ol.appendChild(li);
    ol.scrollTop = ol.scrollHeight;
  }

  /* ── running an analysis ───────────────────────────────────────────── */

  function run() {
    if (S.busy || !S.files.length) return;
    var note = $('#ws-prompt').value.trim();

    var fd = new FormData();
    S.files.forEach(function (f) { fd.append('images', f, f.name || 'page.jpg'); });
    if (note) fd.append('problem_note', note);

    if (note) {
      log('you', note, true);
      $('#ws-prompt').value = '';
    }
    log('noema', 'Reading ' + S.files.length + ' page' + (S.files.length > 1 ? 's' : '') + '…');

    start(api('/api/analyze', { method: 'POST', body: fd }));
  }

  function runFixture(name, title) {
    if (S.busy) return;
    S.files = [];
    renderFiles();
    log('you', 'Run the bundled sample: ' + title, true);
    start(api('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fixture: name }),
    }));
  }

  function start(promise) {
    S.busy = true;
    syncRun();
    $('#stat-viz').textContent = 'analysing';
    showViz('busy');
    $('#viz-busy-title').textContent = 'Reading your work';
    $('#viz-busy-sub').textContent = 'Transcribing every line exactly as written — mistakes included.';

    promise.then(function (job) {
      S.job = job;
      S.busy = false;
      syncRun();
      applyJob(job);
      if (shouldPoll(job)) startPolling(job.job_id);
    }).catch(function (err) {
      S.busy = false;
      syncRun();
      $('#stat-viz').textContent = 'error';
      showViz('failed');
      $('#viz-failed-why').textContent = String(err.message || err);
      log('noema', 'That did not go through: ' + (err.message || err));
      toast(err.message || 'The analysis failed.');
    });
  }

  function shouldPoll(job) {
    return job && (job.video_status === 'pending' || job.video_status === 'rendering');
  }

  function startPolling(jobId) {
    stopPolling();
    S.pollStart = Date.now();
    var tick = function () {
      if (Date.now() - S.pollStart > POLL_TIMEOUT_MS) {
        stopPolling();
        if (S.job) { S.job.video_status = 'failed'; S.job.video_error = 'the render took too long'; }
        applyJob(S.job);
        return;
      }
      api('/api/job/' + jobId).then(function (fresh) {
        if (!S.job || S.job.job_id !== jobId) return;
        S.job = fresh;
        applyJob(fresh);
        if (!shouldPoll(fresh)) { stopPolling(); return; }
        S.pollTimer = setTimeout(tick, POLL_MS);
      }).catch(function () {
        S.pollTimer = setTimeout(tick, POLL_MS);   // transient; keep going
      });
    };
    S.pollTimer = setTimeout(tick, 400);
  }

  function stopPolling() {
    clearTimeout(S.pollTimer);
    S.pollTimer = null;
  }

  /* ── painting a job ────────────────────────────────────────────────── */

  function showViz(which) {
    $('#viz-empty').hidden = which !== 'empty';
    $('#viz-busy').hidden = which !== 'busy';
    $('#viz-failed').hidden = which !== 'failed';
    $('#ws-video').hidden = which !== 'video';
  }

  function applyJob(job) {
    if (!job) return;

    renderSteps(job);

    if (job.hint) {
      $('#viz-hint').hidden = false;
      $('#viz-hint-text').textContent = job.hint;
      $('#viz-hint-eyebrow').textContent =
        job.first_error_index === null || job.first_error_index === undefined ? 'All clear' : 'Look here';
    } else {
      $('#viz-hint').hidden = true;
    }

    var video = $('#ws-video');

    if (job.video_status === 'ready') {
      var src = job.video_url || ('/api/video/' + job.job_id);
      if (video.getAttribute('src') !== src) {
        video.setAttribute('src', src);
        video.load();
      }
      showViz('video');
      $('#stat-viz').textContent = 'playing';
      $('#ws-play').disabled = false;
      $('#ws-restart').disabled = false;
      var p = video.play();
      if (p && p.catch) p.catch(function () { toast('Press play to start the animation.'); });
      if (!applyJob._said) { log('noema', 'Animation ready. The hint points at the step — no correction.'); applyJob._said = true; }
      return;
    }

    if (job.video_status === 'failed' || job.video_status === 'not_needed') {
      showViz('failed');
      $('#stat-viz').textContent = job.video_status === 'not_needed' ? 'not needed' : 'render failed';
      $('#viz-failed-why').textContent = job.video_status === 'not_needed'
        ? 'Nothing to animate for this one.'
        : firstLine(job.video_error || 'the renderer did not produce a file');
      $('#ws-play').disabled = true;
      $('#ws-restart').disabled = true;
      return;
    }

    showViz('busy');
    $('#stat-viz').textContent = 'rendering';
    $('#viz-busy-title').textContent = 'Rendering';
    $('#viz-busy-sub').textContent = 'The first render of a scene takes a few seconds; repeats are cached.';
  }

  // Render errors arrive as a whole traceback. The cause is the useful part.
  function firstLine(err) {
    var s = String(err);
    // Match the raised message ("RenderError: no scene template named X"), not
    // the `raise RenderError(` line that appears earlier in the same traceback.
    var all = s.match(/\b\w*(?:Error|Exception): [^\n;]{3,200}/g);
    if (all && all.length) return all[all.length - 1].trim();
    return s.split('\n')[0].slice(0, 240);
  }

  function renderSteps(job) {
    var ol = $('#viz-steps');
    ol.textContent = '';
    (job.steps || []).forEach(function (st, i) {
      var li = document.createElement('li');
      li.className = 'viz-step' + (i === job.first_error_index ? ' located' : '');
      var lbl = document.createElement('span'); lbl.className = 'lbl'; lbl.textContent = st.label || (i + 1) + ')';
      var raw = document.createElement('span'); raw.className = 'raw'; raw.textContent = st.raw_text || '';
      li.appendChild(lbl); li.appendChild(raw);
      ol.appendChild(li);
    });
  }

  /* ── transport ─────────────────────────────────────────────────────── */

  function wireTransport() {
    var video = $('#ws-video');
    var fill = $('#ws-track-fill');

    video.addEventListener('timeupdate', function () {
      var d = video.duration || 0;
      fill.style.width = d ? ((video.currentTime / d) * 100).toFixed(2) + '%' : '0';
      $('#ws-time').textContent = mmss(video.currentTime) + ' / ' + mmss(d);
      var total = d ? Math.round(d * S.fps) : 0;
      var at = Math.round(video.currentTime * S.fps);
      $('#ws-frame').textContent = total ? ('frame ' + at + '/' + total) : 'frame —';
    });

    video.addEventListener('play', function () { $('#stat-viz').textContent = 'playing'; });
    video.addEventListener('pause', function () { $('#stat-viz').textContent = 'paused'; });

    $('#ws-play').addEventListener('click', function () {
      if (video.paused) video.play(); else video.pause();
    });
    $('#ws-restart').addEventListener('click', function () {
      video.currentTime = 0;
      video.play();
    });
    $('#ws-track').addEventListener('click', function (e) {
      if (!video.duration) return;
      var r = this.getBoundingClientRect();
      video.currentTime = ((e.clientX - r.left) / r.width) * video.duration;
    });
  }

  /* ── input wiring ──────────────────────────────────────────────────── */

  function wireInput() {
    var drop = $('#ws-drop');
    var input = $('#ws-file');

    $('#ws-browse').addEventListener('click', function (e) {
      e.stopPropagation();
      input.click();
    });
    drop.addEventListener('click', function () { input.click(); });
    drop.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
    input.addEventListener('change', function () {
      addFiles(input.files);
      input.value = '';
    });

    ['dragenter', 'dragover'].forEach(function (t) {
      drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (t) {
      drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.remove('over'); });
    });
    drop.addEventListener('drop', function (e) {
      if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
    });

    window.addEventListener('paste', function (e) {
      if (e.clipboardData && e.clipboardData.files && e.clipboardData.files.length) {
        addFiles(e.clipboardData.files);
      }
    });

    $('#ws-run').addEventListener('click', run);
    $('#ws-prompt').addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); run(); }
    });
  }

  /* ── go ────────────────────────────────────────────────────────────── */

  wireInput();
  wireTransport();
  renderFiles();
  loadHealth();
  loadSamples();
})();
