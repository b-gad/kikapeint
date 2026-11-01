#!/usr/bin/env python3
"""Capture les œuvres d'une page web « les 10 tableaux les plus connus de X » et les ajoute à manual_works.json.

  python3 scripts/capture_works.py "https://exemple.fr/10-tableaux-de-picasso|Pablo Picasso" ["URL|Artiste" ...]
  python3 scripts/capture_works.py --page https://exemple.fr/article --artist "Pablo Picasso"

Sans artiste, il est déduit du titre de la page (« ... de Pablo Picasso »). Pour chaque page :
  1. Chromium visible (1920 × 1080, échelle ×2), bandeaux fermés (refus), défilement par paliers ;
  2. les œuvres sont les images du corps de l'article (≥ 300 px de large) avec un titre voisin
     (intertitre, légende ou texte alternatif) ; l'élément image est capturé seul, en grand si une visionneuse existe ;
  3. titre nettoyé (numéros et dates entre parenthèses retirés, l'année est gardée) ; image enregistrée en JPEG
     de 1600 px maximum dans images_local/<artiste>-<titre>.jpg ;
  4. l'œuvre est cherchée sur Wikidata (identifiant, année, musée, mouvement) ; sinon identifiant local:<artiste>-<titre> ;
  5. l'entrée (image_local, private: true, licence « Non libre (usage privé) ») est ajoutée à manual_works.json ;
     python3 add_local_image.py --rebuild produit ensuite data/works_private.json (notices Wikipédia, niveau, période).
Les œuvres déjà présentes (même identifiant, ou même titre et même artiste) sont ignorées. Seuls le titre et l'année
sont repris de la page.

Installation (environnement isolé, hors dépôt) :
  python3 -m venv ~/.venvs/kikapeint-capture && ~/.venvs/kikapeint-capture/bin/pip install playwright pillow requests
  ~/.venvs/kikapeint-capture/bin/python -m playwright install chromium
  ~/.venvs/kikapeint-capture/bin/python scripts/capture_works.py ...
"""
import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageStat  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import add_local_image as ali  # noqa: E402
import fetch_works as fw  # noqa: E402
import import_list as il  # noqa: E402

MANUAL_FILE = ROOT / "manual_works.json"
MIN_WIDTH = 300           # largeur minimale (px CSS) d'une œuvre
MAX_SIDE = 1600
PAUSE = 1.5               # secondes entre deux pages
UNWANTED = re.compile(r"related|recommend|newsletter|product|sidebar|footer|header|nav|logo|avatar|author|popup|modal|cart", re.I)
REFUSE = re.compile(r"^(tout )?(refuser|rejeter|reject( all)?|decline|continuer sans accepter|non merci)", re.I)
CLOSE = {"✕", "×", "x", "fermer", "close"}
IMAGE_URL = re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.I)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# --- Titres ------------------------------------------------------------------------

def clean_title(text):
    """Retire numéros et dates entre parenthèses. Retourne (titre, année ou None)."""
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r"^(n\s*[°ºo]\s*)?\d+\s*[.)\-–:]\s*", "", t, flags=re.I)
    t = re.sub(r"^(n\s*[°º]\s*)\d+\s*", "", t, flags=re.I)
    year = None
    for m in re.finditer(r"\(([^)]*)\)", t):
        y = re.search(r"\b(1[3-9]\d\d|20\d\d)\b", m.group(1))
        if y:
            year = int(y.group(1))
    t = re.sub(r"\s*\([^)]*\d{4}[^)]*\)", "", t).strip(" -–—:,.")
    return t, year


def artist_from_page_title(title):
    m = re.search(r"\b(?:de|d'|du|par)\s+((?:[A-ZÀ-Ý][\wÀ-ÿ'’.-]*\s?){1,4})\s*(?:[–|—-]|$)", title)
    return m.group(1).strip() if m else None


# --- Navigation ---------------------------------------------------------------------

