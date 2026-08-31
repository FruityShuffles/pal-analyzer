# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What this is

A **local, zero-setup Palworld combat-score analyzer**: the tool scores/ranks a player's owned Pals (species, level, IVs, passives) for combat and suggests an element-diverse party of 5. Pals can be entered manually **or** bulk-imported from the multiplayer server save (see Save ingestion). The deliverable is a single self-contained `pal_analyzer.html` the user double-clicks — no server, no runtime Python, no network. Python is used **only at build time** to bake reference data into the HTML and to convert save files into import JSON.

**Save ingestion (added once the server `Level.sav` became available).** The earlier "no owned-Pal data exists on this machine" premise no longer holds: the user obtained the server save. `ingest_save.py` reads it offline and emits import JSON that loads through the app's "⬆ Import JSON" button — the app stays fully offline. The primary import is the combined `out/pals-all.json`: every Pal carries an `owner` (player nickname, or the owning **guild's** name for Pals assigned to a base — base workers have no `OwnerPlayerUId` in the save and are attributed container → WorkerDirector → base → guild). Per-player files are still emitted; the app has an Owners chip filter that scopes both the ranked table and the party of 5. The old "do not add save-file reading" guidance and the `docs/DATA_SOURCES.md` "Save file location and format" section are obsolete; see `docs/SAVE_INGEST.md` for the format details.

## Build pipeline

All build steps are stdlib-only (Python 3.8+, no pip installs). `build_id_maps.py`
feeds both the app's Trust data and save ingestion; `ingest_save.py` is otherwise
independent of the app build:

```bash
python data/build_data.py     # fetch wiki data -> data/pals.json + data/passives.json (needs network)
python data/build_id_maps.py  # fetch ID maps + friendship stats -> data/id_maps.json (needs network)
python build_report.py        # bake wiki + friendship JSON into pal_analyzer.html (offline)
python ingest_save.py         # Level.sav -> out/pals-<player>.json + out/ingest_review.md (needs an Oodle DLL)
```

- Run `build_data.py` only when refreshing wiki data (e.g. after a game DLC). It hits the palworld.wiki.gg Cargo API and pages transparently. It prints spot-checks (Lamball/Anubis/Mammorest/Kitsun stat lines, Aggressive passive) at the end — verify those.
- **Do not suggest rerunning `build_data.py` as a data-freshness fix.** It was last run 2026-07-18, after the v1.0 release (2026-07-10); the community wiki lags major patches by weeks-to-months, so rerunning it just re-fetches the same possibly-stale pages. When post-1.0 accuracy actually matters (changed base stats, new passives, Awakening numbers), the right direction is extracting values from the **game files themselves** (the Pak data tables, e.g. `DT_PalMonsterParameter` — the same source save editors like palworld-save-pal datamine) rather than the wiki.
- Run `build_report.py` after **any** edit to `pal_analyzer_template.html` or the JSON. It merges display-name-keyed Trust friendship stats from `data/id_maps.json` into the species records, then replaces the `/*__PALS_JSON__*/ {}` and `/*__PASSIVES_JSON__*/ {}` markers in the template with compact JSON. It hard-fails if the friendship map is absent. **`pal_analyzer.html` is generated — never hand-edit it; edit `pal_analyzer_template.html` and rebuild.**
- Run `build_id_maps.py` only when refreshing the internal-ID maps (same cadence as `build_data.py`). Source is the palworld-save-pal project (distinct from the wiki — keep its attribution); it also emits the per-species `friendship` map used by Trust scoring. Then `ingest_save.py` reads `Level.sav` + the `<UID>.sav` player saves in the folder and writes `out/` (saves can be dropped anywhere and pointed at with `--level`/`--players`/`--out`; they don't need to sit at the repo root). Its `ingest_review.md` flags any species/passive present in the save but missing from the wiki data — triage combat-relevant passives into `PASSIVE_OVERRIDES` and missing species (usually post-1.0 DLC Pals the wiki hasn't caught up on) into `SPECIES_OVERRIDES`, both in `build_data.py`. For species stats/elements, don't websearch or guess — the palworld-save-pal repo's `data/json/pals.json` (same repo `build_id_maps.py` already sources IDs from) has the exact datamined `scaling: {hp, attack, defense}` and `element_types` for every species, including ones missing from the wiki; element names need remapping (`Electricity→Electric, Earth→Ground, Leaf→Grass, Normal→Neutral`). After editing either override dict, rerun `build_data.py` → `build_report.py` → `ingest_save.py` in that order. **The `out/*.json` files hold real players' Pal rosters — treat them like `pal_analyzer.html` (never publish as an Artifact).**

## Verifying the scoring formula

`scoring_check.py` is a Python mirror of the combat-score math and the canonical formula test:

