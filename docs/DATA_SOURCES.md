# Data Sources — Reference

## Species stats and passive skills: the game's own DataTables

### Decision (current, since 2026-07-25)

`data/pals.json` and `data/passives.json` are extracted from **Palworld's own cooked
DataTables** in `Pal-Windows.pak` — `DT_PalMonsterParameter` and `DT_PassiveSkill_Main`,
the same tables the wiki and the save editors both derive from. How to run the extraction
is in **`tools/gamedata/README.md`**; why and how the approach was chosen and verified is
in **`docs/GAMEDATA_EXTRACTION.md`**.

This replaced the palworld.wiki.gg Cargo API (documented below, still the code path in
`data/build_data.py`). The wiki had fallen well behind the live game: the switch added 20
species and 19 passives it never documented, corrected 10 species' base stats, and made
the hand-maintained `SPECIES_OVERRIDES` / `PASSIVE_OVERRIDES` patches unnecessary.

Cross-checked against `oMaN-Rod/palworld-save-pal`'s independent datamine: **407 species
rows agreed exactly** on base stats, Trust friendship coefficients, and element types.

### Superseded: the palworld.wiki.gg Cargo API

Everything from here to the licensing note describes the earlier wiki pipeline. It is
kept as the documented fallback for a machine with no Palworld install, and because
`data/build_data.py` still implements it. Community GitHub datasets were and remain
rejected: `blaynem/paldex`, `jhideki/palworld-api`, `mlg404/palworld-paldex-api` are all
stale (last updated ~February 2024, predating the Feybreak DLC), and none clearly exposes
structured per-stat passive-skill percentages.

### The API

Base endpoint: `https://palworld.wiki.gg/api.php?action=cargoquery&format=json`

This was discovered by reading the raw Lua source behind the wiki's own data-rendering templates — not guessed. If you ever need to re-derive table/field names yourself, fetch:
```
https://palworld.wiki.gg/wiki/Module:Pal_Query?action=raw
https://palworld.wiki.gg/wiki/Module:Passive_Skills_Query?action=raw
```
and look for `cargoUtil.queryData({ tables = ..., fields = ... })` calls.

Four tables matter for this project:

#### `PalStat` — per-species growth coefficients

These are `HP_Stat` / `Attack_Stat` / `Defense_Stat` from `FORMULAS.md`.

```
GET https://palworld.wiki.gg/api.php?action=cargoquery&tables=PalStat&fields=palName,baseHp,baseAttack,baseDefense,palVariant&where=palVariant=%27Normal%27&limit=5000&format=json
```

Verified real sample response (captured during research):
```json
{"cargoquery":[
  {"title":{"palName":"Amione","baseHp":"65","baseAttack":"70","baseDefense":"65","palVariant":"Normal"}},
  {"title":{"palName":"Anubis","baseHp":"120","baseAttack":"130","baseDefense":"100","palVariant":"Normal"}},
  {"title":{"palName":"Arsox","baseHp":"85","baseAttack":"95","baseDefense":"95","palVariant":"Normal"}}
]}
```

`Anubis` (120/130/100) and `Lamball` (70/70/70, checked separately) both matched values hand-derived earlier in the research conversation exactly — trust this table.

`palVariant='Normal'` filters out Boss/Alpha variants. A handful of Alpha forms have meaningfully different stats (e.g. `BOSS_IceHorse` has 420 HP vs. 140 for the normal form) — Boss variants are out of scope for this tool, ignore them entirely. Filtering this way returns roughly 140+ distinct species rows, consistent with the current (Feybreak-era) full roster.

#### `PalElement` — element type(s) per species

One row per element per Pal — naturally handles dual-typed Pals (e.g. Water/Ice) as two separate rows.

```
GET https://palworld.wiki.gg/api.php?action=cargoquery&tables=PalElement&fields=palName,element&limit=10000&format=json
```

#### `PassiveSkillEffect` — structured, signed, per-stat passive bonuses

