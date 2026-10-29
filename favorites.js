// Coups de cœur : stockage local + fusion avec favorites.json (aucune dépendance au DOM).
// Les œuvres sont identifiées par leur `id` et les artistes par leur `artist_id` (identifiants Wikidata).
(function (root) {
  const KEY = "kikapeint:favorites:v1";
  const KINDS = ["works", "artists"];
  const MAX_NOTE = 200;

  function emptyState() {
    return { works: {}, artists: {}, removed: { works: [], artists: [] } };
  }

  function cleanNote(note) {
    return typeof note === "string" ? note.slice(0, MAX_NOTE) : "";
  }

  // Remet en forme des données lues (localStorage ou favorites.json), en ignorant ce qui est invalide.
  function normalize(raw) {
    const out = emptyState();
    if (!raw || typeof raw !== "object") return out;
    for (const kind of KINDS) {
      const src = raw[kind];
      const entries = Array.isArray(src)
        ? src.filter((e) => e && typeof e.id === "string")
        : Object.entries(src || {}).map(([id, e]) => ({ ...(e || {}), id }));
      for (const e of entries) {
        out[kind][e.id] = { note: cleanNote(e.note), added: typeof e.added === "string" ? e.added : "" };
      }
      const removed = raw.removed && raw.removed[kind];
      if (Array.isArray(removed)) out.removed[kind] = removed.filter((id) => typeof id === "string");
    }
    return out;
  }

  // localStorage peut être absent ou lever une exception (navigation privée, stockage bloqué).
  function browserStorage() {
    try {
      const s = root.localStorage;
      s.setItem("__kikapeint", "1");
      s.removeItem("__kikapeint");
      return s;
    } catch (e) {
      return null;
    }
  }

  // `storage` : objet getItem/setItem, ou null (le jeu fonctionne alors avec une mémoire volatile).
  function createStore(storage) {
    let local = emptyState();
    let remote = emptyState(); // contenu de favorites.json, jamais écrit dans le stockage
    if (storage) {
      try { local = normalize(JSON.parse(storage.getItem(KEY))); } catch (e) { /* données illisibles : on repart de zéro */ }
    }

    function persist() {
      if (!storage) return false;
      try { storage.setItem(KEY, JSON.stringify(local)); return true; } catch (e) { return false; }
    }

    // Vue fusionnée : favorites.json d'abord, le stockage local prime en cas de conflit,
    // et un coup de cœur retiré localement ne revient pas depuis le fichier.
    function merged(kind) {
      const out = {};
      for (const [id, e] of Object.entries(remote[kind])) {
        if (!local.removed[kind].includes(id)) out[id] = e;
      }
      return { ...out, ...local[kind] };
    }

    return {
      persistent: !!storage,
      setRemote(data) { remote = normalize(data); },
      has(kind, id) { return Object.prototype.hasOwnProperty.call(merged(kind), id); },
      get(kind, id) { return merged(kind)[id] || null; },
      add(kind, id, note = "") {
        local[kind][id] = { note: cleanNote(note), added: new Date().toISOString() };
        local.removed[kind] = local.removed[kind].filter((x) => x !== id);
        return persist();
      },
      setNote(kind, id, note) {
        const current = merged(kind)[id];
        if (!current) return false;
        local[kind][id] = { ...current, note: cleanNote(note) };
        return persist();
      },
      remove(kind, id) {
        delete local[kind][id];
        if (!local.removed[kind].includes(id)) local.removed[kind].push(id);
        return persist();
      },
      // [{ id, note, added }], les plus récents d'abord
      list(kind) {
        return Object.entries(merged(kind))
          .map(([id, e]) => ({ id, note: e.note, added: e.added }))
          .sort((a, b) => (a.added < b.added ? 1 : a.added > b.added ? -1 : a.id < b.id ? -1 : 1));
      },
      count() { return KINDS.reduce((n, k) => n + Object.keys(merged(k)).length, 0); },
      // Contenu de favorites.json. `label(kind, id)` ajoute un nom lisible (ignoré à la relecture).
      exportData(label = () => undefined) {
        const out = { version: 1, exported: new Date().toISOString() };
        for (const kind of KINDS) {
          out[kind] = this.list(kind).map((e) => {
            const item = { id: e.id, note: e.note, added: e.added };
            const l = label(kind, e.id);
            return l ? { label: l, ...item } : item;
          });
        }
        return out;
      },
    };
  }

  const api = { KEY, MAX_NOTE, createStore, browserStorage, normalize };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Favorites = api;
})(typeof window !== "undefined" ? window : globalThis);