def dismiss_banners(page):
    """Ferme les bandeaux de cookies (refus) et fenêtres superposées ; ne clique jamais « Accepter »."""
    for _ in range(2):
        for b in page.query_selector_all("button, [role=button], a"):
            try:
                if not b.is_visible():
                    continue
                text = (b.inner_text() or "").strip()
                fixed = b.evaluate("e=>{for(let n=e;n&&n!==document.body;n=n.parentElement){const p=getComputedStyle(n).position;"
                                   "if(p==='fixed'||p==='sticky')return true}return false}")
                if REFUSE.search(text) or (fixed and text.lower() in CLOSE):
                    b.click(timeout=1500)
                    page.wait_for_timeout(500)
            except Exception:
                continue
    page.keyboard.press("Escape")
    # un bandeau resté en place ne doit pas recouvrir les captures
    page.add_style_tag(content="[id*=cookie i],[class*=cookie i],[id*=consent i],[class*=consent i],[class*=gdpr i]{display:none!important}")


def scroll_through(page):
    height, y = page.evaluate("document.body.scrollHeight"), 0
    while y < height:
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(350)
        y += 700
        height = page.evaluate("document.body.scrollHeight")
    page.wait_for_timeout(1200)
    page.evaluate("window.scrollTo(0, 0)")


FIND_WORKS = """(minWidth) => {
  const root = document.querySelector('article') || document.querySelector('main') || document.body;
  const all = [...root.querySelectorAll('img, h1, h2, h3, h4, h5, h6, figcaption')];
  const out = []; let heading = null, headingEl = null;
  const heads = [...root.querySelectorAll('h1, h2, h3, h4, h5, h6')];
  const sectionText = (h) => { if (!h) return ''; const i = heads.indexOf(h); const r = document.createRange();
    r.setStartAfter(h); if (heads[i + 1]) r.setEndBefore(heads[i + 1]); else r.setEndAfter(root.lastChild); return r.toString(); };
  const bad = /%s/i;
  all.forEach((e) => {
    if (/^H[1-6]$/.test(e.tagName)) { heading = e.innerText.trim(); headingEl = e; return; }
    if (e.tagName === 'FIGCAPTION') return;
    const r = e.getBoundingClientRect();
    if (r.width < minWidth || r.height < 100 || !e.offsetParent) return;
    for (let n = e; n && n !== root; n = n.parentElement) {
      if (bad.test((typeof n.className === 'string' ? n.className : '') + ' ' + (n.id || ''))) return;
      if (['HEADER','FOOTER','NAV','ASIDE'].includes(n.tagName)) return;
    }
    const fig = e.closest('figure'); const cap = fig && fig.querySelector('figcaption');
    out.push({ index: out.length, heading, caption: cap ? cap.innerText.trim() : null, alt: e.alt || '',
               src: e.currentSrc || e.src, nw: e.naturalWidth, complete: e.complete, w: r.width,
               section: headingEl ? sectionText(headingEl).slice(0, 3000) : '' });
    e.setAttribute('data-kk-work', String(out.length - 1));
    heading = null; headingEl = null;   // un intertitre n'appartient qu'à l'image qui le suit
  });
  return out;
}""" % UNWANTED.pattern


def png_ok(png):
    """Capture exploitable : non vide (pas uniforme) et de taille suffisante."""
    im = Image.open(io.BytesIO(png)).convert("L")
    return im.size[0] >= 2 * MIN_WIDTH * 0.9 and max(ImageStat.Stat(im).stddev) > 4


def enlarge_and_shoot(page, handle):
    """Si l'image s'ouvre en grand au clic (lien vers un fichier image, ou visionneuse), capture la version agrandie."""
    try:
        info = handle.evaluate("e=>{const a=e.closest('a');return {href:a?a.href:null,cursor:getComputedStyle(e).cursor,w:e.getBoundingClientRect().width}}")
        if info["href"] and IMAGE_URL.search(info["href"]):
            tab = page.context.new_page()
            try:
                tab.goto(info["href"], wait_until="load", timeout=20000)
                img = tab.query_selector("img")
                return img.screenshot(type="png") if img else None
            finally:
                tab.close()
        if info["cursor"] in ("zoom-in", "pointer"):
            handle.click(timeout=2000)
            page.wait_for_timeout(900)
            big = page.evaluate_handle("""(w)=>{const c=[...document.querySelectorAll('img')].filter(i=>{const r=i.getBoundingClientRect();
                 if(r.width<=w*1.15||!i.offsetParent)return false;
                 for(let n=i;n&&n!==document.body;n=n.parentElement){const p=getComputedStyle(n).position;if(p==='fixed')return true}return false});
                 return c.sort((a,b)=>b.getBoundingClientRect().width-a.getBoundingClientRect().width)[0]||null}""", info["w"])
            el = big.as_element()
            png = el.screenshot(type="png") if el else None
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            return png
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
    return None