```bash
python scoring_check.py      # asserts the Mammorest/Kitsun L1-vs-L50 crossover
```

The formula lives in **three places that must stay in sync**: `docs/FORMULAS.md` (spec/ground truth), `scoring_check.py` (Python mirror), and the `statHp`/`statAttack`/`statDefense`/`combatScore` functions inside `pal_analyzer_template.html` (the only runtime copy). If you touch the math, update all three and confirm both `scoring_check.py` and the in-page `console.assert` self-test still reproduce **151.0 / 899.6** (Mammorest) and **150.6 / 901.8** (Kitsun) at L1/L50, IV=0, no passives.

Condensing, combat Soul ranks, and Trust were implemented on 2026-07-19. `docs/AUGMENTS.md` remains the ground truth for mechanics, cost curves, thresholds, and save fields; Awakening and Work Speed remain excluded.

**Wishlist / breed-to-target solver** (added 2026-08-29; `docs/WISHLIST.md` is ground truth). The third breeding question, and the inverse of the suggester: you name the Pal you want and the 1-4 passives it must have, and it returns the single cheapest route from the Pals you can actually put in a pen, measured in **total expected eggs**. Inverting the question is what makes it affordable -- with at most 4 named passives an intermediate's whole relevant state is `(species, wanted mask, junk count)`, ~24k nodes rather than every passive combination. Three things are load-bearing. **A wish is a spec and the solver does not second-guess it**: every named passive is bred, with one liberty -- a rank 1-3 `add_pal` passive is bought for 50k, which is noise against one extra hatch. There is deliberately no premium option, because if you'd spend a token on a passive you simply leave it out of the wish; this also means a 4-passive wish usually collapses to breeding *two* things, since Musclehead/Burly Body/Ferocious/Heavyweight are all 50k buys. **Junk is a price, not a wall** -- a dirty parent only enlarges the pool the wanted passives are drawn from, so where the only Legend carrier is `Legend + 2 junk`, using it dirty costs **4.0 eggs and cleaning it first costs 20.5**; requiring junk-free intermediates quotes 20 eggs for a 4-egg job. It flips only at `|D| = 4`, where the final pool must be exactly 4 (10 eggs; m=5 -> 50, m=6 -> 150), so junk is a **Pareto axis on cost, never a filter** and `acceptProb(m, k, maxExtras)` generalises `inheritProb()` with a pickiness dimension (mirrored by `p_accept()` in `breeding_check.py`). Junk on the *target* is free, since an overwrite costs the same 50k as filling an empty slot. **Gender is not a node dimension**: two bred intermediates are both unhatched so neither is targeted; only a bred parent paired with a *gender-locked* owned one pays `1/P(gender)`. The search is **anytime** -- iterative broadening, beams widening fourfold, a running cost bound from the first cheap route, and a bucketed beam (sorting on eggs alone starves the 3- and 4-passive nodes that are the only ones near the goal). It reports `converged` or `budget` honestly and **must never run from `render()`**, only from a wish's Solve button. Negative answers name their cause: the uncarried passive, or that the species is never the child of two *different* species (Frostallion, Jetragon, Blazamut Ryu -- checked up front, so it is instant rather than a 10-second dead end).

Formula gotchas (see `docs/FORMULAS.md` for why):
- Defense base constant is **50**, not 100 (the wiki article has a typo; 50 is correct).
- Structure is `floor(floor(base + slope·Level·(1+IV%)) · (1+PassiveBonus%) · (1+SoulBonus%) · (1+CondenseBonus%))` — two nested floors. Multiplier classes multiply each other inside the single outer floor.
- `IV% = TalentInt · 0.3 / 100`; passive bonuses are **additive** across a Pal's passives, stored as percent (e.g. `10`) and divided by 100 at use.
- **Max-HP passives are rare but real** — the wiki data had none (hence the old "`hp_pct` is always 0" note), but the game files list God of Destruction (−50%) and World Tree Seedbed (−20%). `passiveBonuses()` sums all three stats. HP also has an outer multiplier stage for Souls and Condensing.
- Trust changes the effective species stat to `species_stat + friendship_stat · trustRank` before level scaling.

### Verifying the app's JS logic without a browser

There's no headless browser installed. To exercise the real runtime code (scoring, party dedupe, persistence), extract the `<script>` from `pal_analyzer.html` and run it in Node with minimal `document`/`localStorage` stubs inside a `vm` context. Note: top-level `let` bindings (`state`, `optimizeBy`, `activeElements`) are **not** on the context object — append an epilogue in the same scope to expose them (e.g. `globalThis.__getState=()=>state`). Function declarations (`computeAt`, `decorate`, `normalizeEntry`, `passiveBonuses`, `save`/`load`, `renderParty`) attach to the context and are directly callable.

