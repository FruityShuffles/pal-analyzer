#!/usr/bin/env python3
"""Bake data/pals.json + data/passives.json into pal_analyzer_template.html,
producing the self-contained deliverable pal_analyzer.html.

Per-species Trust friendship stats from data/id_maps.json are merged into any species
record that doesn't already carry them (import_gamedata.py sources them from the game
files directly); source files remain separate for attribution.

The template contains three placeholder tokens:
    const PALS_DB = /*__PALS_JSON__*/ {};
    const PASSIVES_DB = /*__PASSIVES_JSON__*/ {};
    const BREEDING_DB = /*__BREEDING_JSON__*/ {};
This replaces the `{}` after each token with the real data (the species/passives
inner objects, and the breeding table's {"unique": [...]} wrapper -- kept as an
object so it matches the same `/*TOKEN*/ {}` marker shape as the other two), so the
resulting HTML runs fully offline with no network calls.

Run: python build_report.py   (after build_data.py and build_id_maps.py have produced the JSON)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "pal_analyzer_template.html")
OUT = os.path.join(HERE, "pal_analyzer.html")


def load_inner(path, key):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get(key, data)


def inject(html, token, payload):
    marker = f"/*{token}*/ {{}}"
    if marker not in html:
        sys.exit(f"ERROR: marker not found in template: {marker!r}")
    # compact JSON keeps the file small; </script> can't appear in numeric/string data
    return html.replace(marker, f"/*{token}*/ " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def main():
    pals = load_inner(os.path.join(HERE, "data", "pals.json"), "pals")
    passives = load_inner(os.path.join(HERE, "data", "passives.json"), "passives")
    breeding = load_inner(os.path.join(HERE, "data", "breeding.json"), "breeding")
    with open(os.path.join(HERE, "data", "id_maps.json"), encoding="utf-8") as f:
        id_maps = json.load(f)
    friendship = id_maps.get("friendship")
    if not friendship:
        sys.exit("ERROR: data/id_maps.json has no 'friendship' map -- rerun data/build_id_maps.py first.")
    missing = []
    for name, rec in pals.items():
        # import_gamedata.py already carries friendship straight from the game's own
        # DataTable row, including for species data/id_maps.json hasn't caught up on.
        if "friendship_hp" in rec:
            continue
        friend = friendship.get(name)
        rec["friendship_hp"] = friend["hp"] if friend else 0
        rec["friendship_attack"] = friend["atk"] if friend else 0
        rec["friendship_defense"] = friend["def"] if friend else 0
        if not friend:
            missing.append(name)
    if missing:
        preview = ", ".join(missing[:10]) + ("..." if len(missing) > 10 else "")
        print(f"  ! {len(missing)} species without friendship data (Trust adds 0): {preview}")

    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()

    html = inject(html, "__PALS_JSON__", pals)
    html = inject(html, "__PASSIVES_JSON__", passives)
    html = inject(html, "__BREEDING_JSON__", breeding)

    # safety: no stray unresolved markers, no accidental </script> break-out
    for tok in ("__PALS_JSON__", "__PASSIVES_JSON__", "__BREEDING_JSON__"):
        if f"/*{tok}*/ {{}}" in html:
            sys.exit(f"ERROR: token {tok} left unresolved")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    size = os.path.getsize(OUT)
    print(f"Baked {len(pals)} species + {len(passives)} passives "
          f"+ {len(breeding.get('unique', []))} unique breeding combos")
    print(f"Wrote {OUT}  ({size/1024:.0f} KB, self-contained, no network)")


if __name__ == "__main__":
    main()
