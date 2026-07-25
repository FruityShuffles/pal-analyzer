# Data Sources — Reference

## Species stats and passive skills: palworld.wiki.gg Cargo API

### Decision

Use **palworld.wiki.gg's public Cargo query API**. Do not use community GitHub datasets, and do not self-extract from the local game install.

Three candidate GitHub datasets were evaluated and rejected: `blaynem/paldex`, `jhideki/palworld-api`, `mlg404/palworld-paldex-api`. All three are stale (last updated ~February 2024, predating the Feybreak DLC), and none clearly exposes structured per-stat passive-skill percentages.

Self-extracting from the local game install was also investigated and rejected. `E:\SteamLibrary\steamapps\common\Palworld\Pal\Content\Paks\Pal-Windows.pak` is one monolithic ~40GB pak file with no bundled `.usmap`. This machine has no pak-extraction tooling installed (checked PATH and pip — nothing found). Doing it properly would require installing new third-party software (FModel + a community-maintained `.usmap`, or repak + UAssetAPI) plus manual GUI steps that can't be scripted/automated. The user was asked and chose the wiki-API route instead.

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

palworld.wiki.gg content is CC BY-SA 4.0 (confirmed from the page footer). The compiled `data/pals.json` / `data/passives.json` files should include a comment/attribution noting the source URL.

## Save file location and format

> **SUPERSEDED (2026-07-18) — this entire section is historical, not a build target.** The project pivoted away from reading save files: the user plays on a multiplayer server they do not host, so their owned-Pal data (levels/IVs/passives) is not on this machine (see "SHOW-STOPPER" finding below for the full investigation). The tool now takes its Pal data from **manual user entry via a Pal Picker UI** instead — see the current plan file. Nothing below is needed to build the current tool; it is kept only as the record of why the save-reading approach was abandoned. The Oodle-decompression finding may be useful if save-reading is ever revived. **The wiki Cargo API section above is still fully current and IS the reference the tool uses.**

### Confirmed path on this machine

```
C:\Users\adria\AppData\Local\Pal\Saved\SaveGames\76561198000759941\95922E27B18043E69A68B12720E931B6\LocalData.sav
```

Confirmed by directly listing the filesystem, not from documentation. This is the currently-active world (most recently modified, with ongoing ~30-minute autosave backups at the time of this research). Two other, older/inactive world folders exist under the same Steam ID — the tool's `--save` flag should accept a **folder** path (the world GUID folder) and look for `LocalData.sav` inside it, defaulting to the path above if omitted, but must not hardcode it as the only option.

### Important correction to common assumptions

Community documentation of Palworld saves generally describes a `Level.sav` file plus a separate `Players/<id>.sav` per player. **That is not what this machine's actual save contains.** This save format instead uses a single `LocalData.sav` per world folder — no `Level.sav` and no `Players/` subfolder were found anywhere under this world. This is presumably a newer/consolidated single-player save format. **Do not assume the `Level.sav` / `CharacterSaveParameterMap` structure described in older palworld-save-tools documentation still applies without checking directly against a real loaded save.**

### Parsing library

PyPI package `palworld-save-tools`, version `0.24.0`. **NOTE: 0.24.0 cannot decompress this machine's saves** — see the format finding below. Its `GvasFile.read` / GVAS property parser is still usable *after* the file has been Oodle-decompressed out-of-band, but its `decompress_sav_to_gvas` rejects the `PlM` magic.

### RESOLVED (2026-07-18): save format + the show-stopping content finding

**The save-file discovery task was run against the real `LocalData.sav`. Two things were found.**

**(1) Compression format is Oodle (`PlM`), not zlib (`PlZ`).** Since Palworld v0.6 the client writes saves with Oodle compression. The 12-byte header is unchanged from the classic format:
```
[0:4]  uncompressed_len (uint32 LE)   e.g. 5,272,039
[4:8]  compressed_len   (uint32 LE)   e.g. 61,044  (== filesize - 12)
[8:11] magic  = b"PlM"   (was b"PlZ")
[11]   save_type = 0x31
[12:]  Oodle-compressed GVAS body
```
`palworld-save-tools==0.24.0` only handles `PlZ`. To decompress: call `OodleLZ_Decompress` from an `oo2core_9_win64.dll` via `ctypes` (Palworld statically links Oodle — no DLL ships with it; a compatible `oo2core_9_win64.dll` was found at `C:\Program Files (x86)\Steam\steamapps\common\ELDEN RING NIGHTREIGN\Game\oo2core_9_win64.dll`). Decompression of the real file succeeded and produced a valid `GVAS\x03...` stream. A working ctypes wrapper lives in the scratchpad (`oodle_decomp.py`).

**(2) SHOW-STOPPER: `LocalData.sav` contains NO owned-Pal instance data.** The save's class is `/Script/Pal.PalLocalWorldSaveGame`. Its complete top-level contents are:
- `PalLocalSaveData.Local_ActivateOtomoCount` — a `MapProperty` of `EPalTribeID` → count
- `PalLocalSaveData.Local_PalEncountFlag` — a `MapProperty` of `EPalTribeID` → bool (the Paldeck: which species have been *encountered*)
- `SaveData.WorldMapUISaveDataMap` — client-side map-exploration UI reveal state

Confirmed searches over the fully decompressed 5.27 MB GVAS returned **zero** occurrences of `CharacterSaveParameterMap`, `Talent_HP`, `Talent_Melee`, `Talent_Shot`, `Talent_Defense`, `PassiveSkillList`, `CharacterID`, `Level`, `IndividualId`, or `PalContainerId`. **There are no per-Pal instances, levels, IVs/Talents, or passives anywhere in this file.**

**Why:** the user plays on a multiplayer server they do **not** host. Owned-Pal instance records are stored server-side (in the server's `Level.sav` `CharacterSaveParameterMap` + `Players/<playerGUID>.sav`), which do not exist on this machine. Every world folder under this Steam ID contains only `LocalData.sav` (this same client-local, Paldeck+map format) — there is no local `Level.sav` and no full-world save anywhere on this PC.

**Implication:** `save_reader.py` as originally specified cannot be built from any file on this machine. Building the intended combat-score tool requires obtaining the **server's** save files (`Level.sav` + the relevant `Players/*.sav`) from whoever hosts the server. Those server saves may themselves be `PlM`/Oodle-compressed (use the decompressor above) but *will* contain the classic `CharacterSaveParameterMap` structure the original plan's `save_reader.py` steps were written for.