## Architecture

**Data flow:** wiki data from `build_data.py` + friendship data from `build_id_maps.py` → `build_report.py` → `pal_analyzer.html` (data baked inline) → runs entirely in the browser over `localStorage`.

- **`data/pals.json`** — `{ species: { hp_stat, attack_stat, defense_stat, elements: [1-2 tags] } }`. Filtered to `palVariant='Normal'` (drops Boss/Alpha). Elements come from a separate Cargo table (`PalElement`, one row per element) merged in. At bake time, `build_report.py` adds `friendship_hp` / `friendship_attack` / `friendship_defense` from `data/id_maps.json`.
- **`data/passives.json`** — `{ passive: { attack_pct, defense_pct, hp_pct, rank, add_pal, lottery_weight, element_boosts, description } }`. Only `ShotAttack`/`Defense`/`MaxHP` self-targeted effects affect scoring; all other effect types (Work Speed, Element Boost/Resist, etc.) are ignored but the full passive list is kept so the picker can offer every real passive name. `rank` + `add_pal` gate the passive planner's purchase pools (`docs/AUGMENTS.md` §5).
- **Breeding** (added 2026-07-26) — `data/pals.json` also carries `combi_rank` / `combi_priority` / `ignore_combi` / `male_probability` / `variant`, and `data/breeding.json` holds the 253 unique parent-pair overrides. `ingest_save.py` now captures `gender`. **`docs/BREEDING.md` is ground truth**; the algorithm is locked by `breeding_check.py` and cross-checked into the shipped JS by `node tools/js_check.js`. The search runs only from its button — never from `render()`.
- **Breeding reachability** (added 2026-07-28) — `tools/breed_reach.py` is a standalone offline experiment (`python tools/breed_reach.py` → `out/breed_reach.md`), **not part of the app**: given seed Pals that already carry the wanted passives, what is reachable and how many **unique breeding pairs** does it cost. **`docs/BREED_REACH.md` is ground truth** and documents the two traps that produced real bugs — every step needs a carrier parent, and plans must tag each parent as owned-clean vs bred. Run `--verify` after touching it.

**The app (`pal_analyzer_template.html`)** is one file, vanilla JS, no dependencies. Key pieces:
- **State** is a single `state = { version, targetLevel, assume:{condense,souls,trust}, pals: [...] }` object, auto-saved to `localStorage` key `palAnalyzer.v1` on every change. Entries include `condense`, `soulHp`, `soulAtk`, `soulDef`, and derived `trust`, all defaulting to 0. `normalizeEntry()` is the validation/clamp chokepoint — all writes (form, import, load) pass through it.
- **Two scores per Pal**: `CurrentScore` uses the entered level and actual augments; `TargetScore` uses the adjustable target level (default 80) and assumed-max augment toggles; `Headroom = Target − Current` is the "worth investing?" signal. Rank order is level-dependent, which is the whole point of showing both.
- **Party-of-5** dedupes by **exact** element signature (sorted element list, so `{Fire,Dragon}` and `{Fire}` are distinct; two pure-Fire Pals conflict), keeps the highest-scoring Pal per signature, and has a Current-vs-Target optimize toggle.
- **Owner filter**: entries carry an optional `owner` (player or guild); dynamic chips filter by owner and — unlike the element/text filters, which are table-only — also scope the party of 5. Importing a file with a top-level `player` stamps it onto owner-less entries.
- **Wishlist** entries are `state.wishlist = [{id, species, passives}]` through `normalizeWish()`, and the view is the third segment of the same sticky switcher. Wishes deliberately outlive the roster: import only replaces `state.pals`, and `out/` is re-ingested often.
- Species/passive inputs use native `<datalist>` for zero-dependency autocomplete.

## Constraints

- `pal_analyzer.html` must stay **fully self-contained and offline** — no CDN, no external `src`/`href` to scripts/CSS, no `fetch`/XHR. The only allowed external URLs are the inert palworld.wiki.gg and palworld-save-pal attribution links in the footer.
- `pal_analyzer.html` holds the user's personal Pal list — **never publish it as a Codex Artifact.**
- Wiki data is CC BY-SA 4.0; the generated JSON and the HTML footer carry attribution. Keep it.
- Scope is deliberately narrow (see the plan): stats + passives + implemented combat augments only, no active-skill/type-advantage math. **Breeding was added 2026-07-26** (`docs/BREEDING.md`) and the **wishlist** on 2026-08-29 (`docs/WISHLIST.md`); together they are the sanctioned exception to "no suggestions for un-entered Pals" — it proposes Pals you don't own, but only ones reachable from Pals you do. Don't expand further without asking.
