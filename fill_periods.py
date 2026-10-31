#!/usr/bin/env python3
"""Génère period_works.json : les œuvres les plus connues des artistes de period_artists.json.

Pour compléter les périodes de la frise (config.json) qui manquent d'œuvres :
  1. chaque artiste de period_artists.json est retrouvé sur Wikidata (recherche, puis vérification
     que c'est un peintre ou un sculpteur dont le nom correspond) ;
  2. SPARQL : ses peintures et sculptures avec image, triées par notoriété (sitelinks Wikidata) ;
  3. image sous licence libre (Commons), notice Wikipédia fr, requête HEAD sur l'image ;
  4. au plus `works_per_artist` œuvres par artiste, les plus connues d'abord ; les œuvres déjà dans
     data/works.json ou curated_works.json sont ignorées.

Le champ `movement` vient de period_artists.json : c'est lui qui décide de la période
(table movement_periods de config.json). Fichier généré, relancer le script le réécrit en entier.
Ensuite : python3 fetch_works.py --merge-only

Usage : python3 fill_periods.py
"""
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import fetch_works as fw
import import_list as il

ROOT = Path(__file__).parent
ARTISTS_FILE = ROOT / "period_artists.json"
OUT_FILE = ROOT / "period_works.json"

VISUAL_ARTIST = {"Q1028181", "Q1281618", "Q11569986", "Q15296811", "Q483501", "Q3391743", "Q1925963",
                 "Q16947657", "Q21550646", "Q2347178", "Q10862983", "Q16010345"}  # peintre, sculpteur, graveur, dessinateur…
CANDIDATES_PER_ARTIST = 16   # lignes gardées par artiste avant les filtres (licence, notice, image)
SPARQL_CHUNK = 12
SPARQL_ROWS = 4000


def resolve(name, entities_cache):
    ids = il.search(name, "fr")
    ents = il.get_entities([q for q in ids if q not in entities_cache])
    entities_cache.update(ents)
    best = None
    for q in ids:
        ent = entities_cache.get(q)
        if not ent or "Q5" not in il.claim_ids(ent, "P31"):
            continue
        if not (set(il.claim_ids(ent, "P106")) & VISUAL_ARTIST):
            continue
        if not il.artist_matches(name, ent):
            continue
        links = len(ent.get("sitelinks", {}))
        if best is None or links > best[1]:
            best = (q, links)
    return best[0] if best else None


def trim(out, existing_by_period, table, target):
    """Plafonne chaque période à `target` œuvres au total (existantes + nouvelles) : on prend d'abord la
    meilleure œuvre de chaque artiste, puis la deuxième, etc., les plus connues en premier."""
    by_period = defaultdict(list)
    for w in out:
        by_period[table[w["movement"]]].append(w)
    kept = []
    for period, ws in by_period.items():
        need = max(0, target - existing_by_period.get(period, 0))
        rank = Counter()
        ranked = []
        for w in sorted(ws, key=lambda w: -w["work_sitelinks"]):
            rank[w["artist_id"]] += 1
            ranked.append((rank[w["artist_id"]], -w["work_sitelinks"], w))
        kept += [w for _, _, w in sorted(ranked, key=lambda t: t[:2])[:need]]
    return kept


def existing_counts():
    """Nombre d'œuvres par période déjà dans data/works.json, hors celles qui viennent de period_works.json."""
    works = json.loads(fw.OUT_FILE.read_text(encoding="utf-8"))
    return Counter(w["period"] for w in works if w.get("source") != "period_fill")


