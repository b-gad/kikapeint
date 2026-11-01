// Logique pure du quiz (aucune dépendance au DOM, testable sous Node).
// Les œuvres sont toujours identifiées par leur champ `id` (identifiant Wikidata), jamais par leur position.
(function (root) {
  const LEVELS = ["facile", "moyen", "difficile"];
  const MODES = {
    facile: Array(10).fill("facile"),
    moyen: Array(10).fill("moyen"),
    difficile: Array(10).fill("difficile"),
    mixte: [...Array(4).fill("facile"), ...Array(3).fill("moyen"), ...Array(3).fill("difficile")],
  };
  const DISTRACTORS = 3;

  // Mouvements voisins, utilisés quand il manque des distracteurs (repli « mouvements voisins »).
  const NEIGHBORS = {
    "Impressionnisme": ["Post-impressionnisme", "Symbolisme"],
    "Post-impressionnisme": ["Impressionnisme", "Symbolisme", "Fauvisme"],
    "Symbolisme": ["Post-impressionnisme", "Expressionnisme", "Impressionnisme"],
    "Fauvisme": ["Post-impressionnisme", "Expressionnisme", "Cubisme"],
    "Expressionnisme": ["Symbolisme", "Fauvisme", "Cubisme"],
    "Cubisme": ["Fauvisme", "Expressionnisme"],
  };

  // Étapes d'élargissement, de la plus stricte à la dernière extrémité.
  const STEPS = ["strict", "période élargie", "notoriété élargie", "mouvements voisins", "tous mouvements"];
  const PERIOD = [15, 30, 30, 30]; // écart d'années toléré (mode difficile), par étape
  const FAME_RATIO = [2, 2, 4, 4]; // rapport de notoriété toléré (mode difficile), par étape
  const FAME_OFFSET = 5;           // évite que 0 vs 3 sitelinks passe pour un écart énorme

  function shuffle(arr, rng) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function median(nums) {
    const s = nums.slice().sort((x, y) => x - y);
    const m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  function buildIndex(works) {
    const missing = works.filter((w) => !w.id);
    if (missing.length) throw new Error(`${missing.length} œuvre(s) sans champ id dans works.json`);
    const byId = new Map();
    const artists = new Map();
    const byLevel = { facile: [], moyen: [], difficile: [] };
    for (const w of works) {
      byId.set(w.id, w);
      if (byLevel[w.difficulty]) byLevel[w.difficulty].push(w);
      let a = artists.get(w.artist_id);
      if (!a) {
        a = { id: w.artist_id, name: w.artist, fame: w.artist_fame || 0, years: [], movements: new Set(), periods: new Set() };
        artists.set(w.artist_id, a);
      }
      a.years.push(w.year);
      a.movements.add(w.movement);
      if (w.period) a.periods.add(w.period);
    }
    for (const a of artists.values()) a.year = median(a.years);
    // « Très connu » = l'artiste a au moins une œuvre au niveau facile (artistes les plus notoires
    // et artistes de la liste importée).
    const easyArtists = new Set(byLevel.facile.map((w) => w.artist_id));
    for (const a of artists.values()) a.famous = easyArtists.has(a.id);
    return { works, byId, artists: [...artists.values()], byLevel };
  }

  // Un artiste peut-il servir de distracteur pour cette œuvre, à cette étape d'élargissement ?
  // L'artiste a-t-il au moins une œuvre dans les périodes sélectionnées ? (sans sélection : toujours oui)
  function inSelection(artist, selection) {
    if (!selection) return true;
    for (const p of artist.periods) if (selection.has(p)) return true;
    return false;
  }

  // Les distracteurs viennent d'abord des périodes sélectionnées ; la restriction ne saute qu'à la dernière
  // étape de repli (« tous mouvements »), pour ne jamais proposer moins de quatre choix.
  function accepts(level, step, work, artist, selection) {
    if (step >= 4) return true;
    if (!inSelection(artist, selection)) return false;
    const sameMovement = artist.movements.has(work.movement);
    // Facile : mouvement différent, et artistes très connus tant que c'est possible (levé dès l'étape « notoriété élargie »).
    if (level === "facile") return !sameMovement && (step >= 1 || artist.famous);
    const neighbor = (NEIGHBORS[work.movement] || []).some((m) => artist.movements.has(m));
    if (!sameMovement && !(step >= 3 && neighbor)) return false;
    if (level === "moyen") return true;
    const ratio = ((artist.fame || 0) + FAME_OFFSET) / ((work.artist_fame || 0) + FAME_OFFSET);
    const r = FAME_RATIO[step];
    return Math.abs(artist.year - work.year) <= PERIOD[step] && ratio >= 1 / r && ratio <= r;
  }

  // Question pour une œuvre : la bonne réponse + 3 distracteurs, avec l'étape de repli utilisée.
  function buildQuestion(index, work, rng, selection = null) {
    const level = work.difficulty;
    const others = index.artists.filter((a) => a.id !== work.artist_id && a.name !== work.artist);
    let step = 0;
    let candidates = [];
    for (; step < STEPS.length; step++) {
      candidates = others.filter((a) => accepts(level, step, work, a, selection));
      if (candidates.length >= DISTRACTORS) break;
    }
    if (step === STEPS.length) return null; // moins de 4 artistes au total : jeu de données inutilisable
    // À la dernière étape, on prend d'abord les artistes de la sélection (tri stable après mélange).
    const picked = shuffle(candidates, rng)
      .sort((a, b) => inSelection(b, selection) - inSelection(a, selection))
      .slice(0, DISTRACTORS);
    const choices = shuffle(
      [{ id: work.artist_id, name: work.artist }, ...picked.map((a) => ({ id: a.id, name: a.name }))], rng);
    return { workId: work.id, level, answerId: work.artist_id, choices, step, fallback: step ? STEPS[step] : null };
  }

  // `selection` : ensemble d'identifiants de période, ou null/vide = toutes les périodes.
  function newGame(mode, selection = null) {
    if (!MODES[mode]) throw new Error("Mode inconnu : " + mode);
    return {
      mode, levels: MODES[mode].slice(), usedWorks: new Set(), usedArtists: new Set(), failed: new Set(),
      selection: selection && selection.size ? new Set(selection) : null,
    };
  }

  function inPeriods(work, selection) {
    return !selection || selection.has(work.period);
  }

  // Œuvres éligibles par niveau dans une sélection (null = toute la base).
  function eligibleCounts(index, selection = null) {
    const counts = { facile: 0, moyen: 0, difficile: 0 };
    for (const level of LEVELS) counts[level] = index.byLevel[level].filter((w) => inPeriods(w, selection)).length;
    return counts;
  }

  // Un mode est jouable s'il y a, pour chaque niveau qu'il demande, assez d'œuvres éligibles
  // (10 pour facile / moyen / difficile). Mixte vise 4 + 3 + 3 mais se rabat sur les niveaux voisins
  // (voir drawQuestion) : il lui suffit de 10 œuvres au total.
  function modeAvailable(mode, counts) {
    if (mode === "mixte") return LEVELS.reduce((sum, level) => sum + counts[level], 0) >= MODES.mixte.length;
    const need = {};
    for (const level of MODES[mode]) need[level] = (need[level] || 0) + 1;
    return Object.entries(need).every(([level, n]) => counts[level] >= n);
  }

  // Largeurs (parts de 1) de la frise : proportionnelles aux durées, mais jamais sous `min` ;
  // les cases les plus longues se resserrent en compensation.
  function timelineWidths(durations, min = 0.06) {
    const n = durations.length;
    const floor = Math.min(min, 1 / n);
    const fixed = new Set();
    const widths = new Array(n).fill(floor);
    for (;;) {
      const free = durations.map((_, i) => i).filter((i) => !fixed.has(i));
      const total = free.reduce((sum, i) => sum + durations[i], 0);
      const available = 1 - fixed.size * floor;
      const small = free.filter((i) => (durations[i] / total) * available < floor);
      if (!small.length) {
        free.forEach((i) => { widths[i] = (durations[i] / total) * available; });
        return widths;
      }
      small.forEach((i) => fixed.add(i));
    }
  }

  // Mise en page de la frise : [{ ...période, end (null → thisYear), left, width }] en parts de 1.
  function timelineLayout(periods, thisYear, min = 0.06) {
    const spans = periods.map((p) => ({ ...p, end: p.end == null ? thisYear : p.end }));
    const widths = timelineWidths(spans.map((p) => Math.max(p.end - p.start, 1)), min);
    let left = 0;
    return spans.map((p, i) => {
      const item = { ...p, left, width: widths[i] };
      left += widths[i];
      return item;
    });
  }

  // Position (part de 1) d'une année sur la frise, ou null hors de la frise.
  function yearPosition(layout, year) {
    for (const p of layout) {
      if (year >= p.start && year <= p.end) return p.left + ((year - p.start) / Math.max(p.end - p.start, 1)) * p.width;
    }
    return null;
  }

  // Tire la question suivante pour un niveau : œuvre et artiste correct encore jamais utilisés,
  // et parmi elles celles qui demandent le moins de replis. Retourne null s'il n'y a plus d'œuvre.
  // En mode mixte, si le niveau demandé est épuisé, la question vient du niveau le plus proche.
  function drawQuestion(index, game, level, rng = Math.random) {
    const first = drawAtLevel(index, game, level, rng);
    if (first || game.mode !== "mixte") return first;
    const at = LEVELS.indexOf(level);
    const others = LEVELS.filter((l) => l !== level).sort((a, b) => Math.abs(LEVELS.indexOf(a) - at) - Math.abs(LEVELS.indexOf(b) - at));
    for (const other of others) {
      const q = drawAtLevel(index, game, other, rng);
      if (q) return q;
    }
    return null;
  }

  function drawAtLevel(index, game, level, rng) {
    const pool = index.byLevel[level].filter(
      (w) => !game.usedWorks.has(w.id) && !game.failed.has(w.id) && inPeriods(w, game.selection));
    let fresh = pool.filter((w) => !game.usedArtists.has(w.artist_id));
    if (!fresh.length) fresh = pool; // plus d'artiste neuf à ce niveau : on tolère un artiste répété
    const questions = shuffle(fresh, rng).map((w) => buildQuestion(index, w, rng, game.selection)).filter(Boolean);
    if (!questions.length) return null;
    const best = Math.min(...questions.map((q) => q.step));
    const q = questions.find((x) => x.step === best);
    game.usedWorks.add(q.workId);
    game.usedArtists.add(index.byId.get(q.workId).artist_id);
    return q;
  }

  // Image injoignable : l'œuvre est écartée pour la partie et son artiste redevient disponible.
  function releaseQuestion(index, game, q) {
    game.usedWorks.delete(q.workId);
    game.usedArtists.delete(index.byId.get(q.workId).artist_id);
    game.failed.add(q.workId);
  }

  const api = {
    LEVELS, MODES, STEPS, buildIndex, buildQuestion, newGame, drawQuestion, releaseQuestion,
    eligibleCounts, modeAvailable, timelineWidths, timelineLayout, yearPosition,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.QuizLogic = api;
})(typeof window !== "undefined" ? window : globalThis);
