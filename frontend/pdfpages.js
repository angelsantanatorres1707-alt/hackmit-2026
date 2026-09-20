/* Noema — PDF in, page images out.
 *
 * extract.py opens every upload with PIL and has no PDF path, so a PDF has
 * always come back as an extraction error. Rather than wait on the backend,
 * the pages are rasterised here and uploaded as images, which is what the
 * extractor already knows how to read.
 *
 * pdf.js is vendored under vendor/pdfjs (Apache-2.0) rather than pulled from a
 * CDN -- CLAUDE.md rules those out because venue wifi will fail. It is 1.7MB,
 * so it is imported only when a PDF actually turns up: someone uploading
 * photographs never pays for it.
 */
(function (global) {
  'use strict';

  var lib = null;
  var MAX_W = 1600;          // enough for handwriting, small enough to upload
  var MAX_PAGES = 20;

  function load() {
    if (lib) return Promise.resolve(lib);
    return import('./vendor/pdfjs/pdf.min.mjs').then(function (m) {
      m.GlobalWorkerOptions.workerSrc = 'vendor/pdfjs/pdf.worker.min.mjs';
      lib = m;
      return m;
    });
  }

  function isPdf(f) {
    return !!f && (f.type === 'application/pdf' || /\.pdf$/i.test(f.name || ''));
  }


  /* ── finding the problems on a page ──────────────────────────────────
   *
   * A typeset problem set numbers its problems at the left margin --
   * "Problem 1.", "3.", "(2)", "Exercise 4" -- and pdf.js gives every text run
   * with a position. So the markers can be found exactly rather than guessed
   * at, and the page image cropped between them.
   *
   * The left-margin test is what stops "...as shown in Problem 2" mid-sentence
   * from being read as the start of a problem.
   *
   * This only works when the PDF carries a text layer. A scan or a photo saved
   * as PDF has none, and there is nothing here to read -- that page stays whole
   * and the caller is told, rather than being handed a confident wrong split.
   */

  var MARKER = /^\s*(?:problem|exercise|question|prob|q)\s*\.?\s*(\d{1,2})\s*[.):]?\s*$/i;
  var NUM_ONLY = /^\s*\(?(\d{1,2})\s*[.)]\s*$/;

  function findMarkers(items) {
    var runs = items
      .map(function (i) { return { s: (i.str || '').trim(), x: i.transform[4], y: i.transform[5] }; })
      .filter(function (r) { return r.s; });
    if (!runs.length) return [];

    var left = Math.min.apply(null, runs.map(function (r) { return r.x; }));
    var out = [];
    runs.forEach(function (r) {
      var m = r.s.match(MARKER) || r.s.match(NUM_ONLY);
      if (!m) return;
      if (r.x > left + 14) return;              // must sit in the left margin
      out.push({ num: parseInt(m[1], 10), text: r.s.replace(/\s+$/, ''), y: r.y });
    });

    // Top of the page downwards. PDF y grows upwards, so that is descending y.
    out.sort(function (a, b) { return b.y - a.y; });

    // Drop repeats of the same number (a marker split across runs).
    var seen = {}, clean = [];
    out.forEach(function (m) {
      if (seen[m.num]) return;
      seen[m.num] = true;
      clean.push(m);
    });
    return clean;
  }

  function cropToFile(canvas, top, bottom, name) {
    var h = Math.max(1, Math.round(bottom - top));
    var c = document.createElement('canvas');
    c.width = canvas.width;
    c.height = h;
    c.getContext('2d').drawImage(canvas, 0, Math.round(top), canvas.width, h, 0, 0, canvas.width, h);
    return new Promise(function (resolve, reject) {
      c.toBlob(function (blob) {
        if (!blob) return reject(new Error('could not crop ' + name));
        resolve(new File([blob], name + '.png', { type: 'image/png' }));
      }, 'image/png');
    });
  }

  function pageToFile(page, stem, n) {
    var base = page.getViewport({ scale: 1 });
    var scale = Math.min(2, MAX_W / base.width);
    var vp = page.getViewport({ scale: scale });
    var canvas = document.createElement('canvas');
    canvas.width = Math.floor(vp.width);
    canvas.height = Math.floor(vp.height);
    return page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise
      .then(function () {
        return new Promise(function (resolve, reject) {
          canvas.toBlob(function (blob) {
            if (!blob) return reject(new Error('could not rasterise page ' + n));
            resolve(new File([blob], stem + ' — page ' + n + '.png', { type: 'image/png' }));
          }, 'image/png');
        });
      });
  }

  /* toImages(file, onProgress) -> Promise<{files, total, used, split, unsplit}>
   *
   * `split` is how many pages were cut into problems by their markers;
   * `unsplit` is how many had no text layer to read and stayed whole.
   */
  function toImages(file, onProgress) {
    var stem = (file.name || 'document').replace(/\.pdf$/i, '');
    return load()
      .then(function (pdfjs) {
        return file.arrayBuffer().then(function (buf) {
          return pdfjs.getDocument({ data: new Uint8Array(buf) }).promise;
        });
      })
      .then(function (doc) {
        var count = Math.min(doc.numPages, MAX_PAGES);
        var out = [], split = 0, unsplit = 0;
        var chain = Promise.resolve();

        for (var i = 1; i <= count; i++) {
          (function (n) {
            chain = chain.then(function () {
              if (onProgress) onProgress(n, count);
              return doc.getPage(n).then(function (page) {
                var base = page.getViewport({ scale: 1 });
                var scale = Math.min(2, MAX_W / base.width);
                var vp = page.getViewport({ scale: scale });
                var canvas = document.createElement('canvas');
                canvas.width = Math.floor(vp.width);
                canvas.height = Math.floor(vp.height);

                return page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise
                  .then(function () { return page.getTextContent(); })
                  .then(function (tc) {
                    var marks = findMarkers(tc.items || []);
                    if (marks.length < 2) {
                      // One marker or none is not evidence of a split page.
                      unsplit++;
                      return cropToFile(canvas, 0, canvas.height, stem + ' \u2014 page ' + n)
                        .then(function (f) { out.push({ file: f, label: 'Page ' + n }); });
                    }
                    split++;
                    var steps = Promise.resolve();
                    marks.forEach(function (m, k) {
                      steps = steps.then(function () {
                        // PDF y counts up from the bottom; canvas counts down.
                        var top = (base.height - m.y) * scale - 12 * scale;
                        var next = marks[k + 1];
                        var bottom = next ? (base.height - next.y) * scale - 12 * scale : canvas.height;
                        top = Math.max(0, top);
                        bottom = Math.min(canvas.height, bottom);
                        if (bottom - top < 24) return;         // too thin to be a problem
                        return cropToFile(canvas, top, bottom, stem + ' \u2014 ' + m.text.replace(/[.:]$/, ''))
                          .then(function (f) { out.push({ file: f, label: m.text.replace(/[.:]$/, '') }); });
                      });
                    });
                    return steps;
                  });
              });
            });
          })(i);
        }

        return chain.then(function () {
          return { files: out.map(function (o) { return o.file; }),
                   items: out, total: doc.numPages, used: count,
                   split: split, unsplit: unsplit };
        });
      });
  }

  global.NoemaPdf = { isPdf: isPdf, toImages: toImages, MAX_PAGES: MAX_PAGES };
})(window);