This is exactly the `{attack_pct, defense_pct, hp_pct}` shape `scoring.py` needs.

```
GET https://palworld.wiki.gg/api.php?action=cargoquery&tables=PassiveSkillEffect&fields=passiveSkillName,stat,value,valueType&limit=5000&format=json
```

Verified real sample rows (captured during research):
```json
{"passiveSkillName":"Aggressive","stat":"Attack","value":"10","valueType":"percent"}
{"passiveSkillName":"Aggressive","stat":"Defense","value":"-10","valueType":"percent"}
{"passiveSkillName":"Brittle","stat":"Defense","value":"-20","valueType":"percent"}
{"passiveSkillName":"Demon God","stat":"Attack","value":"30","valueType":"percent"}
{"passiveSkillName":"Demon God","stat":"Defense","value":"5","valueType":"percent"}
```

Some passives affect two stats — the same `passiveSkillName` repeats with a different `stat` row. Many rows have non-combat `stat` values that should be read but ignored for scoring: `Work Speed`, `Element Boost <Type>`, `Element Resist <Type>`, `Full Stomatch Decrease` (that typo is in the wiki's own data, not a transcription error here), `Sanity Decrease`, `Swim Speed`, etc. For scoring, only sum rows where `stat` is exactly `"Attack"` or `"Defense"`.

**RESOLVED (2026-07-18)**: pulled the full `PassiveSkillEffect` table (no `where` filter) — 114 rows. There is **no HP-boosting passive at all**. The complete set of distinct `stat` values is: `Active Skill Cool Time Decrease`, `Attack`, `Breed Speed`, `Defense`, `Element Boost <Type>` (Dark/Dragon/Electric/Fire/Grass/Ground/Ice/Neutral/Water), `Element Resist <Type>` (same 9 types), `Farming Work Suitability`, `Full Stomatch Decrease` [sic], `Life Steal`, `Logging`, `Mining`, `Movement Speed`, `Pal and Player Auto Health Regeneration Rate`, `Pal SP Increase`, `Sanity Decrease`, `Sell Price`, `Shop Buy Price Money Increase`, `Shop Sell Price Money Increase`, `Swim Speed`, `Work Speed`. The only combat-stat percent rows are `stat == "Attack"` and `stat == "Defense"` (all `valueType == "percent"`). **There is no max-HP passive** — the closest is `Pal and Player Auto Health Regeneration Rate` (regen, not max HP) and `Life Steal`, neither of which is a max-HP multiplier. **Consequence: `HP_PassiveBonus%` in the `FORMULAS.md` growth formula is always 0** for every real passive. `build_data.py` should still write an `hp_pct` field to `passives.json` (always 0.0) for schema symmetry, but only `Attack`/`Defense` rows ever contribute.

#### `PassiveSkill` — rank/description (informational only)

```
GET https://palworld.wiki.gg/api.php?action=cargoquery&tables=PassiveSkill&fields=passiveSkillName,rank,description&limit=1000&format=json
```

Not required for scoring, but cheap to grab alongside the others and useful for display in the report.

### License

palworld.wiki.gg content is CC BY-SA 4.0 (confirmed from the page footer), and anything
built from it must carry that attribution. **The current `data/pals.json` /
`data/passives.json` are no longer wiki-derived**, so CC BY-SA does not apply to them;
their `_attribution` / `_source` fields instead name the game build they were extracted
from. If `data/build_data.py` is ever run again, its output *is* wiki content and the
CC BY-SA attribution comes back with it. The palworld-save-pal attribution on
`data/id_maps.json` is unaffected — that file is still sourced from that project.

## Save file location and format

Moved. Save ingestion (the server `Level.sav` → import JSON pipeline, container format,
and Oodle decompression) is documented in **`docs/SAVE_INGEST.md`**. The earlier
"owned-Pal data isn't on this machine" finding here was specific to the client-local
`LocalData.sav` and no longer holds once the server save was obtained.
