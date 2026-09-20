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

  /* toImages(file, onProgress) -> Promise<File[]>, one per page */
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
        var out = [];
        var chain = Promise.resolve();
        for (var i = 1; i <= count; i++) {
          (function (n) {
            chain = chain.then(function () {
              if (onProgress) onProgress(n, count);
              return doc.getPage(n).then(function (page) {
                return pageToFile(page, stem, n).then(function (f) { out.push(f); });
              });
            });
          })(i);
        }
        return chain.then(function () {
          return { files: out, total: doc.numPages, used: count };
        });
      });
  }

  global.NoemaPdf = { isPdf: isPdf, toImages: toImages, MAX_PAGES: MAX_PAGES };
})(window);
