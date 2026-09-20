/* Noema — step 1: collect the problem, or the problem set.
 *
 * No analysis happens here. This page's whole job is to end up with a list of
 * problems in the store, so step 2 can ask which one is the sticking point and
 * take the student's work for it.
 *
 * A problem is {id, kind:'image'|'text', title, text, file, multi}. `multi` is
 * the student saying a page holds more than one problem -- we cannot split a
 * page apart, so we record the claim and let step 2 ask.
 */
(function (global) {
  'use strict';

  var $ = function (s) { return document.querySelector(s); };
  var Store = global.NoemaStore;
  var items = [];
  var seq = 0;

  /* ── toast ─────────────────────────────────────────────────────────── */
  var toastTimer = null;
  function toast(msg) {
    var el = $('#ws-toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 5000);
  }

  /* ── the list ──────────────────────────────────────────────────────── */

  function add(entry) {
    entry.id = 'p' + (++seq);
    items.push(entry);
    render();
    persist();
  }

  function remove(id) {
    items = items.filter(function (p) { return p.id !== id; });
    render();
    persist();
  }

  function persist() {
    if (!Store) return;
    Store.saveProblems(items.map(function (p) {
      return { id: p.id, kind: p.kind, title: p.title, text: p.text || null,
               file: p.file || null, multi: !!p.multi };
    })).catch(function () { toast('Could not save these locally; they will not carry to the next step.'); });
  }

  function render() {
    var ul = $('#probs');
    ul.textContent = '';

    items.forEach(function (p, i) {
      var li = document.createElement('li');
      li.className = 'prob';

      var thumb = document.createElement('div');
      thumb.className = 'prob-thumb';
      if (p.kind === 'image') {
        var im = document.createElement('img');
        im.src = URL.createObjectURL(p.file);
        im.alt = '';
        im.addEventListener('load', function () { URL.revokeObjectURL(im.src); });
        thumb.appendChild(im);
      } else {
        thumb.classList.add('is-text');
        thumb.textContent = '“”';
      }

      var body = document.createElement('div');
      body.className = 'prob-body';

      var h = document.createElement('p');
      h.className = 'prob-title';
      h.textContent = 'Problem ' + (i + 1);

      var sub = document.createElement('p');
      sub.className = 'prob-sub';
      sub.textContent = p.kind === 'text'
        ? p.text.slice(0, 120) + (p.text.length > 120 ? '…' : '')
        : (p.file.name || 'photo');

      // We cannot split a page into separate problems, so ask rather than guess.
      var lab = document.createElement('label');
      lab.className = 'prob-multi';
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !!p.multi;
      cb.addEventListener('change', function () { p.multi = cb.checked; persist(); note(); });
      lab.appendChild(cb);
      lab.appendChild(document.createTextNode(' This holds more than one problem'));

      body.appendChild(h);
      body.appendChild(sub);
      body.appendChild(lab);

      var x = document.createElement('button');
      x.type = 'button';
      x.className = 'prob-x';
      x.setAttribute('aria-label', 'Remove problem ' + (i + 1));
      x.textContent = '×';
      x.addEventListener('click', function () { remove(p.id); });

      li.appendChild(thumb);
      li.appendChild(body);
      li.appendChild(x);
      ul.appendChild(li);
    });

    $('#clear-all').hidden = items.length === 0;
    note();
  }

  function note() {
    var n = items.length;
    var multi = items.filter(function (p) { return p.multi; }).length;
    var el = $('#step-note');
    var next = $('#go-next');

    if (!n) {
      el.textContent = 'Nothing added yet.';
      next.classList.add('is-off');
      return;
    }
    next.classList.remove('is-off');

    if (n === 1 && !multi) {
      el.textContent = 'One problem ready. Next you’ll add the work you have so far.';
    } else if (n === 1 && multi) {
      el.textContent = 'One page holding several problems — you’ll pick which one next.';
    } else {
      el.textContent = n + ' problems ready' +
        (multi ? ' (' + multi + ' holding more than one)' : '') +
        ' — you’ll pick which one next.';
    }
  }

  /* ── adding ────────────────────────────────────────────────────────── */

  function addFiles(list) {
    var n = 0;
    Array.prototype.forEach.call(list || [], function (f) {
      if (!f) return;
      if (/\.pdf$/i.test(f.name || '') || f.type === 'application/pdf') {
        toast('PDFs are not readable yet — export the page as PNG or JPEG.');
        return;
      }
      if (!/^image\//.test(f.type) && !/\.(hei[cf])$/i.test(f.name || '')) return;
      add({ kind: 'image', file: f, title: f.name || 'photo' });
      n++;
    });
    if (!n && list && list.length) toast('That file type cannot be read here.');
  }

  /* ── wiring ────────────────────────────────────────────────────────── */

  function wireAdd() {
    var zone = $('#add');
    var file = $('#add-file');

    function pick(e) { if (e) e.stopPropagation(); file.click(); }
    $('#add-browse').addEventListener('click', pick);
    zone.addEventListener('click', function () { file.click(); });
    zone.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); file.click(); }
    });
    file.addEventListener('change', function () { addFiles(file.files); file.value = ''; });

    var depth = 0;
    zone.addEventListener('dragenter', function (e) { e.preventDefault(); depth++; zone.classList.add('over'); });
    zone.addEventListener('dragover', function (e) { e.preventDefault(); });
    zone.addEventListener('dragleave', function (e) { e.preventDefault(); if (--depth <= 0) zone.classList.remove('over'); });
    zone.addEventListener('drop', function (e) {
      e.preventDefault(); depth = 0; zone.classList.remove('over');
      if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
    });

    window.addEventListener('paste', function (e) {
      if (e.clipboardData && e.clipboardData.files && e.clipboardData.files.length) {
        addFiles(e.clipboardData.files);
      }
    });

    $('#clear-all').addEventListener('click', function () {
      items = [];
      render();
      if (Store) Store.clear();
    });
  }

  function wireTyper() {
    var panel = $('#typer');
    var text = $('#typer-text');
    var addBtn = $('#typer-add');

    function sync() { addBtn.disabled = !text.value.trim(); }
    text.addEventListener('input', sync);

    $('#add-type').addEventListener('click', function (e) {
      e.stopPropagation();
      panel.hidden = false;
      $('#add').hidden = true;
      text.focus();
    });
    function close() { panel.hidden = true; $('#add').hidden = false; text.value = ''; sync(); }
    $('#typer-cancel').addEventListener('click', close);
    addBtn.addEventListener('click', function () {
      var v = text.value.trim();
      if (!v) return;
      add({ kind: 'text', text: v, title: v.slice(0, 40) });
      close();
    });
    text.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); addBtn.click(); }
    });

    // dictation, same API the rest of the app uses
    var Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
    var vb = $('#typer-voice');
    if (!Rec) { vb.disabled = true; vb.title = 'Dictation needs Chrome or Edge'; return; }
    var rec = new Rec(); rec.continuous = true; rec.interimResults = true; rec.lang = 'en-US';
    var base = '', on = false;
    rec.addEventListener('result', function (e) {
      var fin = '', mid = '';
      for (var i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) fin += e.results[i][0].transcript; else mid += e.results[i][0].transcript;
      }
      if (fin) base = (base ? base.replace(/\s*$/, ' ') : '') + fin.trim();
      text.value = base + (mid ? (base ? ' ' : '') + mid : '');
      sync();
    });
    rec.addEventListener('error', function (e) {
      stop(); toast(e.error === 'not-allowed' ? 'Microphone access was refused.' : 'Dictation stopped: ' + e.error);
    });
    rec.addEventListener('end', function () { if (on) { try { rec.start(); } catch (_) { stop(); } } });
    function stop() { on = false; try { rec.stop(); } catch (_) {} vb.classList.remove('listening'); }
    vb.addEventListener('click', function () {
      if (on) return stop();
      base = text.value.trim(); on = true;
      try { rec.start(); } catch (_) {}
      vb.classList.add('listening');
    });
  }

  function wireCamera() {
    var panel = $('#cam'), video = $('#cam-video'), stream = null;
    var btn = $('#add-camera');

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      btn.disabled = true; btn.title = 'This browser has no camera API.'; return;
    }
    function close() {
      if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
      video.srcObject = null; panel.hidden = true; $('#add').hidden = false;
    }
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (stream) return close();
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
        .then(function (st) {
          stream = st; video.srcObject = st; video.play();
          panel.hidden = false; $('#add').hidden = true;
        })
        .catch(function (err) {
          toast(err && err.name === 'NotAllowedError' ? 'Camera access was refused.' : 'No camera available.');
        });
    });
    $('#cam-stop').addEventListener('click', close);
    $('#cam-shot').addEventListener('click', function () {
      if (!stream || !video.videoWidth) return;
      var c = document.createElement('canvas');
      c.width = video.videoWidth; c.height = video.videoHeight;
      c.getContext('2d').drawImage(video, 0, 0);
      c.toBlob(function (blob) {
        if (!blob) return;
        var name = 'problem-' + new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19) + '.jpg';
        addFiles([new File([blob], name, { type: 'image/jpeg' })]);
        close();
      }, 'image/jpeg', 0.92);
    });
  }

  function wireNext() {
    $('#go-next').addEventListener('click', function (e) {
      if (!items.length) {
        e.preventDefault();
        toast('Add the problem you are stuck on first.');
      }
    });
  }

  /* ── go ────────────────────────────────────────────────────────────── */

  wireAdd();
  wireTyper();
  wireCamera();
  wireNext();

  // Anything added earlier in this session comes back, so a step back does not
  // lose the upload.
  if (Store) {
    Store.loadProblems().then(function (saved) {
      if (!saved.length) return render();
      items = saved.filter(function (p) { return p.kind === 'text' || p.file; });
      seq = items.length;
      render();
    });
  } else {
    render();
  }
})(window);
