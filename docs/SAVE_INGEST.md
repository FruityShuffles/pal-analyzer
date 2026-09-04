# Save ingestion (`ingest_save.py`)

Converts the multiplayer server's world save into per-player import JSON for
`pal_analyzer.html`. Offline, stdlib-only, plus one Oodle DLL (see below).

## Inputs / outputs

```
Level.sav                 # world save (the Pal roster lives here)
<UID>000…0.sav  ×N        # per-player saves; filename UID prefix = the owner key
        │  python ingest_save.py
        ▼
out/pals-all.json         # PRIMARY import: all players' Pals + base-assigned Pals,
                          # each entry tagged "owner" (player nickname or guild name)
out/pals-<Player>.json    # one file per player  ({version,targetLevel,player,pals:[…]})
out/ingest_review.md      # species/passives in the save missing from the reference data
```

Each output Pal entry includes `condense`, `soulHp`, `soulAtk`, `soulDef`, and
derived `trust` in addition to species, owner, level, IVs, and passives.

Import `pals-all.json` via the app's **⬆ Import JSON** button and use the in-app
**Owners** chips to filter by player/guild (the owner filter also scopes the suggested
party). Per-player files still import fine — the app stamps their top-level `player`
onto entries as the owner. The app never reads the save itself.

## Save container format (the non-obvious part)

Palworld saves are **not** the usual `PlZ`+zlib that `palworld-save-tools` expects. This
server's files use:

```
offset 0   uint32  uncompressed_len   (little-endian)
offset 4   uint32  compressed_len     (== filesize - 12)
offset 8   char[4] "PlM1"             magic
offset 12  …       Oodle-Kraken stream
```

Decompressing the stream from offset 12 yields the raw **GVAS** (`b"GVAS"` at byte 0).
`Level.sav` here is 1.47 MB compressed → **25,178,830 bytes** GVAS.

Oodle is proprietary, so decompression goes through a game's `oo2core_*_win64.dll` via
`ctypes` (still no pip dependency — the DLL is the user's own game file, never
redistributed). **Palworld itself ships no such DLL** (UE5 links Oodle internally), so
`ingest_save.py` searches other installed games for any `oo2core_*_win64.dll`; pass one
explicitly with `--oodle PATH` if the search fails.

## GVAS parsing

Owned Pals live in `worldSaveData.CharacterSaveParameterMap`. Each entry's value is a
`RawData` byte array holding a nested, **uncompressed** tagged-property stream, so the
fields are readable inline. `ingest_save.py` anchors one record span per `CharacterID`
tag and reads the fields it needs with a minimal typed-property reader.

Field gotchas confirmed against this save:

- `Level`, `Rank`, `Talent_HP`, `Talent_Shot`, `Talent_Defense` are **`ByteProperty`**
  (single byte), not `IntProperty` — reading them as int yields all-zero IVs / level 1.
- The **Attack IV is `Talent_Shot`**; there is no `Talent_Melee` in the data.
- Ownership: `OwnerPlayerUId` is an FGuid; its first uint32 formatted `%08X` equals the
  `<UID>.sav` filename prefix. **Pals assigned to a base have no `OwnerPlayerUId`** —
  they are attributed via their container instead (next section). Unowned Pals in no
  base container are wild/roaming cached spawns and are skipped.
- Player character records carry `IsPlayer` + `NickName` (used to label output files);
  they are excluded from Pal rosters.

Augmentation tags were verified directly against this `Level.sav` on 2026-07-19:

| Save tag | Observed type | Output key | Meaning / gotcha |
|---|---|---|---|
| `Rank` | `ByteProperty` in character records | `condense` | Stored 1–5; **absent means 1 = zero stars**. Output is clamped `Rank - 1` (0–4). One unrelated `IntProperty` tag also exists elsewhere in the GVAS. |
| `Rank_HP` | `ByteProperty` | `soulHp` | Soul rank 0–20; absent means 0. |
| `Rank_Attack` | `ByteProperty` | `soulAtk` | Soul rank 0–20; absent means 0. |
| `Rank_Defence` | `ByteProperty` | `soulDef` | Soul rank 0–20. Note British **Defence**, unlike American `Talent_Defense` for the IV. |
| `FriendshipPoint` | `IntProperty` | `trust` | Cumulative Trust points; output rank is derived from the thresholds below. |
| `Gender` | `EnumProperty` | `gender` | `EPalGenderType::Male` / `::Female` → `"Male"` / `"Female"`, anything else `""`. Added 2026-07-26 for breeding; the existing `EnumProperty` branch already read it, so no new parsing was needed. |

Trust ranks 1–10 begin at cumulative points 6,000 / 13,000 / 21,000 / 30,000 /
40,000 / 55,000 / 80,000 / 110,000 / 150,000 / 200,000. The raw point value is
not stored in import JSON; only the derived 0–10 rank is emitted.

`ingest_review.md` prints a `Gender: N Male / N Female / N unknown` line. Every Pal in
this save resolved (1,111 M / 1,219 F, 0 unknown), so a sudden all-unknown reading means
the tag moved in a patch — breeding pair feasibility degrades silently without it
(`docs/BREEDING.md` §2). **After re-running ingestion, re-import as REPLACE, not MERGE**:
a roster imported before this change carries no gender, and merging would leave a full
duplicate set of genderless Pals.

