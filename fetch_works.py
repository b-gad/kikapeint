#!/usr/bin/env python3
"""Génère data/works.json à partir de Wikidata, Wikimedia Commons et Wikipédia (fr).

Le périmètre vient de config.json, les œuvres ajoutées à la main de manual_works.json
(fichier jamais modifié par ce script).

Pipeline :
  1. SPARQL Wikidata : un appel par mouvement + un appel par artiste supplémentaire
  2. Filtre sur les licences libres des images (API Commons)
  3. Notices courtes en français (API Wikipédia fr)
  4. Sélection avec plafonds, vérification HEAD de chaque image retenue
  5. Fusion avec curated_works.json (généré par import_list.py, hors plafonds) et manual_works.json
  6. Notoriété (sitelinks Wikidata, vues Wikipédia en option), niveaux de difficulté,
     surcharges de difficulty_overrides.json (jamais modifié), écriture de data/works.json
"""
import argparse
import datetime
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote, unquote

import requests

ROOT = Path(__file__).parent
CONFIG_FILE = ROOT / "config.json"
MANUAL_FILE = ROOT / "manual_works.json"
CURATED_FILE = ROOT / "curated_works.json"  # généré par import_list.py
PERIOD_FILE = ROOT / "period_works.json"    # généré par fill_periods.py
OVERRIDES_FILE = ROOT / "difficulty_overrides.json"
OUT_FILE = ROOT / "data" / "works.json"

SPARQL_URL = "https://query.wikidata.org/sparql"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
FRWIKI_API = "https://fr.wikipedia.org/w/api.php"
COMMONS_FILEPATH = "https://commons.wikimedia.org/wiki/Special:FilePath/"
COMMONS_FILEPAGE = "https://commons.wikimedia.org/wiki/File:"
HEADERS = {"User-Agent": "kikapeint/0.2 (projet perso; gadretorix.corp@gmail.com) python-requests"}

TYPES = {"Q3305213": "peinture", "Q860861": "sculpture"}
IMAGE_WIDTH = 800
LINK_CHECK_PAUSE = 0.3  # secondes entre deux requêtes HEAD
PAGEVIEWS_PAUSE = 0.2   # secondes entre deux requêtes à l'API des vues
PAGEVIEWS_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/fr.wikipedia/all-access/user/"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
VIEWS_WEIGHT = 10       # fame = sitelinks + round(VIEWS_WEIGHT * log10(1 + vues mensuelles moyennes))
LEVELS = ("facile", "moyen", "difficile")  # du plus au moins notoire
OUTPUT_FIELDS = ["id", "title", "artist", "artist_id", "year", "movement", "period", "type", "museum",
                 "image", "image_page", "image_license", "image_credit",
                 "notice", "notice_type", "artist_notice", "wikipedia_url", "work_fame", "artist_fame",
                 "difficulty", "difficulty_source", "source"]

# Licences Commons acceptées (préfixes, en minuscules)
FREE_LICENSES = ("cc0", "cc by", "cc-by", "public domain", "pd", "attribution")

SPARQL_TEMPLATE = """
SELECT ?work ?workLabel ?type ?creator ?creatorLabel ?date ?image ?collectionLabel ?workArticle ?creatorArticle ?workLinks ?creatorLinks WHERE {{
  VALUES ?type {{ wd:Q3305213 wd:Q860861 }}
  {selector}
  ?work wdt:P31 ?type ;
        wdt:P170 ?creator ;
        wdt:P571 ?date ;
        wdt:P18 ?image .
  ?work wikibase:sitelinks ?workLinks .
  ?creator wikibase:sitelinks ?creatorLinks .
  FILTER(YEAR(?date) >= {ymin} && YEAR(?date) <= {ymax})
  OPTIONAL {{ ?work wdt:P195 ?collection . }}
  OPTIONAL {{ ?workArticle schema:about ?work ; schema:isPartOf <https://fr.wikipedia.org/> . }}
  OPTIONAL {{ ?creatorArticle schema:about ?creator ; schema:isPartOf <https://fr.wikipedia.org/> . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
}}
LIMIT {limit}
"""


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def qid(uri):
    return uri.rsplit("/", 1)[-1]


