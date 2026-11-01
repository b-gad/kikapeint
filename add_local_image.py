#!/usr/bin/env python3
"""Ajoute au quiz une œuvre dont tu fournis toi-même l'image (fichier, capture d'écran...).

  python3 add_local_image.py <fichier> --title "..." --artist "..." --year 1951 --movement "..." [--qid Q123] [--artist-id Q123]
                             [--type peinture|sculpture] [--museum "..."]

- l'image est copiée dans images_local/ sous le nom <artiste>-<titre>.jpg (minuscules, sans accents ni espaces) ;
  le fichier d'origine n'est jamais modifié. Hors JPEG de 1600 px maximum, elle est convertie en JPEG
  de 1600 px maximum (Pillow, ou sips sur Mac pour HEIC) ; si aucune conversion n'est possible, elle est copiée telle quelle ;
- --qid (identifiant Wikidata de l'œuvre) permet de retrouver l'artiste, la notoriété et la notice Wikipédia ;
- l'œuvre reçoit image_local, image_license « Non libre (usage privé) » et private: true ;
- les œuvres sont listées dans private_works.json et regroupées dans data/works_private.json, que le quiz charge
  s'il existe. images_local/, private_works.json et data/works_private.json sont suivis par git : après un commit
  et un push, ces œuvres apparaissent aussi sur le site en ligne.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import fetch_works as fw
import import_list as il

ROOT = Path(__file__).parent
IMAGES_DIR = ROOT / "images_local"
PRIVATE_FILE = ROOT / "private_works.json"
OUT_FILE = ROOT / "data" / "works_private.json"
MAX_SIDE = 1600
LICENSE = "Non libre (usage privé)"
CREDIT = "image fournie par l'utilisateur"
OUTPUT_FIELDS = fw.OUTPUT_FIELDS + ["image_local", "private"]


def slugify(text):
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def import_image(src, dest):
    """Copie ou convertit `src` vers `dest` (.jpg). Retourne une description de ce qui a été fait."""
    dest.parent.mkdir(exist_ok=True)
    try:
        from PIL import Image, ImageOps
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            if src.suffix.lower() in (".jpg", ".jpeg") and max(im.size) <= MAX_SIDE:
                shutil.copyfile(src, dest)
                return "copiée telle quelle"
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            im.convert("RGB").save(dest, "JPEG", quality=88)
            return f"convertie en JPEG ({im.size[0]}×{im.size[1]})"
    except Exception:  # format inconnu de Pillow (HEIC...) : sips sur Mac
        pass
    if shutil.which("sips"):
        r = subprocess.run(["sips", "-s", "format", "jpeg", "-Z", str(MAX_SIDE), str(src), "--out", str(dest)],
                           capture_output=True)
        if r.returncode == 0 and dest.exists():
            return "convertie avec sips"
    shutil.copyfile(src, dest)
    return "copiée telle quelle (conversion impossible)"


def build(entry, existing, cfg, periods):
    w = dict(entry)
    ent = il.get_entities([w["id"]]).get(w["id"]) if w["id"].startswith("Q") else None
    if ent:
        creators = il.claim_ids(ent, "P170")
        artist = il.get_entities(creators[:1]).get(creators[0]) if creators else None
        w["artist_id"] = w.get("artist_id") or (creators[0] if creators else "private-" + slugify(w["artist"]))
        w["work_article"] = il.fr_title(ent)
        w["artist_article"] = il.fr_title(artist) if artist else None
        w["work_sitelinks"] = len(ent.get("sitelinks", {}))
        w["artist_sitelinks"] = len(artist.get("sitelinks", {})) if artist else 0
    else:
        w.setdefault("artist_id", "private-" + slugify(w["artist"]))
        artist = il.get_entities([w["artist_id"]]).get(w["artist_id"]) if w["artist_id"].startswith("Q") else None
        w.update(work_article=None, artist_article=il.fr_title(artist) if artist else None, work_sitelinks=0,
                 artist_sitelinks=len(artist.get("sitelinks", {})) if artist else 0)
    fw.add_notices([w])
    w["work_fame"], w["artist_fame"] = w["work_sitelinks"], w["artist_sitelinks"]
    easy = cfg["difficulty"]
    rest = sorted((x["work_fame"], x["artist_fame"]) for x in existing if x["difficulty"] != fw.LEVELS[0])
    median = rest[len(rest) // 2] if rest else (0, 0)
    is_easy = w["artist_fame"] >= easy["easy_min_artist_fame"] and w["work_fame"] >= easy["easy_min_work_fame"]
    w["difficulty"] = fw.LEVELS[0] if is_easy else fw.LEVELS[1] if (w["work_fame"], w["artist_fame"]) >= median else fw.LEVELS[2]
    w["difficulty_source"] = "computed"
    fw.apply_overrides([w])
    w["period"] = fw.period_for(w, periods, cfg["movement_periods"])
    return w


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", nargs="?", help="chemin du fichier image")
    ap.add_argument("--title"), ap.add_argument("--artist"), ap.add_argument("--year", type=int)
    ap.add_argument("--movement"), ap.add_argument("--qid", help="identifiant Wikidata de l'œuvre")
    ap.add_argument("--type", default="peinture"), ap.add_argument("--museum")
    ap.add_argument("--artist-id", help="identifiant Wikidata de l'artiste (pour le relier à ses autres œuvres)")
    ap.add_argument("--rebuild", action="store_true", help="régénère seulement data/works_private.json")
    args = ap.parse_args()

    cfg = json.loads(fw.CONFIG_FILE.read_text(encoding="utf-8"))
    periods = fw.load_periods(cfg)
    entries = json.loads(PRIVATE_FILE.read_text(encoding="utf-8")) if PRIVATE_FILE.exists() else []

    if args.image:
        missing = [k for k in ("title", "artist", "year", "movement") if not getattr(args, k)]
        if missing:
            sys.exit("Il manque : " + ", ".join("--" + k for k in missing))
        if args.movement not in cfg["movement_periods"]:
            fw.log(f"  ⚠ mouvement « {args.movement} » absent de movement_periods : période d'après l'année")
        src = Path(args.image).expanduser()
        name = f"{slugify(args.artist)}-{slugify(args.title)}.jpg"
        fw.log(f"  {src.name} → images_local/{name} : {import_image(src, IMAGES_DIR / name)}")
        entry = {
            "id": args.qid or "private-" + slugify(args.artist + " " + args.title),
            "title": args.title, "artist": args.artist, "year": args.year, "movement": args.movement,
            "type": args.type, "museum": args.museum,
            **({"artist_id": args.artist_id} if args.artist_id else {}),
            "image": f"images_local/{name}", "image_local": f"images_local/{name}", "image_page": None,
            "image_license": LICENSE, "image_credit": CREDIT, "private": True, "source": "private",
        }
        entries = [e for e in entries if e["id"] != entry["id"]] + [entry]
        PRIVATE_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    elif not args.rebuild:
        ap.error("donne un fichier image, ou --rebuild")

    manual = json.loads(fw.MANUAL_FILE.read_text(encoding="utf-8")) if fw.MANUAL_FILE.exists() else []
    seen = {e["id"] for e in entries}
    entries = entries + [e for e in manual if e.get("image_local") and e["id"] not in seen]
    public = json.loads(fw.OUT_FILE.read_text(encoding="utf-8"))
    built = [build(e, public, cfg, periods) for e in entries]
    OUT_FILE.write_text(json.dumps([{k: w.get(k) for k in OUTPUT_FIELDS} for w in built], ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    for w in built:
        fw.log(f"  prête : {w['title']} — {w['artist']} ({w['year']}) · période {w['period']} · niveau {w['difficulty']}")


if __name__ == "__main__":
    main()
