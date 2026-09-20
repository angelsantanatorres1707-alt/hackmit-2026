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
(function (global) {
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

  /* ── render quality ────────────────────────────────────────────────── */

  var FPS_BY_QUALITY = {
    low_quality: 15, medium_quality: 30, high_quality: 60,
    production_quality: 60, fourk_quality: 60,
  };


  // The only thing still read from health is the frame rate, which the
  // transport's frame counter needs; guessing 30 would be wrong at other
  // render qualities.
  function loadHealth() {
    api('/api/health').then(function (h) {
      S.fps = FPS_BY_QUALITY[h.render_quality] || 30;
      // The quality/fps badge was removed by request -- render settings are our
      // business, not the viewer's. S.fps is still needed by the frame counter.
    }).catch(function () { /* S.fps keeps its default; nothing else depends on it */ });
  }

  // The sample chips were removed: each one was labelled with the mistake it
  // contained ("multiplication order reversed"), so the picker gave away the
  // answer before the animation had a chance to show it. runFixture() is kept
  // -- /api/fixtures still serves them, so a sample can be triggered from the
  // console or wired to a single unlabelled button if one is wanted back.


  /* ── the problem ───────────────────────────────────────────────────────
   *
   * Kept on screen once set, so it can be referred back to while working.
   * Where it actually reaches the analysis:
   *   typed work  -> the statement rides along in problem.statement, which
   *                  verify.py reads.
   *   photo work  -> a problem IMAGE is sent alongside the work image and
   *                  extract.py reads the problem off the page. A problem
   *                  TYPED here has nowhere to go on that path: the multipart
   *                  route has no field for it. Said out loud rather than
   *                  quietly dropped.
   */

  function setProblem(next) {
    if (S.problem && S.problem.url) URL.revokeObjectURL(S.problem.url);
    S.problem = next;
    renderProblem();
    syncRun();
  }

  function renderProblem() {
    var input = $('#prob-input');
    var shown = $('#prob-shown');
    var img = $('#prob-img');
    var stmt = $('#prob-statement');

    if (!S.problem) {
      input.hidden = false;
      shown.hidden = true;
      $('#prob-change').hidden = true;
      return;
    }

    input.hidden = true;
    shown.hidden = false;
    $('#prob-change').hidden = false;

    if (S.problem.url) { img.src = S.problem.url; img.hidden = false; }
    else { img.removeAttribute('src'); img.hidden = true; }

    if (S.problem.text) { stmt.textContent = S.problem.text; stmt.hidden = false; }
    else { stmt.textContent = ''; stmt.hidden = true; }
  }

  function wireProblem() {
    var file = $('#prob-file');
    var text = $('#prob-text');
    var save = $('#prob-save');

    function canSave() { save.disabled = !text.value.trim(); }
    text.addEventListener('input', canSave);

    $('#prob-browse').addEventListener('click', function () { file.click(); });
    file.addEventListener('change', function () {
      var f = file.files && file.files[0];
      file.value = '';
      if (!f) return;
      if (isPdf(f)) { toast('PDFs are not readable yet \u2014 upload a PNG or JPEG of the problem.'); return; }
      setProblem({ file: f, url: URL.createObjectURL(f), text: text.value.trim() || null });
    });

    save.addEventListener('click', function () {
      var v = text.value.trim();
      if (v) setProblem({ text: v });
    });

    $('#prob-camera').addEventListener('click', function () { openCamera('problem'); });

    $('#prob-change').addEventListener('click', function () {
      var keep = (S.problem && S.problem.text) || '';
      setProblem(null);
      text.value = keep;
      canSave();
    });

    renderProblem();
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

    syncRun();
  }


  var NOTE_DEFAULT = 'Analysed step by step \u2014 never auto-graded';

  // A greyed-out button with no reason beside it reads as broken. Typed text
  // alone cannot be analysed: extract.py takes image bytes, and with none it
  // falls through to a bundled sample of somebody else's work. So say what is
  // missing rather than refusing in silence.
  function syncRun() {
    var hasFiles = S.files.length > 0;
    var hasText = $('#ws-prompt').value.trim().length > 0;
    $('#ws-run').disabled = S.busy || (!hasFiles && !hasText);

    var note = $('#composer-note');
    if (!hasFiles && !hasText) {
      note.textContent = S.problem
        ? 'Problem saved. Now add your work \u2014 a photo, or typed one step per line.'
        : 'Drop a photo above, or type your working one step per line.';
      note.classList.remove('is-warn');
    } else {
      note.textContent = NOTE_DEFAULT;
      note.classList.remove('is-warn');
    }
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
    if (S.busy) return;
    var note = $('#ws-prompt').value.trim();

    // No photo, but something typed: parse it into the extraction schema and
    // use the API's no-vision path. Nothing is sent until it parses.
    if (!S.files.length) {
      if (!note) return;
      var parsed = global.NoemaTyped.parse(note);
      if (parsed.ok && !parsed.problem && S.problem && S.problem.text) {
        parsed.problem = S.problem.text;      // the one kept above, not re-typed
      }
      if (!parsed.ok) {
        log('you', note, true);
        log('noema', parsed.error);
        $('#ws-prompt').value = '';
        syncRun();
        toast(parsed.error);
        return;
      }
      log('you', note, true);
      parsed.notes.forEach(function (n) { log('noema', n); });
      log('noema', 'Read ' + parsed.steps.length + ' step' +
                   (parsed.steps.length > 1 ? 's' : '') + ' from what you typed. Checking them\u2026');
      $('#ws-prompt').value = '';
      syncRun();
      start(api('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(global.NoemaTyped.toPayload(parsed)),
      }));
      return;
    }

    var fd = new FormData();
    if (S.problem && S.problem.file) {
      // The problem page goes first: extract.py reads the problem off the page.
      fd.append('images', S.problem.file, S.problem.file.name || 'problem.jpg');
    }
    S.files.forEach(function (f) { fd.append('images', f, f.name || 'page.jpg'); });
    if (note) fd.append('problem_note', note);
    if (S.problem && S.problem.text && !S.problem.file) {
      log('noema', 'Noting your typed problem for reference. It cannot be sent with a ' +
                   'photo \u2014 the upload route has no field for it \u2014 so the check ' +
                   'runs against what is on the page.');
    }

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

    renderWarnings(job);
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
      $('#ws-play').disabled = false;
      $('#ws-restart').disabled = false;
      var p = video.play();
      if (p && p.catch) p.catch(function () { toast('Press play to start the animation.'); });
      if (!applyJob._said) { log('noema', 'Animation ready. The hint points at the step — no correction.'); applyJob._said = true; }
      return;
    }

    if (job.video_status === 'failed' || job.video_status === 'not_needed') {
      showViz('failed');
      $('#viz-failed-why').textContent = job.video_status === 'not_needed'
        ? 'Nothing to animate for this one.'
        : firstLine(job.video_error || 'the renderer did not produce a file');
      $('#ws-play').disabled = true;
      $('#ws-restart').disabled = true;
      return;
    }

    showViz('busy');
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


  /* The backend tells us when it handed back a bundled sample instead of the
     photo that was uploaded. app.js shows that; this page used to drop it on
     the floor, so someone uploading their own work was shown a stranger's with
     nothing on screen to say so. That is the one failure extract.py calls the
     worst thing this app can do quietly. */
  function renderWarnings(job) {
    var box = $('#ws-warnings');
    box.textContent = '';

    var rows = (job.warnings || []).slice();
    if (job.photo_substituted && !rows.length) {
      rows.push('Your photo was not read. What follows is a bundled sample, not your work.');
    }
    if (!rows.length) { box.hidden = true; return; }

    box.hidden = false;
    rows.forEach(function (w) {
      var el = document.createElement('div');
      // A substitution is not a footnote: it means nothing on screen is theirs.
      el.className = 'ws-warn' + (job.photo_substituted ? ' is-loud' : '');
      el.textContent = w;
      box.appendChild(el);
    });
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
    });

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
    $('#ws-prompt').addEventListener('input', syncRun);
    $('#ws-prompt').addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        run();
      }
    });
  }


  /* ── voice: Web Speech API, the same one the classic flow dictates with ─ */

  function wireVoice() {
    var Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
    var btn = $('#mode-voice');

    if (!Rec) {
      btn.disabled = true;
      btn.title = 'Dictation uses the Web Speech API — Chrome or Edge. Typing works everywhere.';
      return;
    }

    var rec = new Rec();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = 'en-US';

    var base = '';
    var on = false;

    rec.addEventListener('result', function (e) {
      var fin = '', interim = '';
      for (var i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) fin += e.results[i][0].transcript;
        else interim += e.results[i][0].transcript;
      }
      if (fin) base = (base ? base.replace(/\s*$/, ' ') : '') + fin.trim();
      $('#ws-prompt').value = base + (interim ? (base ? ' ' : '') + interim : '');
    });
    rec.addEventListener('error', function (e) {
      stop();
      toast(e.error === 'not-allowed'
        ? 'Microphone access was refused.'
        : 'Dictation stopped: ' + e.error);
    });
    rec.addEventListener('end', function () { if (on) { try { rec.start(); } catch (_) { stop(); } } });

    function start() {
      base = $('#ws-prompt').value.trim();
      on = true;
      try { rec.start(); } catch (_) { /* already running */ }
      btn.classList.add('listening');
      setMode('voice');
    }
    function stop() {
      on = false;
      try { rec.stop(); } catch (_) {}
      btn.classList.remove('listening');
      setMode('text');
    }

    btn.addEventListener('click', function () { if (on) stop(); else start(); });
  }

  /* ── camera: getUserMedia -> canvas -> a File in the same queue ───────── */

  var camDest = 'work';

  function wireCamera() {
    var btn = $('#mode-camera');
    var panel = $('#cam');
    var video = $('#cam-video');
    var stream = null;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      btn.disabled = true;
      btn.title = 'This browser has no camera API.';
      return;
    }

    function close() {
      if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
      video.srcObject = null;
      panel.hidden = true;
      $('#ws-drop').hidden = false;
      setMode('text');
    }

    global.__noemaOpenCamera = function (dest) { camDest = dest || 'work'; if (!stream) open(); };

    function open() {
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
        .then(function (st) {
          stream = st;
          video.srcObject = st;
          video.play();
          panel.hidden = false;
          $('#ws-drop').hidden = true;
          setMode('camera');
        })
        .catch(function (err) {
          toast(err && err.name === 'NotAllowedError'
            ? 'Camera access was refused.'
            : 'No camera available.');
          setMode('text');
        });
    }

    btn.addEventListener('click', function () { camDest = 'work'; if (stream) close(); else open(); });
    $('#cam-stop').addEventListener('click', close);
    $('#cam-shot').addEventListener('click', function () {
      if (!stream || !video.videoWidth) return;
      var c = document.createElement('canvas');
      c.width = video.videoWidth;
      c.height = video.videoHeight;
      c.getContext('2d').drawImage(video, 0, 0);
      c.toBlob(function (blob) {
        if (!blob) return;
        var name = 'camera-' + new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19) + '.jpg';
        var shot = new File([blob], name, { type: 'image/jpeg' });
        if (camDest === 'problem') {
          setProblem({ file: shot, url: URL.createObjectURL(shot), text: $('#prob-text').value.trim() || null });
        } else {
          addFiles([shot]);
        }
        camDest = 'work';
        close();
      }, 'image/jpeg', 0.92);
    });
  }

  function setMode(m) {
    ['text', 'voice', 'camera'].forEach(function (k) {
      var b = $('#mode-' + k);
      b.classList.toggle('is-on', k === m);
      b.setAttribute('aria-selected', String(k === m));
    });
  }

  function openCamera(dest) {
    if (global.__noemaOpenCamera) global.__noemaOpenCamera(dest);
    else toast('The camera is not available in this browser.');
  }

  /* ── go ────────────────────────────────────────────────────────────── */

  wireInput();
  wireTransport();
  wireVoice();
  wireCamera();
  wireProblem();
  renderFiles();
  loadHealth();
})(window);
