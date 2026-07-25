# Extracting Pal data from the game files

> **Status: IMPLEMENTED 2026-07-25.** `data/pals.json` and `data/passives.json` now come
> from the game's DataTables. Operating instructions live in `tools/gamedata/README.md`;
> the rest of this document is the original handoff (still accurate — every verified pak
> fact below held up) plus a closing section on what the implementation found that the
> plan did not anticipate. Read that section before touching the extraction.

## Why do this

Today `data/pals.json` / `data/passives.json` come from the palworld.wiki.gg Cargo API
(`data/build_data.py`), patched by hand-maintained `SPECIES_OVERRIDES` /
`PASSIVE_OVERRIDES` dicts in that file because the community wiki lags game patches/DLC by
weeks-to-months. The game's own cooked **DataTables** are the source of truth the wiki and
save editors both derive from. Pulling from them directly:

- gets post-patch/DLC stats, elements, and passives immediately (no wiki lag), and
- **supersedes the manual override workflow** for species stats/elements and passive
  percentages — the exact thing `SPECIES_OVERRIDES`/`PASSIVE_OVERRIDES` exist to work
  around today (see `CLAUDE.md` build-pipeline notes and `docs/DATA_SOURCES.md`).

This realizes the "extract values from the game files themselves" direction named in
`CLAUDE.md`. An earlier call rejected self-extraction (no tooling installed, pak
encryption unknown); both concerns are resolved below.

## Verified pak facts (do not re-derive)

Confirmed by reading the pak directly off disk on the user's machine:

- **Single pak:** `E:\SteamLibrary\steamapps\common\Palworld\Pal\Content\Paks\Pal-Windows.pak`
  (~40.5 GB) — the only game-data pak. There is **no IoStore** `.utoc`/`.ucas` split.
- **UE pak version 11** (UE 5.1-era).
- **Unencrypted** — this is the decisive result. Footer `EncryptionKeyGuid` is all-zero and
  `bEncryptedIndex = 0`; the primary index parses cleanly to `MountPoint '../../../'` with
  **185,003 entries**. No AES key is needed; any standard UE pak tool opens it directly.
- **Entries are Oodle-compressed** (footer compression-method slot = `"Oodle"`).

The pak path may differ on another machine; treat it as a `--pak` argument, don't hardcode.

## Exact source assets (paths confirmed present in the pak index)

Stats:
- `Pal/Content/Pal/DataTable/Character/DT_PalMonsterParameter.uasset` (+ `.uexp`)
- `Pal/Content/Pal/DataTable/Character/DT_PalMonsterParameter_Common.uasset` (+ `.uexp`)
  — the **`_Common`** table carries newer/DLC rows the wiki lacks. Merge both; `_Common`
  wins on key collisions.

Passives:
- `Pal/Content/Pal/DataTable/PassiveSkill/DT_PassiveSkill_Main.uasset` (+ `_Common`)
- `Pal/Content/Pal/DataTable/PassiveSkill/DT_PassiveSkillEffectCondition.uasset`
  (effect gating; needed only if you want to reproduce conditional passives faithfully)

Passive names & descriptions (localized):
- `Pal/Content/Localization/Game/en/Game.locres` — the DataTables store effect **values**
  plus text-**key** references (namespace/key); the readable English name/description lives
  in the locres. A good extractor resolves these automatically (FModel/CUE4Parse do).

Out of current scope (note only; the app has no active-skill math):
- `Pal/Content/Pal/DataTable/Waza/DT_WazaDataTable.uasset` (+ `_Common`) — active skills.

## Prerequisites & toolchain

1. **`.usmap` mappings file — required.** Palworld ships UE5 *unversioned properties*, so
   any parser needs a mappings dump to know each struct's field layout; without it,
   DataTable rows decode as opaque blobs. Obtain either:
   - a community Palworld `.usmap` dump **matching this game build** (widely available), or
   - one generated locally with **Dumper-7** (inject into the running game once).

2. **Oodle decompressor.** No `oo2core_*_win64.dll` ships standalone with Palworld (it's
   statically linked into the shipping exe). **Reuse the repo's existing bridge:**
   `ingest_save.py` (`find_oodle()` and the `OodleLZ_Decompress` `ctypes` call, ~lines
   59-90) already locates an `oo2core_*_win64.dll` from another installed game and drives
   it. FModel and CUE4Parse bundle their own Oodle handling, so if you use those you don't
   need the DLL separately.

