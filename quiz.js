// Interface : accueil → 10 questions → fin de partie.
(function () {
  const Q = QuizLogic;
  const STORAGE_KEY = "kikapeint:v1";
  const MODE_LABELS = { facile: "Facile", moyen: "Moyen", difficile: "Difficile", mixte: "Mixte" };
  const MAX_CREDIT = 110;

  const app = document.getElementById("app");
  const status = document.getElementById("status");
  let index = null;
  let game = null;
  let screenToken = 0; // invalide les rappels (erreur d'image) d'un écran déjà quitté

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

  function show(...nodes) {
    screenToken++;
    app.replaceChildren(...nodes);
    window.scrollTo(0, 0);
  }

  function thumbUrl(url) {
    return url.replace(/width=\d+$/, "width=200");
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

  // --- Accueil -----------------------------------------------------------------
  function showHome() {
    show(
      el("h1", { class: "brand" }, "kikapeint"),
      el("div", { class: "modes" },
        ...Object.keys(MODE_LABELS).map((m) =>
          el("button", { class: "bubble big", onclick: () => start(m) }, MODE_LABELS[m]))),
      el("button", { class: "about-link", onclick: showAbout }, "À propos"));
  }

  // --- À propos ----------------------------------------------------------------
  function showAbout() {
    show(
      el("h1", { class: "page-title" }, "À propos"),
      el("div", { class: "about" },
        el("p", {}, "Les notices proviennent de ", link("Wikipédia en français", "https://fr.wikipedia.org"),
          ", disponibles sous licence ", link("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/deed.fr"), "."),
        el("p", {}, "Les données sur les œuvres et les artistes proviennent de ", link("Wikidata", "https://www.wikidata.org"), "."),
        el("p", {}, "Les images proviennent de ", link("Wikimedia Commons", "https://commons.wikimedia.org"),
          ". Le crédit et la licence de chaque image figurent dans la légende de l'œuvre, après chaque réponse.")),
      el("button", { class: "next secondary", onclick: showHome }, "Retour"));
  }

  function link(text, href) {
    return el("a", { href, target: "_blank", rel: "noopener noreferrer" }, text);
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
      if (notice) notice.hidden = false;
      next.hidden = false;
      status.textContent = ok ? "Bonne réponse." : `Mauvaise réponse. C'était ${work.artist}.`;
      next.focus();
    }

    const fig = el("figure", { class: "artwork" }, el("div", { class: "frame" }, img), caption);
    show(...[dots, fig, el("div", { class: "grid" }, ...buttons), notice, next].filter(Boolean));
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
    status.textContent = `Partie terminée : ${score} sur ${game.levels.length}.`;
    const recap = game.results.map((r) => {
      const w = index.byId.get(r.workId);
      return el("li", { class: "thumb " + (r.ok ? "ok" : "ko") },
        el("img", { src: thumbUrl(w.image), alt: `${w.title}, ${w.artist}`, loading: "lazy" }),
        el("span", { class: "mark", "aria-label": r.ok ? "juste" : "faux" }, r.ok ? "✓" : "✗"));
    });
    show(
      el("p", { class: "score" }, `${score}/${game.levels.length}`),
      el("ul", { class: "recap" }, ...recap),
      el("div", { class: "actions" },
        el("button", { class: "next", onclick: () => start(game.mode) }, "Rejouer"),
        el("button", { class: "next secondary", onclick: showHome }, "Changer de mode")));
  }

  // --- Démarrage ---------------------------------------------------------------
  fetch("data/works.json")
    .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then((works) => { index = Q.buildIndex(works); showHome(); })
    .catch((e) => show(el("p", { class: "error" }, "Impossible de charger les œuvres (" + e.message + ").")));
})();
