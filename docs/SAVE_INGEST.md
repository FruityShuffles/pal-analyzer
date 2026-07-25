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
out/ingest_review.md      # species/passives in the save missing from the wiki data
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

Trust ranks 1–10 begin at cumulative points 6,000 / 13,000 / 21,000 / 30,000 /
40,000 / 55,000 / 80,000 / 110,000 / 150,000 / 200,000. The raw point value is
not stored in import JSON; only the derived 0–10 rank is emitted.

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
Neither the wiki Cargo API nor the shipped game files expose the code names in a
stdlib-readable form, so `data/build_id_maps.py` sources the bridge from the
**palworld-save-pal** project into `data/id_maps.json` (species, passive, per-passive
Attack/Defense effect for combat-relevance flagging, and display-name-keyed friendship
stats used by Trust scoring).

`ingest_save.py` maps each ID, then reconciles the display name against the wiki
`pals.json` / `passives.json` keys. Anything unmatched goes into `ingest_review.md`:

- **Combat-relevant passive, missing** → add to `PASSIVE_OVERRIDES` in `build_data.py`.
- **Species missing** → usually a new-DLC Pal absent from the wiki pull; refresh
  `build_data.py` or add manually. Unknown species import but score 0 until added.

At time of writing: 98.8% of owned species and all combat passives resolved; the only
gaps were 2 new-DLC Pals (Dynamoff, Skutlass Ignis) and 8 non-combat passives.
