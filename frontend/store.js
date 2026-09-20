/* Noema — what carries between pages.
 *
 * The flow is now several pages: problems -> pick one and add your work ->
 * the video. A File cannot go through sessionStorage (JSON turns it into
 * "{}"), and base64 of a phone photo will blow the 5MB quota on the second
 * upload. IndexedDB stores Blobs natively and has room, so it holds the
 * problems and sessionStorage is left for the small stuff.
 *
 * Everything here is per-tab session data, not a database of anyone's work:
 * clear() empties it, and starting over on page one replaces it.
 */
(function (global) {
  'use strict';

  var DB = 'noema', STORE = 'session', VERSION = 1;

  function open() {
    return new Promise(function (resolve, reject) {
      if (!global.indexedDB) return reject(new Error('no indexedDB'));
      var req = indexedDB.open(DB, VERSION);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function tx(mode, fn) {
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var t = db.transaction(STORE, mode);
        var out = fn(t.objectStore(STORE));
        t.oncomplete = function () { resolve(out && out.result !== undefined ? out.result : out); };
        t.onerror = function () { reject(t.error); };
      });
    });
  }

  function put(key, value) { return tx('readwrite', function (s) { return s.put(value, key); }); }
  function get(key) { return tx('readonly', function (s) { return s.get(key); }); }

  /* A problem: {id, title, text, files:[File], multi:boolean}
     `multi` marks a page the student says holds more than one problem. */
  var API = {
    saveProblems: function (list) { return put('problems', list); },
    loadProblems: function () {
      return get('problems').then(function (v) { return v || []; })
                            .catch(function () { return []; });
    },
    saveChoice: function (id) { try { sessionStorage.setItem('noema:chosen', id); } catch (_) {} },
    loadChoice: function () { try { return sessionStorage.getItem('noema:chosen'); } catch (_) { return null; } },
    clear: function () {
      try { sessionStorage.removeItem('noema:chosen'); } catch (_) {}
      return put('problems', []).catch(function () {});
    },
    available: function () { return !!global.indexedDB; },
  };

  global.NoemaStore = API;
})(window);
