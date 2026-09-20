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




  /* ── files ─────────────────────────────────────────────────────────── */




  var NOTE_DEFAULT = 'Analysed step by step \u2014 never auto-graded';

  // A greyed-out button with no reason beside it reads as broken. Typed text
  // alone cannot be analysed: extract.py takes image bytes, and with none it
  // falls through to a bundled sample of somebody else's work. So say what is
  // missing rather than refusing in silence.


  /* ── chat boxes ────────────────────────────────────────────────────────
   *
   * One box each for the problem and for the work. Both take typing, dropped
   * or pasted images, a file picker, dictation and the camera, so neither has
   * a separate dropzone any more.
   */

  var Rec = window.SpeechRecognition || window.webkitSpeechRecognition;

  function makeChat(root, opts) {
    var text = root.querySelector('.chat-text');
    var atts = root.querySelector('.chat-atts');
    var file = root.querySelector('.chat-file');
    // The pill's circle sends; the work box also has Run analysis under the
    // boxes. Both drive the same box, so both are kept in step.
    var sends = [].slice.call(root.querySelectorAll('.chat-send'));
    if (opts.send && $(opts.send)) sends.push($(opts.send));
    var send = sends[0];   // the work box's only send lives outside the pill
    var box = { root: root, text: text, files: [], listening: false };

    function render() {
      atts.textContent = '';
      box.files.forEach(function (f, i) {
        var li = document.createElement('li');
        li.className = 'chat-att';
        if (/^image\//.test(f.type)) {
          var im = document.createElement('img');
          im.src = URL.createObjectURL(f);
          im.alt = f.name || 'attachment';
          im.addEventListener('load', function () { URL.revokeObjectURL(im.src); });
          li.appendChild(im);
        } else {
          var tag = document.createElement('span');
          tag.className = 'chat-att-kind';
          tag.textContent = (f.name || '').split('.').pop().slice(0, 4).toUpperCase();
          li.appendChild(tag);
        }
        var x = document.createElement('button');
        x.type = 'button'; x.className = 'chat-att-x';
        x.setAttribute('aria-label', 'Remove ' + (f.name || 'attachment'));
        x.textContent = '\u00d7';
        x.addEventListener('click', function () { box.files.splice(i, 1); render(); sync(); });
        li.appendChild(x);
        atts.appendChild(li);
      });
      atts.hidden = !box.files.length;
      pdfNotice();
    }

    function add(list) {
      var n = 0;
      Array.prototype.forEach.call(list || [], function (f) {
        if (!f) return;
        // PDFs are rasterised to page images, since the extractor reads images.
        if (global.NoemaPdf && global.NoemaPdf.isPdf(f)) {
          toast('Reading ' + (f.name || 'the PDF') + '\u2026');
          global.NoemaPdf.toImages(f).then(function (res) {
            res.files.forEach(function (pg) { box.files.push(pg); });
            render(); sync();
            toast('Added ' + res.files.length + ' page' + (res.files.length > 1 ? 's' : '') + '.');
          }).catch(function (err) {
            toast('Could not read that PDF: ' + (err && err.message ? err.message : err));
          });
          n++; return;
        }
        if (!/^image\//.test(f.type) && !/\.(hei[cf])$/i.test(f.name || '')) return;
        box.files.push(f); n++;
      });
      if (n) { render(); sync(); }
    }
    box.add = add;

    function sync() {
      var has = box.files.length > 0 || text.value.trim().length > 0;
      sends.forEach(function (b) { b.disabled = S.busy || !has; });
      if (opts.onSync) opts.onSync(box);
    }
    box.sync = sync;

    box.clear = function () { box.files = []; text.value = ''; render(); sync(); };

    text.addEventListener('input', sync);
    text.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.altKey) {
        // Enter sends, Shift+Enter makes a new line -- the composer convention.
        e.preventDefault();
        if (!send.disabled) opts.onSend(box);
      }
    });
    sends.forEach(function (b) { b.addEventListener('click', function () { if (!b.disabled) opts.onSend(box); }); });

    file.addEventListener('change', function () { add(file.files); file.value = ''; });

    root.addEventListener('paste', function (e) {
      if (e.clipboardData && e.clipboardData.files && e.clipboardData.files.length) {
        e.preventDefault(); add(e.clipboardData.files);
      }
    });

    var depth = 0;
    root.addEventListener('dragenter', function (e) { e.preventDefault(); depth++; root.classList.add('over'); });
    root.addEventListener('dragover', function (e) { e.preventDefault(); });
    root.addEventListener('dragleave', function (e) { e.preventDefault(); if (--depth <= 0) root.classList.remove('over'); });
    root.addEventListener('drop', function (e) {
      e.preventDefault(); depth = 0; root.classList.remove('over');
      if (e.dataTransfer && e.dataTransfer.files) add(e.dataTransfer.files);
    });

    root.querySelector('[data-act="attach"]').addEventListener('click', function () { file.click(); });

    // grow the field with its content, like a chat composer
    function grow() { text.style.height = 'auto'; text.style.height = Math.min(text.scrollHeight, 150) + 'px'; }
    text.addEventListener('input', grow); grow();
    root.querySelector('[data-act="camera"]').addEventListener('click', function () {
      if (global.__noemaOpenCamera) global.__noemaOpenCamera(root.dataset.dest);
      else toast('The camera is not available in this browser.');
    });

    var voiceBtn = root.querySelector('[data-act="voice"]');
    if (!Rec) {
      voiceBtn.disabled = true;
      voiceBtn.title = 'Dictation needs Chrome or Edge';
    } else {
      var rec = new Rec(); rec.continuous = true; rec.interimResults = true; rec.lang = 'en-US';
      var base = '';
      rec.addEventListener('result', function (e) {
        var fin = '', mid = '';
        for (var i = e.resultIndex; i < e.results.length; i++) {
          if (e.results[i].isFinal) fin += e.results[i][0].transcript;
          else mid += e.results[i][0].transcript;
        }
        if (fin) base = (base ? base.replace(/\s*$/, ' ') : '') + fin.trim();
        text.value = base + (mid ? (base ? ' ' : '') + mid : '');
        sync();
      });
      rec.addEventListener('error', function (e) {
        stopVoice();
        toast(e.error === 'not-allowed' ? 'Microphone access was refused.' : 'Dictation stopped: ' + e.error);
      });
      rec.addEventListener('end', function () { if (box.listening) { try { rec.start(); } catch (_) { stopVoice(); } } });

      function stopVoice() { box.listening = false; try { rec.stop(); } catch (_) {} voiceBtn.classList.remove('listening'); }
      voiceBtn.addEventListener('click', function () {
        if (box.listening) return stopVoice();
        base = text.value.trim();
        box.listening = true;
        try { rec.start(); } catch (_) {}
        voiceBtn.classList.add('listening');
      });
    }

    function pdfNotice() { $('#ws-notice').hidden = true; }

    render(); sync();
    return box;
  }


  /* ── the two boxes ─────────────────────────────────────────────────── */

  var problemBox = null;
  var workBox = null;


  function wireChats() {
    workBox = makeChat($('#chat-work'), {
      allowPdf: true,
      send: '#ws-run',
      onSend: function () { run(); },
      onSync: function (box) {
        var note = $('#composer-note');
        var has = box.files.length || box.text.value.trim();
        note.textContent = has
          ? 'Analysed step by step \u2014 never auto-graded'
          : (S.problem ? 'Now add the work you have so far \u2014 a photo, or typed one step per line.'
                       : 'Pick the problem you are stuck on first.');
      },
    });
  }

  /* ── which problem ─────────────────────────────────────────────────────
   * Step 1 collected them; this asks which one is the sticking point. A page
   * the student flagged as holding several problems says so, because we
   * cannot split one apart for them.
   */
  function wirePick() {
    var Store = global.NoemaStore;
    if (!Store) return;

    Store.loadProblems().then(function (list) {
      var ul = $('#pick-list');
      if (!list.length) {
        $('#pick-empty').hidden = false;
        $('#pick-title').textContent = 'No problem yet';
        return;
      }
      if (list.length === 1 && !list[0].multi) {
        $('#pick-title').textContent = 'The problem you are working on';
      }

      list.forEach(function (p, i) {
        var li = document.createElement('li');
        li.className = 'pick-item';

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'pick-btn';

        if (p.kind === 'image' && p.file) {
          var im = document.createElement('img');
          im.src = URL.createObjectURL(p.file);
          im.alt = '';
          btn.appendChild(im);
        }
        var cap = document.createElement('span');
        cap.className = 'pick-cap';
        cap.textContent = p.kind === 'text' ? p.text : ('Problem ' + (i + 1));
        btn.appendChild(cap);

        if (p.multi) {
          var flag = document.createElement('span');
          flag.className = 'pick-flag';
          flag.textContent = 'holds several \u2014 say which in your work';
          btn.appendChild(flag);
        }

        btn.addEventListener('click', function () { choose(p, li); });
        li.appendChild(btn);
        ul.appendChild(li);
      });

      // One unambiguous problem needs no asking.
      if (list.length === 1 && !list[0].multi) {
        choose(list[0], ul.firstChild);
      } else {
        var prev = Store.loadChoice();
        if (prev) {
          var found = list.filter(function (p) { return p.id === prev; })[0];
          if (found) choose(found, ul.children[list.indexOf(found)]);
        }
      }
    });

    function choose(p, li) {
      S.problem = { text: p.text || null, files: p.file ? [p.file] : [] };
      global.NoemaStore.saveChoice(p.id);
      [].forEach.call($('#pick-list').children, function (el) { el.classList.remove('is-on'); });
      if (li) li.classList.add('is-on');
      if (workBox) workBox.sync();
    }
  }

  // the rest of the app still asks these two questions
  function syncRun() { if (workBox) workBox.sync(); }
  function currentWorkFiles() { return workBox ? workBox.files : []; }

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
    var note = workBox ? workBox.text.value.trim() : '';
    S.files = currentWorkFiles();

    // No photo, but something typed: parse it into the extraction schema and
    // use the API's no-vision path. Nothing is sent until it parses.
    if (!S.files.length) {
      if (!note) return;
      var T = global.NoemaTyped;

      // A plain-English question with no work attached. Do not analyse and do
      // not render anything -- work out which piece of work would answer it
      // and ask for that. The upload that follows is what makes the video.
      if (T.isQuestion(note)) {
        log('you', note, true);
        workBox.clear();
        var want = T.whatToAsk(note, S.problem && S.problem.text);
        if (want.outOfScope) {
          log('noema', 'I cannot help with ' + want.outOfScope + ' \u2014 there is no ' +
                       'calculus in this app, so there would be nothing real behind the ' +
                       'animation. I cover linear algebra: products and their order, ' +
                       'inverses and determinants, eigenvectors, projections, and systems.');
        } else {
          log('noema', 'Upload ' + want.ask + ' \u2014 drop a photo in, or type it one ' +
                       'step per line \u2014 and I will show you where it breaks.');
        }
        return;
      }

      var parsed = T.parse(note);
      if (parsed.ok && !parsed.problem && S.problem && S.problem.text) {
        parsed.problem = S.problem.text;      // the one kept above, not re-typed
      }
      if (!parsed.ok) {
        log('you', note, true);
        log('noema', parsed.error);
        workBox.clear();
        toast(parsed.error);
        return;
      }
      log('you', note, true);
      parsed.notes.forEach(function (n) { log('noema', n); });
      log('noema', 'Read ' + parsed.steps.length + ' step' +
                   (parsed.steps.length > 1 ? 's' : '') + ' from what you typed. Checking them\u2026');
      workBox.clear();
      syncRun();
      start(api('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(global.NoemaTyped.toPayload(parsed)),
      }));
      return;
    }

    var fd = new FormData();
    (S.problem && S.problem.files ? S.problem.files : []).forEach(function (f) {
      // The problem pages go first: extract.py reads the problem off the page.
      fd.append('images', f, f.name || 'problem.jpg');
    });
    S.files.forEach(function (f) { fd.append('images', f, f.name || 'page.jpg'); });
    if (note) fd.append('problem_note', note);
    if (S.problem && S.problem.text && !(S.problem.files && S.problem.files.length)) {
      log('noema', 'Noting your typed problem for reference. It cannot be sent with a ' +
                   'photo \u2014 the upload route has no field for it \u2014 so the check ' +
                   'runs against what is on the page.');
    }

    if (note) {
      log('you', note, true);
      workBox.clear();
    }
    log('noema', 'Reading ' + S.files.length + ' page' + (S.files.length > 1 ? 's' : '') + '…');

    start(api('/api/analyze', { method: 'POST', body: fd }));
  }

  function runFixture(name, title) {
    if (S.busy) return;
    S.files = [];
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
    showSlide(3);           // every scrap of feedback below paints on slide 3
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

  /* ── the work box is a dropzone, the way step 1's is ───────────────── */

  /* Step 1 opens the picker when you click anywhere in the dashed box, and
     students arriving at step 2 tried the same thing and got nothing. The
     buttons inside speak for themselves -- makeChat already binds them -- so
     a click that lands on one is left alone rather than opening a second
     file dialog on top of the first. */
  function wireWorkZone() {
    var zone = $('#work-add');
    var file = $('#chat-work .chat-file');
    if (!zone || !file) return;

    zone.addEventListener('click', function (e) {
      if (e.target.closest('.add-actions')) return;
      file.click();
    });
    zone.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); file.click(); }
    });
  }

  /* ── the two slides ────────────────────────────────────────────────── */

  /* Steps 2 and 3 are two sections of one document, not two pages. A render
     runs for tens of seconds behind a poll timer, and navigating to a third
     HTML file would throw both away mid-flight. Hiding a section leaves every
     #viz-* node queryable, so nothing below ever learns which slide is up. */
  function showSlide(n) {
    $('#slide-work').hidden = n !== 2;
    $('#slide-animation').hidden = n !== 3;

    [].forEach.call(document.querySelectorAll('.progress li'), function (li) {
      var here = li.getAttribute('data-step') === String(n);
      li.classList.toggle('is-here', here);
      if (here) li.setAttribute('aria-current', 'step');
      else li.removeAttribute('aria-current');
    });

    global.scrollTo(0, 0);
  }

  function wireSlides() {
    $('#go-animation').addEventListener('click', function () { showSlide(3); });
    $('#back-to-work').addEventListener('click', function () { showSlide(2); });
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

    // The button paused correctly but always showed a play triangle, so it
    // read as doing nothing and the next click just resumed. Drive the icon
    // off the video's own events, not off the click, so it stays honest when
    // playback ends or loops on its own.
    var PLAY_D = 'M8 5l11 7-11 7z';
    var PAUSE_D = 'M8 5h3v14H8zM13 5h3v14h-3z';
    function paintPlayButton() {
      var btn = $('#ws-play');
      var showPause = !video.paused && !video.ended;
      btn.querySelector('path').setAttribute('d', showPause ? PAUSE_D : PLAY_D);
      btn.setAttribute('aria-label', showPause ? 'Pause' : 'Play');
      btn.title = showPause ? 'Pause' : 'Play';
    }
    ['play', 'pause', 'ended', 'emptied'].forEach(function (e) {
      video.addEventListener(e, paintPlayButton);
    });
    paintPlayButton();

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



  /* ── voice: Web Speech API, the same one the classic flow dictates with ─ */


  /* ── camera: getUserMedia -> canvas -> a File in the same queue ───────── */

  var camDest = 'work';

  /* One camera, shared by both boxes. The shot lands in whichever box opened
     it, which is why the destination is passed in rather than assumed. */
  function wireCamera() {
    var panel = $('#cam');
    var video = $('#cam-video');
    var stream = null;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      global.__noemaOpenCamera = function () { toast('This browser has no camera API.'); };
      return;
    }

    function close() {
      if (stream) { stream.getTracks().forEach(function (tr) { tr.stop(); }); stream = null; }
      video.srcObject = null;
      panel.hidden = true;
      camDest = 'work';
    }

    function open() {
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
        .then(function (st) {
          stream = st; video.srcObject = st; video.play(); panel.hidden = false;
        })
        .catch(function (err) {
          toast(err && err.name === 'NotAllowedError' ? 'Camera access was refused.' : 'No camera available.');
          close();
        });
    }

    global.__noemaOpenCamera = function (dest) {
      camDest = dest || 'work';
      if (stream) close(); else open();
    };

    $('#cam-stop').addEventListener('click', close);
    $('#cam-shot').addEventListener('click', function () {
      if (!stream || !video.videoWidth) return;
      var c = document.createElement('canvas');
      c.width = video.videoWidth; c.height = video.videoHeight;
      c.getContext('2d').drawImage(video, 0, 0);
      var dest = camDest;
      c.toBlob(function (blob) {
        if (!blob) return;
        var name = 'camera-' + new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19) + '.jpg';
        var shot = new File([blob], name, { type: 'image/jpeg' });
        var box = dest === 'problem' ? problemBox : workBox;
        if (box) box.add([shot]);
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


  /* ── go ────────────────────────────────────────────────────────────── */

  wireSlides();
  wireWorkZone();
  wireTransport();
  wireCamera();
  wireChats();
  wirePick();
  loadHealth();
})(window);