def capture(page, handle, meta):
    """Capture de l'élément image seul ; une nouvelle tentative si vide ou en cours de chargement."""
    for attempt in range(2):
        handle.scroll_into_view_if_needed()
        page.wait_for_timeout(700 if attempt == 0 else 2000)
        loaded = handle.evaluate("e=>e.complete&&e.naturalWidth>=%d" % (2 * MIN_WIDTH))
        if not loaded:
            continue
        png = enlarge_and_shoot(page, handle) or handle.screenshot(type="png")
        if png and png_ok(png):
            return png
    return None


# --- Wikidata ---------------------------------------------------------------------------

def resolve_artist(name, cache):
    if name in cache:
        return cache[name]
    ids = il.search(name, "fr")
    ents = il.get_entities(ids)
    best = None
    for q in ids:
        e = ents.get(q)
        if e and "Q5" in il.claim_ids(e, "P31") and il.artist_matches(name, e):
            links = len(e.get("sitelinks", {}))
            if best is None or links > best[1]:
                best = (q, links, [x for x in il.labels(e) if x][0])
    cache[name] = best
    return best


def lookup_work(title, artist):
    """Retourne {id, year, museum, movement} si Wikidata connaît l'œuvre (titre + artiste), sinon None."""
    ids = il.search(title, "fr") + il.search(title, "en")
    ents = il.get_entities(list(dict.fromkeys(ids)))
    creators = il.get_entities({c for e in ents.values() for c in il.claim_ids(e, "P170")})
    hit, _ = il.match_row({"titre_fr": title, "title_en": title, "artiste": artist}, ents, creators)
    if not hit:
        return None
    qid, ent, _ = hit
    years = [re.search(r"\d{4}", c["mainsnak"]["datavalue"]["value"]["time"]).group()
             for c in ent.get("claims", {}).get("P571", []) if c["mainsnak"].get("datavalue")]
    extra = il.get_entities(il.claim_ids(ent, "P195")[:1] + il.claim_ids(ent, "P135")[:1])
    names = lambda ids: next((il.labels(extra[i])[0] or il.labels(extra[i])[1] for i in ids if i in extra), None)
    return {"id": qid, "year": int(years[0]) if years else None,
            "museum": names(il.claim_ids(ent, "P195")), "movement": names(il.claim_ids(ent, "P135"))}


# --- Programme --------------------------------------------------------------------------------

def known_keys():
    works = json.loads(fw.OUT_FILE.read_text(encoding="utf-8"))
    for path in (MANUAL_FILE, ali.PRIVATE_FILE, ali.OUT_FILE):
        if path.exists():
            works += json.loads(path.read_text(encoding="utf-8"))
    return ({w.get("id") for w in works},
            {(il.norm(w["title"]), il.norm(w["artist"])) for w in works if w.get("title") and w.get("artist")})


