#!/usr/bin/env python3
"""Transforme oeuvres_celebres_300.csv en curated_works.json (fichier généré, fusionné par fetch_works.py).

Pour chaque ligne du CSV :
  1. recherche de candidats sur Wikidata à partir du titre français et du titre anglais ;
  2. correspondance exacte (titre normalisé) ET artiste identique ; une correspondance ambiguë
     (plusieurs versions, œuvre en série, homonyme chez le même artiste) écarte la ligne ;
  3. image Commons sous licence libre dont la requête HEAD répond ;
  4. notices Wikipédia fr, comme pour les autres œuvres.

Ne modifie jamais manual_works.json. Relancer ce script régénère curated_works.json en entier.

Usage : python3 import_list.py [fichier.csv]
"""
import csv
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

import fetch_works as fw

ROOT = Path(__file__).parent
DEFAULT_CSV = ROOT / "oeuvres_celebres_300.csv"
OUT_FILE = ROOT / "curated_works.json"

SEARCH_LIMIT = 20
PAUSE = 0.1
ARTICLES = {"le", "la", "les", "l", "un", "une", "the", "a", "an", "der", "die", "das", "el", "los", "las", "il", "lo"}


def norm(text):
    """Minuscules, sans accents ni ponctuation, sans article en tête : pour comparer des titres et des noms."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    tokens = re.sub(r"[^a-z0-9]+", " ", t).split()
    while len(tokens) > 1 and tokens[0] in ARTICLES:
        tokens.pop(0)
    return " ".join(tokens)


def first_year(text):
    m = re.search(r"\d{4}", text)
    return int(m.group()) if m else None


# --- API Wikidata ---------------------------------------------------------------

def search(text, lang):
    data = fw.get_json(fw.WIKIDATA_API, {
        "action": "wbsearchentities", "format": "json", "type": "item",
        "search": text, "language": lang, "uselang": lang, "limit": SEARCH_LIMIT,
    })
    time.sleep(PAUSE)
    return [r["id"] for r in data.get("search", [])]


def get_entities(ids):
    out = {}
    ids = sorted(set(ids))
    for i in range(0, len(ids), 20):
        data = fw.get_json(fw.WIKIDATA_API, {
            "action": "wbgetentities", "format": "json", "ids": "|".join(ids[i:i + 20]),
            "props": "labels|aliases|claims|sitelinks", "languages": "fr|en",
        })
        out.update(data.get("entities", {}))
        time.sleep(PAUSE)
    return out


def claim_ids(ent, prop):
    ids = []
    for c in ent.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "id" in v:
            ids.append(v["id"])
    return ids


def claim_strings(ent, prop):
    out = []
    for c in ent.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, str):
            out.append(v)
    return out


def labels(ent):
    return [ent.get("labels", {}).get(lang, {}).get("value") for lang in ("fr", "en")]


def aliases(ent):
    return [a["value"] for lang in ("fr", "en") for a in ent.get("aliases", {}).get(lang, [])]


def fr_title(ent):
    return ent.get("sitelinks", {}).get("frwiki", {}).get("title")


# --- Correspondances ---------------------------------------------------------------

def artist_matches(csv_artist, creator):
    """Le nom du CSV et un nom (libellé ou alias, fr/en) du créateur : l'un contient l'autre, mot à mot."""
    want = set(norm(csv_artist).split())
    for name in [n for n in labels(creator) if n] + aliases(creator):
        have = set(norm(name).split())
        small, big = (want, have) if len(want) <= len(have) else (have, want)
        if small and small <= big and any(len(t) >= 4 for t in small):
            return True
    return False


def title_keys(ent, with_aliases):
    names = [n for n in labels(ent) if n]
    if with_aliases:
        names += aliases(ent)
    return {norm(n) for n in names}


def match_row(row, entities, creators):
    """Retourne (entité, id du créateur) ou (None, raison)."""
    wanted = {norm(row["titre_fr"]), norm(row["title_en"])}
    for with_aliases in (False, True):  # d'abord les libellés, puis les alias en dernier recours
        found = []
        for qid_, ent in entities.items():
            if not (title_keys(ent, with_aliases) & wanted):
                continue
            ok = [c for c in claim_ids(ent, "P170") if c in creators and artist_matches(row["artiste"], creators[c])]
            if ok:
                found.append((qid_, ent, ok[0]))
        if len(found) > 1:
            return None, "ambiguë"
        if found:
            qid_, ent, creator = found[0]
            if ent.get("claims", {}).get("P527"):  # a des parties : œuvre en série ou ensemble
                return None, "série"
            return (qid_, ent, creator), None
    return None, "introuvable"


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    print(f"{len(rows)} lignes dans {csv_path.name}", file=sys.stderr)

    # 1. Candidats par recherche, puis entités et créateurs
    candidates = {}
    for i, row in enumerate(rows, 1):
        ids = search(row["titre_fr"], "fr")
        if norm(row["title_en"]) != norm(row["titre_fr"]):
            ids += search(row["title_en"], "en")
        candidates[i] = list(dict.fromkeys(ids))
        if i % 50 == 0:
            print(f"  recherche : {i}/{len(rows)}", file=sys.stderr)
    entities = get_entities([q for ids in candidates.values() for q in ids])
    creator_ids = {c for e in entities.values() for c in claim_ids(e, "P170")}
    creators = get_entities(creator_ids)
    print(f"  {len(entities)} candidats, {len(creators)} créateurs", file=sys.stderr)

    # 2. Correspondance ligne par ligne
    rejects = Counter()
    matched = []
    seen = set()
    for i, row in enumerate(rows, 1):
        subset = {q: entities[q] for q in candidates[i] if q in entities}
        hit, reason = match_row(row, subset, creators)
        if not hit:
            rejects[reason] += 1
            continue
        qid_, ent, creator_id = hit
        files = claim_strings(ent, "P18")
        if not files:
            rejects["sans image"] += 1
            continue
        if qid_ in seen:
            rejects["doublon dans le CSV"] += 1
            continue
        seen.add(qid_)
        creator = creators[creator_id]
        artist_name = next((n for n in labels(creator) if n), row["artiste"])
        matched.append({
            "id": qid_,
            "title": row["titre_fr"].strip(),
            "artist": artist_name,
            "artist_id": creator_id,
            "year": first_year(row["annee"]),
            "movement": row["periode"].strip(),
            "type": row["type"].strip(),
            "museum": row["lieu"].strip() or None,
            "commons_file": fw.commons_filename(files[0]),
            "work_article": fr_title(ent),
            "artist_article": fr_title(creator),
            "work_sitelinks": len(ent.get("sitelinks", {})),
            "artist_sitelinks": len(creator.get("sitelinks", {})),
            "source": "curated",
        })
    print(f"  {len(matched)} correspondances", file=sys.stderr)

    # 3. Licence libre puis requête HEAD
    licenses = fw.fetch_licenses([w["commons_file"] for w in matched])
    kept = []
    for w in matched:
        info = licenses.get(w["commons_file"], {})
        if not fw.is_free(info.get("license")):
            rejects["licence non libre"] += 1
            continue
        w["image_license"], w["image_credit"] = info["license"], info["credit"]
        w["image"] = fw.image_url(w["commons_file"])
        w["image_page"] = fw.image_page(w["commons_file"])
        if not fw.link_ok(w["image"]):
            rejects["image injoignable"] += 1
            continue
        kept.append(w)
    print(f"  {len(kept)} avec image libre et joignable", file=sys.stderr)

    # 4. Notices (facultatives : sans article français, l'œuvre est gardée sans carte de notice)
    fw.add_notices(kept)

    keep = ["id", "title", "artist", "artist_id", "year", "movement", "type", "museum",
            "image", "image_page", "image_license", "image_credit",
            "notice", "notice_type", "artist_notice", "wikipedia_url",
            "work_article", "artist_article", "work_sitelinks", "artist_sitelinks", "source"]
    out = [{k: w.get(k) for k in keep} for w in kept]
    OUT_FILE.write_text(fw.json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"\n{len(out)} œuvres écrites dans {OUT_FILE.name}, {len(rows) - len(out)} écartées sur {len(rows)}")
    for reason, n in rejects.most_common():
        print(f"  écartées « {reason} » : {n}")


if __name__ == "__main__":
    main()