## Base Pals → guild attribution

Base workers live in dedicated character containers, linked to their base and guild by
two world-level structures (all offsets verified against this save):

- Each character record's container GUID is read via the nested `ContainerId` → `ID`
  tags (there is **no** findable `SlotID` name tag in the raw stream).
- `BaseCampSaveData` has one `WorkerDirector` module per base; its `RawData` blob
  (`PalBaseCampSaveData_WorkerDirector`) starts with the 16-byte **base id** and holds
  the worker **container GUID at `blob[-20:-4]`** (4 zero bytes trail it).
- `GroupSaveDataMap` guild records (`GroupType == EPalGroupType::Guild`) map bases to
  guilds. The RawData layout **drifted from the old palworld-save-tools GROUP spec** by
  two extra u32 fields: `group_id` guid, `group_name` fstring (the admin UID as hex),
  handle array (u32 count × 2 guids), `org_type` byte, **u32 unknown**, `base_ids`
  (u32 count × guid), **u32 unknown**, `base_camp_level` u32, base-camp-points array
  (u32 count × guid), `guild_name` fstring, `admin_player_uid` guid, players.

Owner label for a base Pal = its guild's `guild_name` (duplicate guild names are
disambiguated with the admin player's nickname). Base Pals appear in `pals-all.json`
only, not in the per-player files.

## Internal-ID → display-name mapping

The save stores internal code IDs (`Sheepball`, `Kitsunebi`, `PAL_ALLAttack_up2`); the
app's reference data is keyed by display name (`Lamball`, `Foxparks`, `Ferocious`).
`data/build_id_maps.py` sources that bridge from the **palworld-save-pal** project into
`data/id_maps.json` (species, passive, per-passive Attack/Defense effect for
combat-relevance flagging, and display-name-keyed friendship stats used by Trust
scoring). Keep its attribution wherever `id_maps.json` is used.

The original rationale here — that nothing else exposed the code names in a
stdlib-readable form — stopped being true with the 2026-07-25 game-file import: the
export is itself keyed by code ID and carries English names through
`OverrideNameTextID` → `DT_PalNameText_en`. `id_maps.json` stays because ingestion and
Trust still read it, and note the two vocabularies disagree on case (the save says
`Sheepball`, the export `PAL_NAME_SheepBall`). Folding the bridge into
`import_gamedata.py` is possible; it has not been done.

A save ID does not always match a map key exactly, so `map_species()` walks three
candidates, each case-insensitively: the ID as-is; the ID with a `BOSS_` prefix stripped
(a caught alpha resolves to its base species); and that with a trailing `_otomo` dropped
— a boss's summoned companion has its own stat row but the same tribe and display name
as the base Pal, so `BOSS_KingWhale_otomo` resolves to Panthalus. Only two `_otomo` rows
exist game-wide, and the tribe filter in `import_gamedata.py` deliberately keeps no
variant rows, so this is a mapping alias rather than missing reference data.

`ingest_save.py` maps each ID, then reconciles the display name against the
`data/pals.json` / `data/passives.json` keys. Anything unmatched goes into
`ingest_review.md`, combat-relevant passives first — those silently score 0.

**Before treating a flagged ID as missing data, check whether it is a variant alias.**
`import_gamedata.py` keeps one row per tribe on purpose, dropping `BOSS_`/`GYM_`/
`PREDATOR_`/`RAID_` forms, so those resolve through the `map_species()` candidate chain
above rather than through new reference rows. `BOSS_KingWhale_otomo` was fixed that way,
by extending the chain — not by adding a species.

**For genuinely missing data the fix is to re-run the game-data extraction, not to
hand-write an override.** Since the 2026-07-25 game-file import, `data/pals.json` and
`data/passives.json` come from the game's own DataTables, so a non-empty report usually
just means the export predates a game patch:

1. Re-dump `Pal-Windows.pak` with `tools/gamedata/PalDataExport` — `tools/gamedata/README.md`
   has the exact invocation and its prerequisites (a matching `.usmap`, an Oodle DLL, a
   side-installed .NET 10). Never write to the game install.
2. `python import_gamedata.py` → `data/pals.json` + `passives.json` + `breeding.json`.
3. `python build_report.py` → bake the reference data into `pal_analyzer.html`.
4. `python ingest_save.py` → re-ingest and confirm the report is empty.

The `SPECIES_OVERRIDES` / `PASSIVE_OVERRIDES` dicts in `data/build_data.py` are the
**superseded wiki path and should not be edited.** The game-file import made both
unnecessary — it added 20 species and 19 passives the wiki never documented and
corrected 10 species' base stats. `build_data.py` is kept only as a fallback for a
machine with no Palworld install; see `docs/DATA_SOURCES.md`.

As of 2026-09-03, on a 2,807-Pal three-player save, `ingest_review.md` is empty on both
counts: every owned species and every passive present in the save resolves.
