# 🐑 Palworld Combat-Score Analyzer

A local, zero-setup tool that scores and ranks your Palworld Pals for combat, suggests an
element-diverse party of 5, and works out what to breed next.

**Download [`pal_analyzer.html`](pal_analyzer.html), double-click it, done.** It is a single
self-contained file — no server, no install, no build step, no network access. Your Pals stay
in your own browser's `localStorage` and never leave the machine.

<!-- screenshot goes here -->

## What it does

Three views, one roster:

- **Roster** — every Pal ranked by a combat score derived from the game's real stat formula.
  Each Pal gets a **CurrentScore** (its actual level and augments) and a **TargetScore** (an
  adjustable target level, default 80, with maxed augments assumed). The gap between them is
  **Headroom** — the "is this one worth investing in?" signal. Rank order genuinely changes
  with level, which is the whole point of showing both. Filter by element, text, or owner;
  the party-of-5 picker dedupes by exact element signature so you don't field three Fire Pals.
- **Breeding** — "what should I *make*?" Scans your roster for parent pairs whose child could
  inherit passives that are either unbuyable or expensive, and ranks the results by score, then
  eggs, then gold. Every suggestion resolves to concrete Pals you actually own, with genders.
- **Wishlist** — the inverse: name the Pal you want and the 1–4 passives it must have, and it
  finds the cheapest breeding route from Pals you can actually put in a pen, measured in total
  expected eggs. Impossible wishes say *why* (nobody carries that passive; that species is
  never the child of two different species).

Augments modelled: Condensing, combat Soul ranks, Trust, and the passive planner (which
passives to buy into a Pal's four slots). Awakening and Work Speed are deliberately out of
**scoring** scope, as is active-skill and type-advantage damage math.

Passives themselves are described in full, though: every passive carries its complete
effect list straight from the game's DataTables, so the picker and the hover tooltips show
what a passive *actually* does — Musclehead reads "Attack +30%. Work Speed -50%.", not just
the half that scores. Nothing scored changed; see [`DATA_SOURCES.md`](docs/DATA_SOURCES.md).

## Getting your Pals in

Type them in by hand, or bulk-import from a save.

`ingest_save.py` reads a Palworld `Level.sav` (single-player or dedicated server) fully offline
and writes import JSON that loads through the app's **⬆ Import JSON** button:

```bash
python ingest_save.py --level path/to/Level.sav --players path/to/Players --out out/
```

Import `out/pals-all.json` for everyone on the server — each Pal carries an `owner` (the player's
nickname, or the owning guild's name for base workers), and the app's owner chips filter both the
table and the party suggestion. Per-player files are written too. `out/ingest_review.md` flags
anything in the save that the reference data doesn't know about.

This needs an Oodle decompression DLL, which ships with the game — see
[`docs/SAVE_INGEST.md`](docs/SAVE_INGEST.md). Everything written to `out/` is real roster data and
is gitignored.

## Rebuilding from source

`pal_analyzer.html` is **generated** — edit `pal_analyzer_template.html` and rebuild. Every build
step is Python 3.8+ standard library only; there is nothing to `pip install`.

```bash
python import_gamedata.py     # game-file export -> data/pals.json + passives.json + breeding.json
python data/build_id_maps.py  # refresh save-file ID maps -> data/id_maps.json  (needs network)
python build_report.py        # bake the JSON into pal_analyzer.html            (offline)
```

`import_gamedata.py` consumes a JSON dump produced by `tools/gamedata/PalDataExport`, a read-only
CUE4Parse extraction of your own `Pal-Windows.pak`. You only need to re-run that after a game
patch; see [`tools/gamedata/README.md`](tools/gamedata/README.md) for its prerequisites. It never
writes to the game install.

### Tests

The scoring and breeding math is mirrored in Python and locked by fixtures, and the shipped
JavaScript is exercised in a `vm` sandbox — there's no browser dependency:

```bash
python scoring_check.py     # combat-score formula lock
python breeding_check.py    # breeding algorithm + probability lock
node tools/js_check.js      # runs the shipped JS: cross-checks both, plus search invariants
```

The combat formula lives in three places that must stay in sync — [`docs/FORMULAS.md`](docs/FORMULAS.md)
(the spec), `scoring_check.py` (the Python mirror), and the runtime copy in the template. If you
touch the math, update all three.

## Docs

The `docs/` folder is the ground truth for everything the code assumes:

| | |
|---|---|
| [`FORMULAS.md`](docs/FORMULAS.md) | the stat and combat-score math, and why it's shaped that way |
| [`AUGMENTS.md`](docs/AUGMENTS.md) | Condensing, Souls, Trust, passive costs and thresholds |
| [`BREEDING.md`](docs/BREEDING.md) | child-species rules, inheritance probability, the suggester |
| [`WISHLIST.md`](docs/WISHLIST.md) | the breed-to-target solver |
| [`BREED_REACH.md`](docs/BREED_REACH.md) | a standalone reachability experiment (`tools/breed_reach.py`) |
| [`SAVE_INGEST.md`](docs/SAVE_INGEST.md) | save format, container layout, the ingest pipeline |
| [`DATA_SOURCES.md`](docs/DATA_SOURCES.md) | where each data file comes from |
| [`GAMEDATA_EXTRACTION.md`](docs/GAMEDATA_EXTRACTION.md) | how the game-file extraction was built |

## Data and attribution

- `data/pals.json`, `data/passives.json` and `data/breeding.json` are extracted from Palworld's
  own DataTables. They were cross-checked against two independent datamines: 407 species rows
  agreed exactly with [`oMaN-Rod/palworld-save-pal`](https://github.com/oMaN-Rod/palworld-save-pal),
  and the derived breeding table agreed with [`tylercamp/palcalc`](https://github.com/tylercamp/palcalc)
  on all 44,552 shared parent pairs with zero mismatches.
- `data/id_maps.json` (internal save IDs → display names) comes from
  [palworld-save-pal](https://github.com/oMaN-Rod/palworld-save-pal), MIT licensed — keep that
  attribution wherever the file is used.
- Palworld is © Pocketpair, Inc. This is an unofficial fan tool, not affiliated with or endorsed
  by Pocketpair. The extracted game data under `data/` remains Pocketpair's and is included for
  interoperability; the MIT license below covers this project's own code, not that data.

## License

MIT — see [LICENSE](LICENSE).