3. **Extraction tool** — see recommended path below.

## Field mapping into the existing schema

The extracted values line up with the app's schema at the same scale, so this drops in
without re-deriving anything:

| Game DataTable field | App field | Notes |
|---|---|---|
| `DT_PalMonsterParameter` scaling `HP` | `hp_stat` | same scale as `SPECIES_OVERRIDES` |
| `DT_PalMonsterParameter` scaling `Attack` | `attack_stat` | |
| `DT_PalMonsterParameter` scaling `Defense` | `defense_stat` | |
| `ElementType1` / `ElementType2` | `elements` (1-2 tags) | remap names, see below |
| `DT_PassiveSkill_Main` attack effect % | `attack_pct` | |
| `DT_PassiveSkill_Main` defense effect % | `defense_pct` | |
| (none — no max-HP passive exists) | `hp_pct` | always `0.0`, schema symmetry only |
| `DT_PassiveSkill_Main` rank | `rank` | picker metadata |
| resolved `Game.locres` text | `description` | picker metadata |

**Element name remap** (per `CLAUDE.md`): `Electricity→Electric, Earth→Ground,
Leaf→Grass, Normal→Neutral`.

**Scoring caveat** (see `docs/FORMULAS.md`): only `stat=="Attack"` / `"Defense"` percent
passives feed the combat score; `HP_PassiveBonus%` is always 0 because **no max-HP passive
exists** in the game data. Keep every other passive as picker metadata but do not let it
affect scoring. Filter species to the `Normal` variant (drop Boss/Alpha), matching the
current `palVariant='Normal'` filter.

## Recommended implementation path

Extraction inherently needs a UE asset parser, which is beyond Python stdlib. Keep it
**out of the required stdlib-only app build** and treat it as a rare data-refresh step —
the same allowance `build_data.py` already gets for needing the network.

**Tier 1 — recommended (low effort, keeps repo code stdlib-only):**
1. Open `Pal-Windows.pak` in **FModel**, load the `.usmap`, and export to JSON:
   `DT_PalMonsterParameter` (+`_Common`), `DT_PassiveSkill_Main` (+`_Common`), and
   `Game.locres`. FModel resolves the locres text refs when exporting the tables.
2. Add a new **stdlib-only `import_gamedata.py`** that reads those JSON exports, applies
   the field/element remap above, filters to `Normal`, and writes `data/pals.json` /
   `data/passives.json` — carrying the existing CC BY-SA/attribution requirements is no
   longer needed for game-sourced data, but keep an attribution/provenance comment noting
   the game build the data came from.
   - Safer first increment: instead of overwriting the wiki JSON wholesale, have
     `import_gamedata.py` regenerate the `SPECIES_OVERRIDES` / `PASSIVE_OVERRIDES` blocks
     so game data wins over stale wiki rows while the wiki pipeline stays intact. Promote
     to full replacement once the numbers are validated.

**Tier 2 — alternative (full automation, more upfront work):** a scripted **CUE4Parse**
(.NET) CLI can go pak→JSON headlessly end-to-end (usmap-aware, Oodle built in), making the
refresh a single command. Cost: a .NET build dependency in the repo. Only worth it if
unattended per-patch refreshes become a goal.

A pure-Python extractor is possible but **not recommended** — a from-scratch usmap-aware
unversioned-property + DataTable + locres parser is fragile relative to the payoff.

**Build order after import:** `import_gamedata.py` → `build_report.py` (bakes JSON into
`pal_analyzer.html`). Only rerun `ingest_save.py` if the id maps changed. Do **not**
hand-edit `pal_analyzer.html` — it's generated.

## Verification the implementer must hit

- **Formula anchors:** extracted Mammorest/Kitsun base stats must reproduce
  `scoring_check.py`'s **151.0 / 899.6** (Mammorest) and **150.6 / 901.8** (Kitsun) at
  L1/L50, IV=0, no passives. If they don't, the usmap or the scale mapping is wrong. Run
  `python scoring_check.py`.
- **Cross-check** a handful of extracted species against the current `SPECIES_OVERRIDES`
  (e.g. Eidrolon 115/125/120 Dragon+Dark) — they should match, since both trace to the
  same datamine.