def process_page(ctx, url, artist, known_ids, known_titles, artist_cache):
    page = ctx.new_page()
    added, failed = [], []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        artist = artist or artist_from_page_title(page.title())
        if not artist:
            log(f"  ⚠ artiste introuvable dans le titre « {page.title()} » : donne-le avec URL=Artiste")
            return None, [], []
        dismiss_banners(page)
        scroll_through(page)
        works = page.evaluate(FIND_WORKS, MIN_WIDTH)
        log(f"  {len(works)} images candidates pour {artist}")
        artist_info = resolve_artist(artist, artist_cache)
        artist_tokens = set(il.norm(artist).split())
        manual = json.loads(MANUAL_FILE.read_text(encoding="utf-8")) if MANUAL_FILE.exists() else []
        for w in works:
            head, year_h = clean_title(w["heading"] or "")
            alt, year_a = clean_title(re.sub(r"\s+", " ", w["alt"]))
            alt = " ".join(t for t in alt.split() if il.norm(t) not in artist_tokens).strip()
            cap, year_c = clean_title(w["caption"] or "")
            numbered = bool(re.match(r"\s*(n\s*[°º]\s*)?\d+\s*[.)\-–:]", w["heading"] or "", re.I))
            title, year = next(((t, y) for t, y, ok in ((head, year_h, numbered), (alt, year_a, bool(alt)), (cap, year_c, True),
                                                       (head, year_h, True)) if ok and t), ("", None))
            if not title or il.norm(title) == il.norm(artist):
                continue                                    # portrait de l'artiste ou image sans titre
            if (il.norm(title), il.norm(artist)) in known_titles:
                log(f"    = déjà présente : {title}")
                continue
            handle = page.query_selector(f'[data-kk-work="{w["index"]}"]')
            png = capture(page, handle, w) if handle else None
            if not png:
                failed.append(title)
                continue
            found = lookup_work(title, artist)
            time.sleep(0.3)
            year = year or (found and found["year"])
            if not year:   # dernier recours : une année du texte de la section (seule l'année est reprise)
                m = re.search(r"\b(1[5-9]\d\d|20[0-2]\d)\b", w.get("section") or "")
                year = int(m.group(1)) if m else None
            if not year:
                log(f"    ✗ {title} : année inconnue")
                failed.append(title)
                continue
            wid = found["id"] if found else f"local:{ali.slugify(artist)}-{ali.slugify(title)}"
            if wid in known_ids:
                log(f"    = déjà présente : {title}")
                continue
            name = f"{ali.slugify(artist)}-{ali.slugify(title)}.jpg"
            im = Image.open(io.BytesIO(png)).convert("RGB")
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            ali.IMAGES_DIR.mkdir(exist_ok=True)
            im.save(ali.IMAGES_DIR / name, "JPEG", quality=90)
            movement = (found and found["movement"]) or "Art moderne"
            entry = {
                "id": wid, "title": title, "artist": artist, "year": year, "movement": movement, "type": "peinture",
                "museum": found["museum"] if found else None,
                "image": f"images_local/{name}", "image_local": f"images_local/{name}", "image_page": None,
                "image_license": ali.LICENSE, "image_credit": ali.CREDIT, "private": True, "source": "private",
                **({"artist_id": artist_info[0]} if artist_info else {}),
            }
            manual = [e for e in manual if e["id"] != wid] + [entry]
            MANUAL_FILE.write_text(json.dumps(manual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            known_ids.add(wid)
            known_titles.add((il.norm(title), il.norm(artist)))
            added.append(title)
            log(f"    ✓ {title} ({year}) {'[Wikidata ' + wid + ']' if found else '[local]'}")
    finally:
        page.close()
    return artist, added, failed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pairs", nargs="*", help="URL|Artiste (artiste facultatif : URL seule)")
    ap.add_argument("--page"), ap.add_argument("--artist")
    args = ap.parse_args()
    pairs = []
    for p in args.pairs:
        url, _, artist = p.partition("|")
        pairs.append((url.strip(), artist.strip() or None))
    if args.page:
        pairs.append((args.page, args.artist))
    if not pairs:
        ap.error("donne au moins une URL")
    known_ids, known_titles = known_keys()
    artist_cache = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=2, locale="fr-FR")
        for i, (url, artist) in enumerate(pairs):
            if i:
                time.sleep(PAUSE)
            clean = re.sub(r"[?&](srsltid|utm_[a-z]+)=[^&]*", "", url)   # paramètres de suivi retirés
            log(f"# {clean}")
            try:
                name, added, failed = process_page(ctx, clean, artist, known_ids, known_titles, artist_cache)
            except Exception as e:
                name, added, failed = artist, [], []
                log(f"  ✗ page inaccessible : {e}")
            print(f"{clean} ({name or '?'}) : {len(added)} œuvre(s) ajoutée(s)"
                  + (f" ; échecs : {', '.join(failed)}" if failed else ""))
        browser.close()


if __name__ == "__main__":
    main()