def get_json(url, params, retries=4):
    for attempt in range(retries):
        r = requests.get(url, params=params, headers=HEADERS, timeout=90)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


# --- Commons : noms et URL de fichiers ---------------------------------------

def image_url(filename):
    return COMMONS_FILEPATH + quote(filename.replace(" ", "_")) + f"?width={IMAGE_WIDTH}"


def image_page(filename):
    return COMMONS_FILEPAGE + quote(filename.replace(" ", "_"))


def commons_filename(value):
    """Nom de fichier Commons depuis une URL Special:FilePath, une page File:/Fichier:, ou un nom brut."""
    v = unquote(value.strip()).split("?")[0].split("#")[0]
    if "upload.wikimedia.org" in v:
        raise ValueError("URL upload.wikimedia.org non supportée : utilise la page File: ou Special:FilePath")
    m = re.search(r"(?:Special:FilePath/|/wiki/(?:File|Fichier):)(.+)$", v, re.I)
    if m:
        v = m.group(1)
    v = re.sub(r"^(?:File|Fichier):", "", v, flags=re.I)
    return v.replace("_", " ").strip()


# --- 1. Wikidata --------------------------------------------------------------

def museum_name(b):
    # « Valeur inconnue » dans Wikidata : le label est une URL genid, on l'ignore.
    name = b.get("collectionLabel", {}).get("value")
    return None if not name or name.startswith("http") or re.fullmatch(r"Q\d+", name) else name


def run_query(selector, ymin, ymax, limit, movement_name):
    query = SPARQL_TEMPLATE.format(selector=selector, ymin=ymin, ymax=ymax, limit=limit)
    data = get_json(SPARQL_URL, {"query": query, "format": "json"})
    rows = []
    for b in data["results"]["bindings"]:
        label = b["workLabel"]["value"]
        artist = b["creatorLabel"]["value"]
        # Sans libellé, le service renvoie l'identifiant brut (Q123) : on écarte.
        if re.fullmatch(r"Q\d+", label) or re.fullmatch(r"Q\d+", artist):
            continue
        rows.append({
            "id": qid(b["work"]["value"]),
            "title": label,
            "artist": artist,
            "artist_id": qid(b["creator"]["value"]),
            "year": int(b["date"]["value"].lstrip("+")[:4]),
            "movement": movement_name,
            "type": TYPES[qid(b["type"]["value"])],
            "museum": museum_name(b),
            "commons_file": commons_filename(b["image"]["value"]),
            "work_article": unquote(b["workArticle"]["value"].rsplit("/", 1)[-1]) if "workArticle" in b else None,
            "artist_article": unquote(b["creatorArticle"]["value"].rsplit("/", 1)[-1]) if "creatorArticle" in b else None,
            "work_sitelinks": int(b["workLinks"]["value"]),
            "artist_sitelinks": int(b["creatorLinks"]["value"]),
            "source": "wikidata",
        })
    return rows


def query_movement(mv, cfg):
    return run_query(f"?work wdt:P135 wd:{mv['id']} .",
                     mv.get("year_min", cfg["year_min"]), mv.get("year_max", cfg["year_max"]),
                     cfg["limits"]["sparql_rows_per_movement"], mv["name"])


def query_artist(extra, cfg):
    return run_query(f"VALUES ?creator {{ wd:{extra['id']} }}",
                     cfg["year_min"], cfg["year_max"],
                     cfg["limits"]["sparql_rows_per_movement"], extra["movement"])


def merge_rows(all_rows):
    """Une œuvre peut avoir plusieurs mouvements : on garde la première occurrence."""
    merged = {}
    for r in all_rows:
        merged.setdefault(r["id"], r)
    return list(merged.values())


# --- 2. Licences Commons ------------------------------------------------------

def is_free(license_name):
    ln = (license_name or "").lower()
    if not ln or "fair use" in ln or "non-free" in ln:
        return False
    return ln.startswith(FREE_LICENSES)


