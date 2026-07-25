# Game-data extraction (`PalDataExport`)

Dumps Palworld's own cooked DataTables out of `Pal-Windows.pak` to JSON, which
`import_gamedata.py` (repo root, stdlib-only) turns into `data/pals.json` /
`data/passives.json`. This replaces the palworld.wiki.gg fetch in `data/build_data.py`
— see `docs/GAMEDATA_EXTRACTION.md` for the background and `docs/DATA_SOURCES.md` for
where the project's reference data comes from now.

**Read-only.** The pak is opened for reading and nothing under the game install is
written, moved, or patched. Refresh this only after a game patch.

## Prerequisites (none are committed — see `.gitignore`)

Everything lives in `tools/gamedata/vendor/`:

| File | Where it comes from |
|---|---|
| `Mappings.usmap` | `PalworldModding/UsefulFiles` on GitHub — must match the game build. Palworld cooks UE5 *unversioned properties*, so without this the DataTable rows decode as opaque blobs. |
| `oo2core_9_win64.dll` | Any Oodle-using game install (Palworld links Oodle statically and ships no DLL). `ingest_save.py`'s `find_oodle()` locates one the same way. |
| `dotnet/` | .NET 10 SDK, side-installed with `dotnet-install.ps1 -Channel 10.0 -InstallDir vendor/dotnet -NoPath`. Needed because the only CUE4Parse build that reads usmap **v4** (`ExplicitEnumValues`) targets `net10.0`; the machine's system SDK is 8.x. Nothing on PATH changes. |

```powershell
$v = "tools/gamedata/vendor"
New-Item -ItemType Directory -Force $v
Invoke-WebRequest 'https://raw.githubusercontent.com/PalworldModding/UsefulFiles/master/Mappings.usmap' -OutFile "$v/Mappings.usmap"
Copy-Item '<some game>/oo2core_9_win64.dll' "$v/"
Invoke-WebRequest 'https://dot.net/v1/dotnet-install.ps1' -OutFile "$v/dotnet-install.ps1"
& "$v/dotnet-install.ps1" -Channel 10.0 -InstallDir "$v/dotnet" -NoPath
```

## Running

```powershell
$dotnet = "tools/gamedata/vendor/dotnet/dotnet.exe"
& $dotnet build tools/gamedata/PalDataExport/PalDataExport.csproj -c Release
& $dotnet tools/gamedata/PalDataExport/bin/Release/net10.0/PalDataExport.dll `
    --pak 'E:\SteamLibrary\steamapps\common\Palworld\Pal\Content\Paks' `
    --usmap tools/gamedata/vendor/Mappings.usmap `
    --oodle tools/gamedata/vendor/oo2core_9_win64.dll `
    --out   tools/gamedata/export

python import_gamedata.py     # export/*.json -> data/pals.json + data/passives.json
python build_report.py        # bake into pal_analyzer.html
```

The exe in `bin/` won't launch directly (its apphost resolves the *system* dotnet, which
is 8.x) — invoke the `.dll` through `vendor/dotnet/dotnet.exe` as above.

`--find <substring>` lists matching pak entries instead of exporting, which is how the
asset paths above were found.

## What gets exported

| File | Used for |
|---|---|
| `DT_PalMonsterParameter.json` | species `Hp` / `ShotAttack` / `Defense`, `ElementType1/2`, `Friendship_*` (Trust) |
| `DT_PassiveSkill_Main.json` | passive effect types/values/targets and rank |
| `DT_PalNameText_en.json`, `DT_SkillNameText_en.json`, `DT_SkillDescText_en.json`, `DT_UI_Common_Text_en.json` | English display names and descriptions |
| `_meta.json` | provenance (pak name/size/mtime) copied into the generated JSON's `_source` |

`*_Common.json` variants are exported too. `DT_PalMonsterParameter` is a
`CompositeDataTable` whose only parent is `_Common`, and CUE4Parse already returns the
merged row set — both files carry identical rows, so the importer reads only the first.

Note the base (non-`L10N`) text tables are **Japanese**: Palworld's native culture is JP,
which is also why `Localization/Game/en/Game.locres` is a 37-byte stub. English lives in
`Pal/Content/L10N/en/...` and untranslated rows there read literally `"en_text"`.
