/* Noema — step 1: collect the problem, or the problem set.
 *
 * No analysis happens here. This page's whole job is to end up with a list of
 * problems in the store, so step 2 can ask which one is the sticking point and
 * take the student's work for it.
 *
 * A problem is {id, kind:'image'|'text', title, text, file, multi}. `multi`
 * was a checkbox asking whether a page held more than one problem; the box is
 * gone and nothing sets it now, so it persists as false. The field stays in
 * the shape because step 2 still reads it -- with it false, a lone problem is
 * auto-selected there instead of being offered as a choice of one.
 */
(function (global) {
  'use strict';

  var $ = function (s) { return document.querySelector(s); };
  var Store = global.NoemaStore;
  var items = [];
  var seq = 0;

  /* Landing on step 1 is starting over, whichever screen you came from: the
     list opens empty and the store is emptied with it, so nothing from the
     last problem carries into the next one. */
  var cleared = Store ? Store.clear().catch(function () {}) : Promise.resolve();

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

  /* Every write waits on the opening wipe. Both are their own IndexedDB
     transaction and each does its own open(), so their order is decided by
     which open() resolves first -- not by which was called first. A paste
     landing in the first moments of the page could otherwise be saved and
     then wiped, losing an upload with no error anywhere. */
  function persist() {
    if (!Store) return;
    var snapshot = items.map(function (p) {
      return { id: p.id, kind: p.kind, title: p.title, text: p.text || null,
               file: p.file || null, multi: !!p.multi };
    });
    cleared.then(function () { return Store.saveProblems(snapshot); })
           .catch(function () { toast('Could not save these locally; they will not carry to the next step.'); });
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

      body.appendChild(h);

      // A photo is identified by its thumbnail, not by whatever the camera
      // roll happened to call the file. Only a typed problem gets a second
      // line, and there the line is the problem itself.
      if (p.kind === 'text') {
        var sub = document.createElement('p');
        sub.className = 'prob-sub';
        sub.textContent = p.text.slice(0, 120) + (p.text.length > 120 ? '\u2026' : '');
        body.appendChild(sub);
      }

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
    $('#go-next').classList.toggle('is-off', items.length === 0);
  }

  /* ── adding ────────────────────────────────────────────────────────── */

  function addFiles(list) {
    var n = 0;
    Array.prototype.forEach.call(list || [], function (f) {
      if (!f) return;
      // A PDF is rasterised here and added a page at a time, because the
      // extractor only reads images. See pdfpages.js.
      if (global.NoemaPdf && global.NoemaPdf.isPdf(f)) { addPdf(f); n++; return; }
      if (!/^image\//.test(f.type) && !/\.(hei[cf])$/i.test(f.name || '')) return;
      add({ kind: 'image', file: f, title: f.name || 'photo' });
      n++;
    });
    if (!n && list && list.length) toast('That file type cannot be read here.');
  }

  /* Adding a problem says nothing. The problem appearing in the list under
     the dropzone is the receipt, and it is a better one than a sentence that
     covers it up -- the old summary reported what was found, then told the
     student to tick a box that no longer exists.

     Two things stay, because both are cases where saying nothing would hide
     something from the student: a PDF that could not be read at all, and one
     longer than the page cap, whose later pages are simply not there. */
  function addPdf(file) {
    global.NoemaPdf.toImages(file).then(function (res) {
      (res.items || []).forEach(function (it) {
        add({ kind: 'image', file: it.file, title: it.label || it.file.name });
      });
      if (res.total > res.used) {
        toast('Only the first ' + res.used + ' of ' + res.total + ' pages were read.');
      }
    }).catch(function (err) {
      toast('Could not read that PDF: ' + (err && err.message ? err.message : err));
    });
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
      e.stopPropagation();          // it lives inside the dropzone
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

  render();
})(window);