def fetch_licenses(files):
    licenses = {}
    files = sorted(set(files))
    for i in range(0, len(files), 50):
        chunk = files[i:i + 50]
        data = get_json(COMMONS_API, {
            "action": "query", "format": "json", "prop": "imageinfo",
            "iiprop": "extmetadata", "iiextmetadatafilter": "LicenseShortName|Artist",
            "titles": "|".join("File:" + f for f in chunk),
        })
        # Les titres peuvent être normalisés (underscores → espaces) : on remappe.
        norm = {n["to"]: n["from"] for n in data["query"].get("normalized", [])}
        for page in data["query"]["pages"].values():
            title = norm.get(page["title"], page["title"])[len("File:"):]
            meta = (page.get("imageinfo") or [{}])[0].get("extmetadata", {})
            licenses[title] = {
                "license": meta.get("LicenseShortName", {}).get("value"),
                "credit": re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip() or None,
            }
        log(f"  licences : {min(i + 50, len(files))}/{len(files)}")
    return licenses


# --- 3. Notices Wikipédia fr --------------------------------------------------

def shorten(text, max_chars=420):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    end = cut.rfind(".")
    return cut[:end + 1] if end > 120 else cut.rsplit(" ", 1)[0] + "…"


def fetch_extracts(titles):
    extracts = {}
    titles = sorted(set(titles))
    for i in range(0, len(titles), 20):
        chunk = titles[i:i + 20]
        data = get_json(FRWIKI_API, {
            "action": "query", "format": "json", "prop": "extracts", "exintro": 1,
            "explaintext": 1, "redirects": 1, "exlimit": 20, "titles": "|".join(chunk),
        })
        q = data["query"]
        back = {}
        for chain in (q.get("normalized", []), q.get("redirects", [])):
            for m in chain:
                back[m["to"]] = back.get(m["from"], m["from"])
        for page in q["pages"].values():
            if page.get("extract"):
                extract = shorten(page["extract"])
                extracts[back.get(page["title"], page["title"])] = extract
                extracts[page["title"]] = extract
    return extracts


def add_notices(works):
    titles = [w[f] for w in works for f in ("work_article", "artist_article") if w[f]]
    log(f"  {len(set(titles))} articles à interroger")
    ex = fetch_extracts([t.replace("_", " ") for t in titles])
    for w in works:
        w["notice"], w["notice_type"] = None, None
        for field, ntype in (("work_article", "work"), ("artist_article", "artist")):
            title = (w[field] or "").replace("_", " ")
            if title in ex:
                w["notice"], w["notice_type"] = ex[title], ntype
                w["wikipedia_url"] = "https://fr.wikipedia.org/wiki/" + w[field]
                break
        # Présentation de l'artiste, en plus de la notice de l'œuvre. Inutile (doublon) quand la
        # notice est déjà celle de l'artiste.
        w["artist_notice"] = None
        if w["notice_type"] == "work":
            w["artist_notice"] = ex.get((w["artist_article"] or "").replace("_", " "))
    return works


# --- 4. Vérification des liens -------------------------------------------------

def link_ok(url):
    """HEAD sur l'URL de la miniature (redirections suivies) ; pause systématique ensuite."""
    ok = False
    for attempt in range(3):
        try:
            r = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=30)
        except requests.RequestException:
            time.sleep(2)
            continue
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        ok = r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/")
        break
    time.sleep(LINK_CHECK_PAUSE)
    return ok


# --- 5. Œuvres manuelles -------------------------------------------------------