def write(out, fw_cfg):
    table = fw_cfg["movement_periods"]
    out = sorted(out, key=lambda w: (w["movement"], w["artist"], w["year"]))
    keep = ["id", "title", "artist", "artist_id", "year", "movement", "type", "museum",
            "image", "image_page", "image_license", "image_credit",
            "notice", "notice_type", "artist_notice", "wikipedia_url",
            "work_article", "artist_article", "work_sitelinks", "artist_sitelinks", "source"]
    OUT_FILE.write_text(json.dumps([{k: w.get(k) for k in keep} for w in out], ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    fw.log(f"  {len(out)} œuvres écrites dans {OUT_FILE.name}")
    base = existing_counts()
    per_period = Counter(table[w["movement"]] for w in out)
    for p in fw_cfg["periods"]:
        fw.log(f"    {p['id']:28}{base[p['id']]:4} + {per_period[p['id']]:3} = {base[p['id']] + per_period[p['id']]:4}")


def main():
    cfg = json.loads(ARTISTS_FILE.read_text(encoding="utf-8"))
    per_artist = cfg.get("works_per_artist", 9)
    target = cfg.get("target_per_period", 60)
    fw_cfg = json.loads(fw.CONFIG_FILE.read_text(encoding="utf-8"))
    table = fw_cfg["movement_periods"]
    if "--trim" in sys.argv:  # replafonne period_works.json sans refaire les requêtes
        write(trim(json.loads(OUT_FILE.read_text(encoding="utf-8")), existing_counts(), table, target), fw_cfg)
        return
    existing = {w["id"] for w in json.loads(fw.OUT_FILE.read_text(encoding="utf-8"))}
    if fw.CURATED_FILE.exists():
        existing |= {w["id"] for w in json.loads(fw.CURATED_FILE.read_text(encoding="utf-8"))}

    fw.log("1/4 Artistes (Wikidata)")
    wanted, seen = [], set()
    for a in cfg["artists"]:
        if a["name"] in seen:
            continue
        seen.add(a["name"])
        if a["movement"] not in table:
            sys.exit(f"period_artists.json : mouvement « {a['movement']} » absent de movement_periods")
        wanted.append(a)
    cache, resolved, missing = {}, {}, []
    for a in wanted:
        q = resolve(a["name"], cache)
        if q:
            resolved[q] = a
        else:
            missing.append(a["name"])
    fw.log(f"  {len(resolved)} artistes trouvés" + (f", introuvables : {', '.join(missing)}" if missing else ""))

    fw.log("2/4 Œuvres (SPARQL)")
    by_movement = defaultdict(list)
    for q, a in resolved.items():
        by_movement[a["movement"]].append(q)
    rows = []
    for movement, ids in by_movement.items():
        for i in range(0, len(ids), SPARQL_CHUNK):
            chunk = ids[i:i + SPARQL_CHUNK]
            selector = "VALUES ?creator { " + " ".join(f"wd:{q}" for q in chunk) + " }"
            try:
                got = fw.run_query(selector, 1000, 2100, SPARQL_ROWS, movement)
            except Exception as e:  # un artiste trop volumineux ne doit pas arrêter le reste
                fw.log(f"  ⚠ {movement} {chunk} : {e}")
                continue
            rows += got
            time.sleep(1)
        fw.log(f"  {movement}: {sum(1 for r in rows if r['movement'] == movement)} lignes")
    works = fw.merge_rows(rows)
    works = [w for w in works if w["id"] not in existing]
    # Les plus connues d'abord, par artiste.
    works.sort(key=lambda w: -w["work_sitelinks"])
    kept, count = [], Counter()
    for w in works:
        if count[w["artist_id"]] < CANDIDATES_PER_ARTIST:
            count[w["artist_id"]] += 1
            kept.append(w)
    works = kept
    fw.log(f"  {len(works)} œuvres candidates")

    fw.log("3/4 Licences et notices")
    licenses = fw.fetch_licenses([w["commons_file"] for w in works])
    free = []
    for w in works:
        info = licenses.get(w["commons_file"], {})
        if fw.is_free(info.get("license")):
            w["image_license"], w["image_credit"] = info["license"], info["credit"]
            free.append(w)
    fw.log(f"  {len(free)} avec image libre")
    works = [w for w in fw.add_notices(free) if w["notice"]]
    fw.log(f"  {len(works)} avec notice")

    fw.log("4/4 Sélection et vérification des images (HEAD)")
    works.sort(key=lambda w: -w["work_sitelinks"])
    capped, count = [], Counter()
    for w in works:
        if count[w["artist_id"]] < per_artist:
            count[w["artist_id"]] += 1
            capped.append(w)
    works = trim(capped, existing_counts(), table, target + 10)
    works.sort(key=lambda w: -w["work_sitelinks"])
    out, count, dead = [], Counter(), 0
    for w in works:
        if count[w["artist_id"]] >= per_artist:
            continue
        w["image"] = fw.image_url(w["commons_file"])
        w["image_page"] = fw.image_page(w["commons_file"])
        if not fw.link_ok(w["image"]):
            dead += 1
            continue
        count[w["artist_id"]] += 1
        w["source"] = "period_fill"
        out.append(w)
        if len(out) % 50 == 0:
            fw.log(f"  {len(out)} images vérifiées")
    fw.log(f"  {dead} images injoignables")
    write(trim(out, existing_counts(), table, target), fw_cfg)


if __name__ == "__main__":
    main()