- After `import_gamedata.py` → `build_report.py`, confirm the in-page `console.assert`
  self-test still passes and that species previously present only via `SPECIES_OVERRIDES`
  now resolve from the primary data.

## What the implementation actually found (2026-07-25)

The plan above was right about the pak, the asset paths, and the field mapping. Six things
it did not anticipate:

1. **Tier 2 (scripted CUE4Parse) was taken, not Tier 1 (FModel).** FModel is a GUI and
   isn't installed; a ~150-line .NET console app (`tools/gamedata/PalDataExport`) does the
   whole dump headlessly, and CUE4Parse handles Oodle itself given a DLL path. The repo's
   Python stays stdlib-only as intended.
2. **The `.usmap` is version 4 (`ExplicitEnumValues`).** The current community mappings
   (`PalworldModding/UsefulFiles`, updated for 1.0) need a CUE4Parse build new enough to
   parse v4, and the only such NuGet build targets `net10.0`. The machine had SDK 8, so
   .NET 10 is side-installed under `tools/gamedata/vendor/dotnet` — no PATH or system
   change. CUE4Parse 1.2.1/1.2.2 (net8.0) reject the file with "Usmap has invalid version".
3. **`Game.locres` is a 37-byte stub — the plan's locres step is a dead end.** Palworld's
   native culture is *Japanese*, so English never went through a locres. Display names and
   descriptions come from `Pal/Content/L10N/en/Pal/DataTable/Text/DT_*` instead; the base
   `Pal/Content/Pal/DataTable/Text/DT_*` tables hold Japanese, and untranslated rows in the
   en tables read literally `"en_text"`. Text-ID lookups must also be **case-insensitive**
   (`PAL_NAME_Windchimes` vs. the row key `WindChimes` — Hangyu is silently lost otherwise).
4. **`_Common` does not need merging.** `DT_PalMonsterParameter` is a `CompositeDataTable`
   whose only parent is `_Common`, and CUE4Parse returns the already-merged rows — the two
   exports are row-for-row identical.
5. **"No max-HP passive exists" was a fact about the *wiki*, not the game.** The game has
   two displayable ones (God of Destruction −50%, World Tree Seedbed −20%), so `hp_pct` is
   no longer decorative: `passiveBonuses()` in the template now sums it, and
   `docs/FORMULAS.md` was corrected. The formula anchors are unaffected (they use no
   passives) and still reproduce 151.0 / 899.6 and 150.6 / 901.8.
6. **Effect *target* matters.** `DT_PassiveSkill_Main` rows carry a `TargetType` per
   effect; `ToTrainer` effects buff the player, not the Pal. Vanguard ("+10% Player
   Attack") and Stronghold Strategist were being scored as Pal bonuses under the wiki data
   and are now excluded. Species selection likewise needs the game's own grouping: keep the
   row whose key equals its `Tribe` id, which drops boss/oilrig/quest variants the way the
   old `palVariant='Normal'` filter did.

Species selection is by tribe, and passive selection is by the game's
`Category == SortDisplayable` flag — 115 of 1905 rows.

### Verification actually performed

- `scoring_check.py` passes; the in-page `console.assert` self-test passes with 0 failures
  (run through Node per `CLAUDE.md`).
- Anchors reproduce exactly: Lamball 70/70/70, Anubis 120/130/100, Mammorest 150/85/90,
  Kitsun 100/115/100, and Eidrolon 115/125/120 Dragon+Dark now resolves from primary data
  rather than `SPECIES_OVERRIDES`.
- Cross-checked against `oMaN-Rod/palworld-save-pal`'s independent datamine: **407 rows,
  zero mismatches** on base stats, `Friendship_*`, and element types/order.
- Of 96 passives shared with the wiki, 93 matched exactly; the 3 that didn't were wiki
  errors (Eternal Flame rank, Immortality's missing +15% Attack, Whopper's rank).
- `ingest_save.py` re-run over the real server save: `out/ingest_review.md` went from 12
  unmapped passives to **empty**.

## Provenance / licensing note

Data extracted from the game's own files is not wiki CC BY-SA content, so the wiki
attribution requirement doesn't apply to game-sourced JSON — but record the **game build**
the extraction came from (and keep the palworld-save-pal attribution wherever its id maps
are still used). The `out/*.json` player-roster files and `pal_analyzer.html` remain
never-publish; nothing in this workflow changes that.