def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_manual(licenses_needed):
    """Lit manual_works.json (sans jamais l'écrire) et normalise les entrées."""
    if not MANUAL_FILE.exists():
        return []
    entries = json.loads(MANUAL_FILE.read_text(encoding="utf-8"))
    works = []
    for i, e in enumerate(entries, 1):
        if e.get("image_local"):  # image fournie par l'utilisateur : traitée par add_local_image.py (data/works_private.json)
            continue
        missing = [k for k in ("title", "artist", "year", "movement", "image") if not e.get(k)]
        if missing:
            log(f"  ⚠ manual_works.json #{i} ignorée, champs manquants : {', '.join(missing)}")
            continue
        try:
            fname = commons_filename(e["image"])
        except ValueError as err:
            log(f"  ⚠ manual_works.json #{i} ({e['title']}) ignorée : {err}")
            continue
        notice_type = e.get("notice_type", "work")
        works.append({
            "id": f"manual-{slug(e['artist'])}-{slug(e['title'])}",
            "title": e["title"], "artist": e["artist"],
            "artist_id": e.get("artist_id") or f"manual-{slug(e['artist'])}",
            "year": int(e["year"]), "movement": e["movement"],
            "type": e.get("type", "peinture"), "museum": e.get("museum"),
            "commons_file": fname, "notice": e.get("notice"),
            "notice_type": notice_type if e.get("notice") else None,
            "artist_notice": e.get("artist_notice"),
            "wikipedia_url": e.get("wikipedia_url"), "source": "manual",
        })
        licenses_needed.append(fname)
    return works


def load_curated():
    """Lit curated_works.json (généré par import_list.py). Les images y ont déjà été vérifiées."""
    if not CURATED_FILE.exists():
        return []
    works = json.loads(CURATED_FILE.read_text(encoding="utf-8"))
    for w in works:
        w["commons_file"] = commons_filename(w["image"])
    return works


# --- 6. Notoriété et difficulté ------------------------------------------------

def load_period_works():
    """Lit period_works.json (généré par fill_periods.py). Niveaux de difficulté calculés comme pour les autres."""
    if not PERIOD_FILE.exists():
        return []
    works = json.loads(PERIOD_FILE.read_text(encoding="utf-8"))
    for w in works:
        w["commons_file"] = commons_filename(w["image"])
    return works


