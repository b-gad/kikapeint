// Interface : accueil → 10 questions → fin de partie ; coups de cœur ; à propos.
(function () {
  const Q = QuizLogic;
  const STORAGE_KEY = "kikapeint:v1";
  const MODE_LABELS = { facile: "Facile", moyen: "Moyen", difficile: "Difficile", mixte: "Mixte" };
  const MAX_CREDIT = 110;
  const HEART_PATH = "M12 21s-7.5-4.6-9.6-9.2C.9 8.2 3 4.5 6.6 4.5c2 0 3.5 1.1 4.4 2.5.9-1.4 2.4-2.5 4.4-2.5 3.6 0 5.7 3.7 4.2 7.3C19.5 16.4 12 21 12 21z";

  const app = document.getElementById("app");
  const status = document.getElementById("status");
  const fav = Favorites.createStore(Favorites.browserStorage());
  let index = null;
  let game = null;
  let screenToken = 0; // invalide les rappels (erreur d'image) d'un écran déjà quitté
  const repWorkCache = new Map();

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") node.className = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    node.append(...children);
    return node;
  }

  // `screen` nomme l'écran : le CSS adapte la mise en page à chacun.
  function show(screen, ...nodes) {
    screenToken++;
    app.dataset.screen = screen;
    app.replaceChildren(...nodes);
    window.scrollTo(0, 0);
  }

  function say(text) { status.textContent = text; }

  function thumbUrl(url, width = 200) {
    return url.replace(/width=\d+$/, "width=" + width);
  }

  function link(text, href) {
    return el("a", { href, target: "_blank", rel: "noopener noreferrer" }, text);
  }

  function heartIcon() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "heart-icon");
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", HEART_PATH);
    svg.append(path);
    return svg;
  }

  // Le score est gardé en localStorage, sans affichage (peut échouer : navigation privée).
  function saveScore(mode, score) {
    try {
      const s = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
      s.best = s.best || {};
      s.best[mode] = Math.max(s.best[mode] || 0, score);
      s.history = [{ mode, score, date: new Date().toISOString() }, ...(s.history || [])].slice(0, 50);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
    } catch (e) { /* ignoré */ }
  }

  // Un artiste est représenté par son œuvre la plus connue (work_fame), à égalité par l'id le plus petit.
  function repWork(artistId) {
    if (!repWorkCache.has(artistId)) {
      let best = null;
      for (const w of index.works) {
        if (w.artist_id !== artistId) continue;
        if (!best || (w.work_fame || 0) > (best.work_fame || 0) ||
            ((w.work_fame || 0) === (best.work_fame || 0) && w.id < best.id)) best = w;
      }
      repWorkCache.set(artistId, best);
    }
    return repWorkCache.get(artistId);
  }

  // --- Accueil -----------------------------------------------------------------
  function showHome() {
    show("home",
      el("h1", { class: "brand" }, "kikapeint"),
      el("div", { class: "modes" },
        ...Object.keys(MODE_LABELS).map((m) =>
          el("button", { class: "bubble big", onclick: () => start(m) }, MODE_LABELS[m]))),
      el("nav", { class: "page-links" },
        el("button", { class: "page-link", onclick: () => showFavorites() }, "Mes coups de cœur"),
        el("button", { class: "page-link", onclick: showAbout }, "À propos")));
  }

  // --- À propos ----------------------------------------------------------------
  function showAbout() {
    show("about",
      el("h1", { class: "page-title" }, "À propos"),
      el("div", { class: "about" },
        el("p", {}, "Les notices proviennent de ", link("Wikipédia en français", "https://fr.wikipedia.org"),
          ", disponibles sous licence ", link("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/deed.fr"), "."),
        el("p", {}, "Les données sur les œuvres et les artistes proviennent de ", link("Wikidata", "https://www.wikidata.org"), "."),
        el("p", {}, "Les images proviennent de ", link("Wikimedia Commons", "https://commons.wikimedia.org"),
          ". Le crédit et la licence de chaque image figurent dans la légende de l'œuvre, après chaque réponse.")),
      el("button", { class: "next secondary", onclick: showHome }, "Retour"));
  }

  function start(mode) {
    game = Q.newGame(mode);
    game.results = []; // { workId, ok }
    showQuestion();
  }

  // --- Question ----------------------------------------------------------------
  function showQuestion() {
    const position = game.results.length;
    if (position >= game.levels.length) return showEnd();
    const q = Q.drawQuestion(index, game, game.levels[position]);
    if (!q) return showEnd(); // plus aucune œuvre disponible pour ce niveau
    renderQuestion(q, position);
  }

  function dotsFor(position) {
    return Array.from({ length: game.levels.length }, (_, i) => {
      const r = game.results[i];
      return el("li", {
        class: "dot" + (r ? (r.ok ? " ok" : " ko") : ""),
        "aria-label": `Question ${i + 1} : ${r ? (r.ok ? "juste" : "faux") : i === position ? "en cours" : "à venir"}`,
      });
    });
  }

  function renderQuestion(q, position) {
    const work = index.byId.get(q.workId);
    let answered = false;

    const dots = el("ol", { class: "dots" }, ...dotsFor(position));
    const caption = el("figcaption", { class: "caption", hidden: "" });
    const img = el("img", { src: work.image, alt: "Œuvre à identifier", decoding: "async" });
    // Image injoignable : on passe à une autre œuvre du même niveau.
    const token = screenToken + 1;
    img.addEventListener("error", () => {
      if (answered || token !== screenToken) return;
      Q.releaseQuestion(index, game, q);
      showQuestion();
    });

    const next = el("button", { class: "next sticky", hidden: "", onclick: showQuestion }, "Suivant");
    const notice = noticeCard(work); // null sans notice : pas de carte vide
    const hearts = heartsBlock(work);

    const buttons = q.choices.map((c) =>
      el("button", { class: "bubble", onclick: () => answer(c) }, c.name));

    function answer(choice) {
      if (answered) return;
      answered = true;
      const ok = choice.id === q.answerId;
      game.results.push({ workId: work.id, ok });
      buttons.forEach((b, i) => {
        b.disabled = true;
        if (q.choices[i].id === q.answerId) b.classList.add("good");
        else if (q.choices[i].id === choice.id) b.classList.add("bad");
      });
      dots.replaceChildren(...dotsFor(position + 1));
      caption.hidden = false;
      caption.replaceChildren(
        el("strong", {}, work.title),
        el("span", {}, [work.year, work.museum].filter(Boolean).join(" · ")),
        el("small", {}, imageCredit(work)));
      hearts.hidden = false;
      if (notice) notice.hidden = false;
      next.hidden = false;
      say(ok ? "Bonne réponse." : `Mauvaise réponse. C'était ${work.artist}.`);
      next.focus();
    }

    const art = el("div", { class: "stage-art" },
      el("figure", { class: "artwork" }, el("div", { class: "frame" }, img), caption));
    const side = el("div", { class: "stage-side" },
      ...[el("div", { class: "grid" }, ...buttons), hearts, notice, next].filter(Boolean));
    show("question", dots, el("div", { class: "stage" }, art, side));
  }

  // Deux cœurs : l'œuvre (par id) et l'artiste (par artist_id), chacun avec une note facultative.
  function heartsBlock(work) {
    const rows = [
      heartRow("works", work.id, "L'œuvre", `l'œuvre « ${work.title} »`),
      heartRow("artists", work.artist_id, "L'artiste", `l'artiste ${work.artist}`),
    ];
    return el("div", { class: "hearts", hidden: "" }, ...rows);
  }

  function heartRow(kind, id, label, what) {
    const button = el("button", { class: "heart", "aria-pressed": "false" }, heartIcon(), el("span", {}, label));
    const note = el("input", {
      class: "note", type: "text", maxlength: String(Favorites.MAX_NOTE),
      placeholder: "Note personnelle (facultative)", "aria-label": "Note personnelle pour " + what,
    });

    function sync() {
      const entry = fav.get(kind, id);
      button.setAttribute("aria-pressed", String(!!entry));
      button.setAttribute("aria-label", (entry ? "Retirer des coups de cœur : " : "Ajouter aux coups de cœur : ") + what);
      button.title = button.getAttribute("aria-label");
      button.classList.toggle("on", !!entry);
      note.hidden = !entry;
      note.value = entry ? entry.note : "";
    }

    button.addEventListener("click", () => {
      if (fav.has(kind, id)) { fav.remove(kind, id); say("Retiré des coups de cœur."); sync(); }
      else { fav.add(kind, id); say("Ajouté aux coups de cœur."); sync(); note.focus(); }
    });
    note.addEventListener("input", () => fav.setNote(kind, id, note.value));
    sync();
    return el("div", { class: "heart-row" }, button, note);
  }

  function noticeCard(work) {
    if (!work.notice && !work.artist_notice) return null;
    const arts = "https://artsandculture.google.com/search?q=" + encodeURIComponent(`${work.title} ${work.artist}`);
    const links = [work.wikipedia_url && link("Wikipédia", work.wikipedia_url), link("Google Arts & Culture", arts)];
    const paragraphs = [];
    if (work.notice) paragraphs.push(el("p", {}, work.notice));
    if (work.artist_notice) {
      paragraphs.push(el("p", { class: "notice-artist" },
        el("span", { class: "notice-label" }, "L'artiste"), work.artist_notice));
    }
    return el("aside", { class: "notice", hidden: "" }, ...paragraphs,
      el("p", { class: "notice-links" }, ...links.filter(Boolean)));
  }

  function imageCredit(work) {
    let credit = (work.image_credit || "").replace(/\s+/g, " ").trim();
    if (credit.length > MAX_CREDIT) credit = credit.slice(0, MAX_CREDIT).trimEnd() + "…";
    return ["Image : " + (credit || "auteur inconnu"), work.image_license].filter(Boolean).join(" · ");
  }

  // --- Fin de partie -----------------------------------------------------------
  function showEnd() {
    const score = game.results.filter((r) => r.ok).length;
    saveScore(game.mode, score);
    say(`Partie terminée : ${score} sur ${game.levels.length}.`);
    const recap = game.results.map((r) => {
      const w = index.byId.get(r.workId);
      return el("li", { class: "thumb " + (r.ok ? "ok" : "ko") },
        el("img", { src: thumbUrl(w.image, 400), alt: `${w.title}, ${w.artist}`, loading: "lazy" }),
        el("span", { class: "mark", "aria-label": r.ok ? "juste" : "faux" }, r.ok ? "✓" : "✗"));
    });
    show("end",
      el("p", { class: "score" }, `${score}/${game.levels.length}`),
      el("ul", { class: "recap" }, ...recap),
      el("div", { class: "actions" },
        el("button", { class: "next", onclick: () => start(game.mode) }, "Rejouer"),
        el("button", { class: "next secondary", onclick: showHome }, "Changer de mode")));
  }

  // --- Mes coups de cœur -------------------------------------------------------
  // Œuvres et artistes dans la même galerie ; un artiste est représenté par son œuvre la plus connue.
  function favoriteItems() {
    const items = [];
    for (const e of fav.list("works")) {
      const work = index.byId.get(e.id);
      if (work) items.push({ kind: "works", id: e.id, note: e.note, added: e.added, work });
    }
    for (const e of fav.list("artists")) {
      const work = repWork(e.id);
      if (work) items.push({ kind: "artists", id: e.id, note: e.note, added: e.added, work });
    }
    return items.sort((a, b) => (a.added < b.added ? 1 : a.added > b.added ? -1 : 0));
  }

  function exportFavorites() {
    const label = (kind, id) => {
      if (kind === "works") return index.byId.get(id)?.title;
      return repWork(id)?.artist;
    };
    const blob = new Blob([JSON.stringify(fav.exportData(label), null, 2) + "\n"], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = el("a", { href: url, download: "favorites.json" });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function showFavorites(selected) {
    const items = favoriteItems();
    const sel = selected && items.find((i) => i.kind === selected.kind && i.id === selected.id);

    const head = el("header", { class: "fav-head" },
      el("h1", { class: "page-title" }, "Mes coups de cœur"),
      el("div", { class: "fav-actions" },
        items.length || fav.count() ? el("button", { class: "next compact", onclick: exportFavorites }, "Exporter") : "",
        el("button", { class: "next secondary compact", onclick: showHome }, "Retour")));

    if (!items.length) {
      return show("favorites", head,
        el("p", { class: "fav-empty" },
          "Aucun coup de cœur pour l'instant. Après une réponse, touche un cœur pour ajouter l'œuvre ou l'artiste."));
    }

    const frames = items.map((it) => {
      const isSel = sel && sel.kind === it.kind && sel.id === it.id;
      const name = it.kind === "artists" ? it.work.artist : it.work.title;
      return el("li", {},
        el("button", {
          class: "frame-btn" + (isSel ? " selected" : ""), "aria-pressed": String(!!isSel),
          "aria-label": (it.kind === "artists" ? "Artiste : " : "Œuvre : ") + name,
          onclick: () => showFavorites({ kind: it.kind, id: it.id }),
        },
          el("span", { class: "frame" }, el("img", { src: thumbUrl(it.work.image, 400), alt: "", loading: "lazy" })),
          it.kind === "artists" ? el("span", { class: "frame-name" }, it.work.artist) : ""));
    });

    show("favorites", head,
      el("div", { class: "fav-body" + (sel ? " has-detail" : "") },
        el("ul", { class: "gallery" }, ...frames),
        sel ? favoriteDetail(sel) : ""));
  }

  function favoriteDetail(it) {
    const w = it.work;
    const isArtist = it.kind === "artists";
    const note = el("input", {
      class: "note", type: "text", id: "fav-note", maxlength: String(Favorites.MAX_NOTE),
      placeholder: "Note personnelle", value: it.note,
    });
    note.addEventListener("input", () => fav.setNote(it.kind, it.id, note.value));
    return el("section", { class: "fav-detail", "aria-live": "polite" },
      el("h2", {}, isArtist ? w.artist : w.title),
      el("p", { class: "fav-meta" }, isArtist
        ? `Œuvre la plus connue : ${w.title}, ${w.year}`
        : `${w.artist} · ${w.year}`),
      el("label", { class: "fav-label", for: "fav-note" }, "Note personnelle"),
      note,
      el("button", { class: "next secondary compact", onclick: () => {
        fav.remove(it.kind, it.id);
        say("Retiré des coups de cœur.");
        showFavorites();
      } }, "Retirer des coups de cœur"));
  }

  // --- Démarrage ---------------------------------------------------------------
  // favorites.json (racine du dépôt) est facultatif : absent ou illisible, on l'ignore.
  const remoteFavorites = fetch("favorites.json", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => { if (data) fav.setRemote(data); })
    .catch(() => {});

  fetch("data/works.json")
    .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then((works) => { index = Q.buildIndex(works); return remoteFavorites; })
    .then(showHome)
    .catch((e) => show("error", el("p", { class: "error" }, "Impossible de charger les œuvres (" + e.message + ").")));
})();
