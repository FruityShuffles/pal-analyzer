# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **local, zero-setup Palworld combat-score analyzer**: the tool scores/ranks a player's owned Pals (species, level, IVs, passives) for combat and suggests an element-diverse party of 5. Pals can be entered manually **or** bulk-imported from the multiplayer server save (see Save ingestion). The deliverable is a single self-contained `pal_analyzer.html` the user double-clicks — no server, no runtime Python, no network. Python is used **only at build time** to bake reference data into the HTML and to convert save files into import JSON.

**Save ingestion (added once the server `Level.sav` became available).** The earlier "no owned-Pal data exists on this machine" premise no longer holds: the user obtained the server save. `ingest_save.py` reads it offline and emits import JSON that loads through the app's "⬆ Import JSON" button — the app stays fully offline. The primary import is the combined `out/pals-all.json`: every Pal carries an `owner` (player nickname, or the owning **guild's** name for Pals assigned to a base — base workers have no `OwnerPlayerUId` in the save and are attributed container → WorkerDirector → base → guild). Per-player files are still emitted; the app has an Owners chip filter that scopes both the ranked table and the party of 5. The old "do not add save-file reading" guidance is obsolete; save format details live in `docs/SAVE_INGEST.md`.

## Build pipeline

All build steps are stdlib-only (Python 3.8+, no pip installs). `build_id_maps.py`
feeds both the app's Trust data and save ingestion; `ingest_save.py` is otherwise
independent of the app build:

```bash
python import_gamedata.py     # game-file export -> data/pals.json + data/passives.json (offline)
python data/build_id_maps.py  # fetch ID maps -> data/id_maps.json (needs network)
python build_report.py        # bake species + passive JSON into pal_analyzer.html (offline)
python ingest_save.py         # Level.sav -> out/pals-<player>.json + out/ingest_review.md (needs an Oodle DLL)
```

- **`data/pals.json` and `data/passives.json` now come from the game's own DataTables, not the wiki** (implemented 2026-07-25; `docs/GAMEDATA_EXTRACTION.md` records the plan and what actually happened). `import_gamedata.py` is stdlib-only and reads the JSON produced by `tools/gamedata/PalDataExport`, a read-only CUE4Parse dump of `Pal-Windows.pak` — see `tools/gamedata/README.md` for its prerequisites (a matching `.usmap`, an Oodle DLL, a side-installed .NET 10) and how to re-run it after a game patch. **Never write to the game install.** The extraction step is only needed when the game itself updates; `import_gamedata.py` alone is enough to regenerate the JSON from an existing export.
- `data/build_data.py` (the palworld.wiki.gg Cargo fetch, with its `SPECIES_OVERRIDES` / `PASSIVE_OVERRIDES` hand-patches) is **superseded and should not be run.** It is kept only as the fallback for a machine with no Palworld install. The wiki lagged the live game badly — the game-file import added 20 species and 19 passives the wiki never documented, corrected 10 species' base stats (Relaxaurus Defense 70 → 110, plus Relaxaurus Lux, Orserk, Grizzbolt, Jetragon, Lyleen, Lyleen Noct, Faleris, Faleris Aqua, Enchanted Sword), and made both override dicts unnecessary.
- Run `build_report.py` after **any** edit to `pal_analyzer_template.html` or the JSON. It fills in display-name-keyed Trust friendship stats from `data/id_maps.json` for any species record that lacks them (game-sourced records from `import_gamedata.py` already carry `friendship_*` straight from `DT_PalMonsterParameter`), then replaces the `/*__PALS_JSON__*/ {}` and `/*__PASSIVES_JSON__*/ {}` markers in the template with compact JSON. It hard-fails if the friendship map is absent. **`pal_analyzer.html` is generated — never hand-edit it; edit `pal_analyzer_template.html` and rebuild.**
- Run `build_id_maps.py` only when refreshing the internal-ID maps (after a game patch). Source is the palworld-save-pal project (keep its attribution); it maps the save's internal code IDs to display names for `ingest_save.py`, and still emits the `friendship` map that `build_report.py` falls back on. Then `ingest_save.py` reads `Level.sav` + the `<UID>.sav` player saves in the folder and writes `out/` (saves can be dropped anywhere and pointed at with `--level`/`--players`/`--out`; they don't need to sit at the repo root). Its `ingest_review.md` flags any species/passive present in the save but missing from `data/pals.json` / `data/passives.json`. **The fix for anything it flags is now re-running the game-data extraction, not hand-writing an override** — as of the 2026-07-25 import the report is empty. **The `out/*.json` files hold real players' Pal rosters — treat them like `pal_analyzer.html` (never publish as an Artifact).**

## Verifying the scoring formula

`scoring_check.py` is a Python mirror of the combat-score math and the canonical formula test:

```bash
python scoring_check.py      # asserts the Mammorest/Kitsun L1-vs-L50 crossover
```

The formula lives in **three places that must stay in sync**: `docs/FORMULAS.md` (spec/ground truth), `scoring_check.py` (Python mirror), and the `statHp`/`statAttack`/`statDefense`/`combatScore` functions inside `pal_analyzer_template.html` (the only runtime copy). If you touch the math, update all three and confirm both `scoring_check.py` and the in-page `console.assert` self-test still reproduce **151.0 / 899.6** (Mammorest) and **150.6 / 901.8** (Kitsun) at L1/L50, IV=0, no passives.

Condensing, combat Soul ranks, and Trust were implemented on 2026-07-19. `docs/AUGMENTS.md` remains the ground truth for mechanics, cost curves, thresholds, and save fields; Awakening and Work Speed remain excluded.