def merge_period_works(existing, movement_names, easy_cfg, periods, table):
    """Ajoute à des œuvres déjà au format works.json celles de period_works.json qu'elles ne contiennent pas.
    Les niveaux des œuvres existantes ne bougent pas : les nouvelles sont classées avec les mêmes règles
    (seuils « facile », puis médiane de notoriété des œuvres non faciles déjà présentes)."""
    have = {w["id"] for w in existing}
    new = [w for w in load_period_works() if w["id"] not in have]
    for w in new:
        w["work_fame"], w["artist_fame"] = w["work_sitelinks"], w["artist_sitelinks"]
        w["image_page"] = image_page(w["commons_file"])
        if w["movement"] not in movement_names:
            movement_names.append(w["movement"])
    rest = sorted((w["work_fame"], w["artist_fame"]) for w in existing if w["difficulty"] != LEVELS[0])
    median = rest[len(rest) // 2] if rest else (0, 0)
    for w in new:
        easy = w["artist_fame"] >= easy_cfg["easy_min_artist_fame"] and w["work_fame"] >= easy_cfg["easy_min_work_fame"]
        w["difficulty"] = LEVELS[0] if easy else LEVELS[1] if (w["work_fame"], w["artist_fame"]) >= median else LEVELS[2]
        w["difficulty_source"] = "computed"
    apply_overrides(new)
    for w in new:
        w["period"] = period_for(w, periods, table)
    return existing + new, len(new)


def fetch_sitelinks(ids):
    """Nombre de sitelinks Wikidata pour des identifiants Q (utile aux artistes des œuvres manuelles)."""
    out = {}
    ids = sorted(set(ids))
    for i in range(0, len(ids), 50):
        data = get_json(WIKIDATA_API, {"action": "wbgetentities", "format": "json", "props": "sitelinks",
                                       "ids": "|".join(ids[i:i + 50])})
        for q, ent in data.get("entities", {}).items():
            out[q] = len(ent.get("sitelinks", {}))
    return out


def monthly_views(title):
    """Vues mensuelles moyennes (fr.wikipedia, utilisateurs) sur les 12 derniers mois complets."""
    first_of_month = datetime.date.today().replace(day=1)
    end = first_of_month - datetime.timedelta(days=1)
    start = (first_of_month - datetime.timedelta(days=365)).replace(day=1)
    url = PAGEVIEWS_API + quote(title.replace(" ", "_"), safe="") + f"/monthly/{start:%Y%m%d}00/{end:%Y%m%d}00"
    for attempt in range(3):
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code != 200:  # 404 : pas de données pour cette page
            return 0
        items = r.json().get("items", [])
        return sum(i["views"] for i in items) / max(len(items), 1)
    return 0


def add_fame(works, with_views):
    """work_fame / artist_fame : sitelinks Wikidata, plus un terme logarithmique si les vues sont activées."""
    manual_artists = [w["artist_id"] for w in works
                      if "artist_sitelinks" not in w and re.fullmatch(r"Q\d+", w["artist_id"])]
    extra = fetch_sitelinks(manual_artists) if manual_artists else {}
    views_cache = {}

    def views(title):
        if not title:
            return 0
        if title not in views_cache:
            views_cache[title] = monthly_views(title.replace("_", " "))
            time.sleep(PAGEVIEWS_PAUSE)
        return views_cache[title]

    def fame(links, title):
        if not with_views:
            return links
        return links + round(VIEWS_WEIGHT * math.log10(1 + views(title)))

    for n, w in enumerate(works, 1):
        w.setdefault("work_sitelinks", 0)  # œuvre manuelle : pas d'entité Wikidata, à ajuster en surcharge
        w.setdefault("artist_sitelinks", extra.get(w["artist_id"], 0))
        w["work_fame"] = fame(w["work_sitelinks"], w.get("work_article"))
        w["artist_fame"] = fame(w["artist_sitelinks"], w.get("artist_article"))
        if with_views and n % 50 == 0:
            log(f"  vues : {n}/{len(works)}")


def assign_levels(works, easy_min_artist_fame, easy_min_work_fame, curated_ids=frozenset()):
    """Facile : toute œuvre de la liste commentée (curated_works.json), ou artiste ET œuvre très connus
    (seuils de config.json). Le reste est coupé en deux moitiés sur (work_fame, artist_fame) : la plus notoire est « moyen »,
    l'autre « difficile ». À notoriété d'œuvre égale, celle de l'artiste départage."""
    def is_easy(w):
        return w["id"] in curated_ids or (
            w["artist_fame"] >= easy_min_artist_fame and w["work_fame"] >= easy_min_work_fame)

    rest = sorted((w["work_fame"], w["artist_fame"]) for w in works if not is_easy(w))
    median = rest[len(rest) // 2] if rest else (0, 0)
    for w in works:
        key = (w["work_fame"], w["artist_fame"])
        w["difficulty"] = LEVELS[0] if is_easy(w) else LEVELS[1] if key >= median else LEVELS[2]
        w["difficulty_source"] = "curated" if w["id"] in curated_ids else "computed"


def load_periods(cfg):
    """Périodes de config.json (fin `null` = aujourd'hui), contiguës ; vérifie aussi la table movement → période."""
    this_year = datetime.date.today().year
    periods = []
    for p in cfg["periods"]:
        end = p["end"] if p.get("end") is not None else this_year
        periods.append({**p, "end": end, "center": (p["start"] + end) / 2})
    for a, b in zip(periods, periods[1:]):
        if a["end"] != b["start"]:
            sys.exit(f"config.json : les périodes « {a['id']} » et « {b['id']} » ne sont pas contiguës "
                     f"({a['end']} ≠ {b['start']})")
    ids = {p["id"] for p in periods}
    for movement, pid in cfg["movement_periods"].items():
        if pid not in ids:
            sys.exit(f"config.json : movement_periods[« {movement} »] référence une période inconnue « {pid} »")
    return periods


def period_for(work, periods, table):
    """Table movement → période d'abord ; sinon la période dont le centre est le plus proche de l'année.
    Les bornes des périodes ne servent pas à attribuer les œuvres, seulement à dessiner la frise."""
    if work["movement"] in table:
        return table[work["movement"]]
    return min(periods, key=lambda p: abs(p["center"] - work["year"]))["id"]


def period_summary(works, periods, table):
    print(f"\n{'Période':<48}{'Œuvres':>7}{'Peint.':>7}{'Sculp.':>7}{'Artistes':>9}{'facile':>8}{'moyen':>7}{'difficile':>10}")
    print("-" * 103)
    for p in periods + [None]:
        ws = works if p is None else [w for w in works if w["period"] == p["id"]]
        label = "TOTAL" if p is None else f"{p['name']} ({p['start']}-{p['end']})"
        print(f"{label:<48}{len(ws):>7}{sum(w['type'] == 'peinture' for w in ws):>7}"
              f"{sum(w['type'] == 'sculpture' for w in ws):>7}{len({w['artist_id'] for w in ws}):>9}"
              + "".join(f"{sum(w['difficulty'] == lv for w in ws):>{n}}" for lv, n in zip(LEVELS, (8, 7, 10))))
    by_year = Counter(w["movement"] for w in works if w["movement"] not in table)
    if by_year:
        print("\nPériode attribuée d'après l'année (mouvement absent de movement_periods) : "
              + ", ".join(f"{m} ({n})" for m, n in by_year.most_common()))


def apply_overrides(works):
    """difficulty_overrides.json : {"works": {id: niveau}, "artists": {id: niveau}} ; l'œuvre prime sur l'artiste."""
    if not OVERRIDES_FILE.exists():
        return
    ov = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
    for kind in ("works", "artists"):
        for ident, level in ov.get(kind, {}).items():
            if level not in LEVELS:
                sys.exit(f"difficulty_overrides.json : niveau « {level} » invalide pour {ident} (attendu : {', '.join(LEVELS)})")
    by_work, by_artist = ov.get("works", {}), ov.get("artists", {})
    known = {w["id"] for w in works} | {w["artist_id"] for w in works}
    for ident in list(by_work) + list(by_artist):
        if ident not in known:
            log(f"  ⚠ difficulty_overrides.json : « {ident} » ne correspond à aucune œuvre ni artiste retenus")
    for w in works:
        level = by_work.get(w["id"]) or by_artist.get(w["artist_id"])
        if level:
            w["difficulty"], w["difficulty_source"] = level, "override"


# --- 7. Récapitulatif ----------------------------------------------------------

def summary(works, movement_order):
    by_mv = defaultdict(list)
    for w in works:
        by_mv[w["movement"]].append(w)
    names = movement_order + [m for m in by_mv if m not in movement_order]
    head = f"{'Mouvement':<22}{'Œuvres':>7}{'Artistes':>9}{'Peint.':>7}{'Sculp.':>7}{'N.œuvre':>9}{'N.artiste':>10}{'Manuel':>7}   Période"
    print("\n" + head)
    print("-" * len(head))

    def row(label, ws):
        if not ws:
            return f"{label:<22}{0:>7}"
        years = [w["year"] for w in ws]
        return (f"{label:<22}{len(ws):>7}{len({w['artist_id'] for w in ws}):>9}"
                f"{sum(w['type'] == 'peinture' for w in ws):>7}{sum(w['type'] == 'sculpture' for w in ws):>7}"
                f"{sum(w['notice_type'] == 'work' for w in ws):>9}{sum(w['notice_type'] == 'artist' for w in ws):>10}"
                f"{sum(w['source'] == 'manual' for w in ws):>7}   {min(years)}-{max(years)}")

    for n in names:
        print(row(n, by_mv.get(n, [])))
    print("-" * len(head))
    print(row("TOTAL", works))
    weak = [n for n in names if len({w['artist_id'] for w in by_mv.get(n, [])}) < 8]
    if weak:
        print(f"\n⚠ Moins de 8 artistes pour : {', '.join(weak)} (quiz à 4 choix fragile)")

    # Œuvres par niveau et par mouvement
    print(f"\n{'Mouvement':<22}" + "".join(f"{lv:>10}" for lv in LEVELS) + f"{'Surchargées':>13}")
    print("-" * 67)
    for n in names + ["TOTAL"]:
        ws = works if n == "TOTAL" else by_mv.get(n, [])
        print(f"{n:<22}" + "".join(f"{sum(w['difficulty'] == lv for w in ws):>10}" for lv in LEVELS)
              + f"{sum(w['difficulty_source'] == 'override' for w in ws):>13}")

    # Artistes par notoriété
    artists = {}
    for w in works:
        a = artists.setdefault(w["artist_id"], {"name": w["artist"], "fame": w["artist_fame"], "n": 0, "mv": w["movement"]})
        a["n"] += 1
    ranked = sorted(artists.values(), key=lambda a: (-a["fame"], a["name"]))
    for title, subset in (("20 artistes les plus notoires", ranked[:20]), ("20 artistes les moins notoires", ranked[-20:][::-1])):
        print(f"\n{title}")
        for i, a in enumerate(subset, 1):
            print(f"  {i:>2}. {a['name']:<32}{a['fame']:>5}  {a['n']:>3} œuvre(s)  {a['mv']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-link-check", action="store_true", help="saute la vérification HEAD des images (debug)")
    ap.add_argument("--periods-only", action="store_true",
                    help="recalcule seulement le champ period de data/works.json (sans réseau, aucun autre champ modifié)")
    ap.add_argument("--merge-only", action="store_true",
                    help="ajoute à data/works.json les œuvres de period_works.json absentes (sans réseau, "
                         "les œuvres existantes ne changent pas)")
    ap.add_argument("--pageviews", action="store_true",
                    help="ajoute les vues Wikipédia fr mensuelles (12 derniers mois) à la notoriété ; plus lent")
    args = ap.parse_args()

    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    periods = load_periods(cfg)
    if args.periods_only:
        works = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        for w in works:
            w["period"] = period_for(w, periods, cfg["movement_periods"])
        out = [{k: w.get(k) for k in OUTPUT_FIELDS} for w in works]
        OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        log(f"  {OUT_FILE.relative_to(ROOT)} : champ period mis à jour sur {len(out)} œuvres")
        period_summary(out, periods, cfg["movement_periods"])
        return
    if args.merge_only:
        works = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        movement_names = list(dict.fromkeys(w["movement"] for w in works))
        works, added = merge_period_works(works, movement_names, cfg["difficulty"], periods, cfg["movement_periods"])
        works.sort(key=lambda w: (movement_names.index(w["movement"]), w["artist"], w["year"]))
        out = [{k: w.get(k) for k in OUTPUT_FIELDS} for w in works]
        OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        log(f"  {OUT_FILE.relative_to(ROOT)} : {added} œuvres ajoutées, {len(out)} au total")
        period_summary(out, periods, cfg["movement_periods"])
        return
    movement_names = [m["name"] for m in cfg["movements"]]
    for x in cfg["extra_artists"]:
        if x["movement"] not in movement_names:
            sys.exit(f"config.json : l'artiste {x['id']} référence un mouvement inconnu « {x['movement']} »")
    OUT_FILE.parent.mkdir(exist_ok=True)

    log("1/6 Wikidata (SPARQL)")
    rows = []
    for mv in cfg["movements"]:
        got = query_movement(mv, cfg)
        log(f"  {mv['name']}: {len(got)} lignes")
        rows += got
        time.sleep(1)
    for x in cfg["extra_artists"]:
        got = query_artist(x, cfg)
        log(f"  artiste {x['id']} ({x['movement']}): {len(got)} lignes")
        rows += got
        time.sleep(1)
    works = merge_rows(rows)
    log(f"  {len(works)} œuvres uniques")

    log("2/6 Licences des images (Commons)")
    files_for_license = []
    manual = load_manual(files_for_license)
    licenses = fetch_licenses([w["commons_file"] for w in works] + files_for_license)
    free = []
    for w in works:
        info = licenses.get(w["commons_file"], {})
        if is_free(info.get("license")):
            w["image_license"], w["image_credit"] = info["license"], info["credit"]
            free.append(w)
    works = free
    log(f"  {len(works)} œuvres avec image libre")

    log("3/6 Notices (Wikipédia fr)")
    works = add_notices(works)
    # Sans aucune notice, l'étape « notice après réponse » du quiz serait vide : on écarte.
    works = [w for w in works if w["notice"]]
    log(f"  {len(works)} œuvres avec notice")

    log("4/6 Sélection et vérification des images (HEAD)")
    # Priorité : notice propre à l'œuvre, puis diversité d'artistes (plafond par artiste).
    works.sort(key=lambda w: (w["notice_type"] != "work", w["artist"], w["year"]))
    lim = cfg["limits"]
    selected, per_artist, per_mv, dead = [], Counter(), Counter(), []
    for w in works:
        k = (w["movement"], w["artist_id"])
        if per_mv[w["movement"]] >= lim["works_per_movement"] or per_artist[k] >= lim["works_per_artist"]:
            continue
        w["image"] = image_url(w["commons_file"])
        if not args.skip_link_check and not link_ok(w["image"]):
            dead.append(w)
            continue
        selected.append(w)
        per_artist[k] += 1
        per_mv[w["movement"]] += 1
        if len(selected) % 50 == 0:
            log(f"  {len(selected)} images vérifiées")
    log(f"  {len(selected)} retenues, {len(dead)} écartées (image injoignable)")
    for w in dead:
        log(f"    ✗ {w['id']} {w['title']} — {w['image']}")

    log("5/6 Fusion avec curated_works.json et manual_works.json, écriture")
    # Les œuvres de la liste commentée échappent aux plafonds. En cas de même id, l'œuvre déjà retenue gagne.
    taken = {w["id"] for w in selected}
    curated = [w for w in load_curated() if w["id"] not in taken]
    log(f"  curated_works.json : {len(curated)} œuvres ajoutées ({len(load_curated()) - len(curated)} déjà présentes)")
    for w in curated:
        if w["movement"] not in movement_names:
            movement_names.append(w["movement"])
    selected = selected + curated
    taken |= {w["id"] for w in curated}
    period_works = [w for w in load_period_works() if w["id"] not in taken]
    log(f"  period_works.json : {len(period_works)} œuvres ajoutées")
    for w in period_works:
        if w["movement"] not in movement_names:
            movement_names.append(w["movement"])
    selected = selected + period_works
    for w in manual:
        info = licenses.get(w["commons_file"], {})
        w["image_license"], w["image_credit"] = info.get("license"), info.get("credit")
        if not is_free(w["image_license"]):
            log(f"  ⚠ œuvre manuelle « {w['title']} » : licence non libre ou introuvable ({w['image_license']})")
        w["image"] = image_url(w["commons_file"])
        if not args.skip_link_check and not link_ok(w["image"]):
            log(f"  ✗ œuvre manuelle « {w['title']} » écartée : image injoignable ({w['image']})")
            continue
        selected = [s for s in selected if s["id"] != w["id"]] + [w]
        if w["movement"] not in movement_names:
            movement_names.append(w["movement"])

    log("6/6 Notoriété et difficulté" + (" (avec vues Wikipédia)" if args.pageviews else ""))
    add_fame(selected, args.pageviews)
    easy = cfg["difficulty"]
    # Les œuvres de la liste sont connues par construction : toutes en facile (même celles déjà présentes
    # sous un autre état dans works.json). difficulty_overrides.json s'applique ensuite.
    curated_ids = {w["id"] for w in load_curated()}
    assign_levels(selected, easy["easy_min_artist_fame"], easy["easy_min_work_fame"], curated_ids)
    apply_overrides(selected)

    for w in selected:
        w["image_page"] = image_page(w["commons_file"])
        w["period"] = period_for(w, periods, cfg["movement_periods"])
    selected.sort(key=lambda w: (movement_names.index(w["movement"]), w["artist"], w["year"]))
    out = [{k: w.get(k) for k in OUTPUT_FIELDS} for w in selected]
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log(f"  {OUT_FILE.relative_to(ROOT)} : {len(out)} œuvres")

    summary(out, movement_names)
    period_summary(out, periods, cfg["movement_periods"])


if __name__ == "__main__":
    main()