Formula gotchas (see `docs/FORMULAS.md` for why):
- Defense base constant is **50**, not 100 (the wiki article has a typo; 50 is correct).
- Structure is `floor(floor(base + slope·Level·(1+IV%)) · (1+PassiveBonus%) · (1+SoulBonus%) · (1+CondenseBonus%))` — two nested floors. Multiplier classes multiply each other inside the single outer floor.
- `IV% = TalentInt · 0.3 / 100`; passive bonuses are **additive** across a Pal's passives, stored as percent (e.g. `10`) and divided by 100 at use.
- **Max-HP passives are rare but real**: the wiki data had none (hence the old "`hp_pct` is always 0" note), but the game files list two — God of Destruction (Max HP −50%) and World Tree Seedbed (−20%). `passiveBonuses()` sums all three stats. Only effects targeting the Pal (`ToSelf`/`None`) count; `ToTrainer` ones buff the *player* and are dropped at import.
- Trust changes the effective species stat to `species_stat + friendship_stat · trustRank` before level scaling.

### Verifying the app's JS logic without a browser

There's no headless browser installed. To exercise the real runtime code (scoring, party dedupe, persistence), extract the `<script>` from `pal_analyzer.html` and run it in Node with minimal `document`/`localStorage` stubs inside a `vm` context. Note: top-level `let` bindings (`state`, `optimizeBy`, `activeElements`) are **not** on the context object — append an epilogue in the same scope to expose them (e.g. `globalThis.__getState=()=>state`). Function declarations (`computeAt`, `decorate`, `normalizeEntry`, `passiveBonuses`, `save`/`load`, `renderParty`) attach to the context and are directly callable.

## Architecture

**Data flow:** game DataTables via `tools/gamedata/PalDataExport` → `import_gamedata.py` → `data/pals.json` + `data/passives.json` → `build_report.py` → `pal_analyzer.html` (data baked inline) → runs entirely in the browser over `localStorage`. `build_id_maps.py` feeds `ingest_save.py`'s ID → display-name mapping on a separate track.

- **`data/pals.json`** — `{ species: { hp_stat, attack_stat, defense_stat, elements: [1-2 tags], friendship_hp, friendship_attack, friendship_defense } }`. From `DT_PalMonsterParameter`: `Hp` / `ShotAttack` / `Defense` (the displayed "Attack" is ShotAttack — no Pal passive touches MeleeAttack) and `ElementType1/2` in primary-first order, remapped `Electricity→Electric, Earth→Ground, Leaf→Grass, Normal→Neutral`. One record per **tribe**, keeping the row whose key *is* the tribe id — that drops `BOSS_`/`PREDATOR_`/`GYM_`/`RAID_`/oilrig/quest variants, reproducing the old `palVariant='Normal'` filter. Rows with no English name (unreleased content) are skipped.
- **`data/passives.json`** — `{ passive: { attack_pct, defense_pct, hp_pct, rank, description } }`. From `DT_PassiveSkill_Main`, filtered to `Category == SortDisplayable` (the game's own "the UI shows this on a Pal" flag — the other ~1790 rows are test/internal/equipment-only). Only `ShotAttack` / `Defense` / `MaxHP` effects feed scoring; every other effect type (Work Speed, Element Boost/Resist, status) is ignored but the passive is still listed so the picker offers every real name. ~45 passives ship an authored description; the rest are rebuilt from their effect rows.

**The app (`pal_analyzer_template.html`)** is one file, vanilla JS, no dependencies. Key pieces:
- **State** is a single `state = { version, targetLevel, assume:{condense,souls,trust}, pals: [...] }` object, auto-saved to `localStorage` key `palAnalyzer.v1` on every change. Entries include `condense`, `soulHp`, `soulAtk`, `soulDef`, and derived `trust`, all defaulting to 0. `normalizeEntry()` is the validation/clamp chokepoint — all writes (form, import, load) pass through it.
- **Two scores per Pal**: `CurrentScore` uses the entered level and actual augments; `TargetScore` uses the adjustable target level (default 80) and assumed-max augment toggles; `Headroom = Target − Current` is the "worth investing?" signal. Rank order is level-dependent, which is the whole point of showing both.
- **Party-of-5** dedupes by **exact** element signature (sorted element list, so `{Fire,Dragon}` and `{Fire}` are distinct; two pure-Fire Pals conflict), keeps the highest-scoring Pal per signature, and has a Current-vs-Target optimize toggle.
- **Owner filter**: entries carry an optional `owner` (player or guild); dynamic chips filter by owner and — unlike the element/text filters, which are table-only — also scope the party of 5. Importing a file with a top-level `player` stamps it onto owner-less entries.
- Species/passive inputs use native `<datalist>` for zero-dependency autocomplete.

## Constraints

- `pal_analyzer.html` must stay **fully self-contained and offline** — no CDN, no external `src`/`href` to scripts/CSS, no `fetch`/XHR. The only allowed external URLs are the inert palworld.wiki.gg and palworld-save-pal attribution links in the footer.
- `pal_analyzer.html` holds the user's personal Pal list — **never publish it as a Claude Artifact.**
- Species/passive data is extracted from the game's own files, so the wiki's CC BY-SA 4.0 terms no longer apply to it — but `data/*.json` records the game build it came from, and the palworld-save-pal attribution stays wherever `data/id_maps.json` is used. Keep both. The wiki link in the HTML footer is now historical; do not remove attribution without checking what still sources from where.
- Scope is deliberately narrow (see the plan): stats + passives + implemented combat augments only, no active-skill/type-advantage math, no breeding solver, no suggestions for un-entered Pals. Don't expand without asking.
