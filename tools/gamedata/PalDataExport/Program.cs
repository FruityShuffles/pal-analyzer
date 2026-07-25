// PalDataExport -- read-only dump of Palworld's cooked DataTables to JSON.
//
// Opens Pal-Windows.pak with CUE4Parse (read-only; nothing under the game install is ever
// written), resolves UE5 unversioned properties with a .usmap mappings file, and
// serialises the DataTables the Pal Analyzer needs into one JSON file each, plus the
// English text tables that turn internal row keys into display names.
//
// Usage:
//   PalDataExport --pak <Paks dir or .pak> --usmap <Mappings.usmap>
//                 [--oodle oo2core_9_win64.dll] [--out <dir>]

using CUE4Parse.Compression;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Versions;
using Newtonsoft.Json;

namespace PalDataExport;

internal static class Program
{
    // Package path (no extension -- CUE4Parse resolves the .uasset/.uexp pair) -> output file.
    private static readonly (string Asset, string Out)[] Targets =
    {
        ("Pal/Content/Pal/DataTable/Character/DT_PalMonsterParameter",            "DT_PalMonsterParameter.json"),
        ("Pal/Content/Pal/DataTable/Character/DT_PalMonsterParameter_Common",     "DT_PalMonsterParameter_Common.json"),
        ("Pal/Content/Pal/DataTable/PassiveSkill/DT_PassiveSkill_Main",           "DT_PassiveSkill_Main.json"),
        ("Pal/Content/Pal/DataTable/PassiveSkill/DT_PassiveSkill_Main_Common",    "DT_PassiveSkill_Main_Common.json"),
        ("Pal/Content/Pal/DataTable/PassiveSkill/DT_PassiveSkillEffectCondition", "DT_PassiveSkillEffectCondition.json"),
        // English display text. Palworld's native culture is Japanese, so the base
        // Pal/Content/Pal/DataTable/Text tables hold Japanese and these L10N/en tables are
        // the English source, keyed by text ID (rows they don't translate read "en_text").
        ("Pal/Content/L10N/en/Pal/DataTable/Text/DT_PalNameText_Common",   "DT_PalNameText_en.json"),
        ("Pal/Content/L10N/en/Pal/DataTable/Text/DT_SkillNameText_Common", "DT_SkillNameText_en.json"),
        ("Pal/Content/L10N/en/Pal/DataTable/Text/DT_SkillDescText_Common", "DT_SkillDescText_en.json"),
        // Authored descriptions embed <uiCommon id=|KEY|/> references into this table.
        ("Pal/Content/L10N/en/Pal/DataTable/Text/DT_UI_Common_Text_Common", "DT_UI_Common_Text_en.json"),
    };

    private static int Main(string[] args)
    {
        var opts = ParseArgs(args);
        if (opts is null) return 2;
        var (pak, usmap, oodle, outDir, find) = opts.Value;

        var pakDir = Directory.Exists(pak) ? pak : Path.GetDirectoryName(Path.GetFullPath(pak));
        Directory.CreateDirectory(outDir);

        if (!string.IsNullOrEmpty(oodle))
        {
            OodleHelper.Initialize(oodle);
            Console.WriteLine($"oodle   : {oodle}");
        }

        Console.WriteLine($"pak dir : {pakDir}");
        var provider = new DefaultFileProvider(pakDir, SearchOption.TopDirectoryOnly,
            new VersionContainer(EGame.GAME_UE5_1), StringComparer.OrdinalIgnoreCase);
        provider.Initialize();
        provider.Mount();
        Console.WriteLine($"mounted : {provider.Files.Count} files");

        provider.MappingsContainer = new FileUsmapTypeMappingsProvider(usmap);
        Console.WriteLine($"usmap   : {usmap}");

        if (find is not null)
        {
            foreach (var key in provider.Files.Keys.Where(k => k.Contains(find, StringComparison.OrdinalIgnoreCase)).Take(200))
                Console.WriteLine($"  {key}");
            return 0;
        }

        // No locres load: Palworld's native culture is Japanese and
        // Pal/Content/Localization/Game/en/Game.locres is a 37-byte stub. The English
        // strings live in the L10N DataTables exported above, keyed by text ID.

        var settings = new JsonSerializerSettings
        {
            Formatting = Formatting.Indented,
            ReferenceLoopHandling = ReferenceLoopHandling.Ignore,
        };

        var failures = 0;
        foreach (var (asset, outName) in Targets)
        {
            try
            {
                var obj = provider.LoadPackageObject(asset);
                var json = JsonConvert.SerializeObject(obj, settings);
                File.WriteAllText(Path.Combine(outDir, outName), json);
                Console.WriteLine($"  ok    {outName}  ({json.Length:N0} chars)");
            }
            catch (Exception e)
            {
                failures++;
                Console.WriteLine($"  FAIL  {outName}: {e.GetType().Name}: {e.Message}");
            }
        }

        // Provenance: which game build these numbers came from. import_gamedata.py copies
        // this into the _source field of the JSON it generates.
        var pakFile = Directory.GetFiles(pakDir, "*.pak").OrderByDescending(f => new FileInfo(f).Length)
            .FirstOrDefault();
        var meta = new Dictionary<string, object>
        {
            ["pak"] = pakFile is null ? pakDir : Path.GetFileName(pakFile),
            ["pak_bytes"] = pakFile is null ? 0L : new FileInfo(pakFile).Length,
            ["pak_modified_utc"] = pakFile is null
                ? "" : new FileInfo(pakFile).LastWriteTimeUtc.ToString("yyyy-MM-ddTHH:mm:ssZ"),
            ["mounted_files"] = provider.Files.Count,
            ["usmap"] = Path.GetFileName(usmap),
            ["extracted_utc"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
            ["extractor"] = "tools/gamedata/PalDataExport (CUE4Parse)",
        };
        File.WriteAllText(Path.Combine(outDir, "_meta.json"), JsonConvert.SerializeObject(meta, settings));
        Console.WriteLine($"  ok    _meta.json  (pak modified {meta["pak_modified_utc"]})");

        return failures == 0 ? 0 : 1;
    }

    private static (string Pak, string Usmap, string Oodle, string Out, string Find)? ParseArgs(string[] args)
    {
        string pak = null, usmap = null, oodle = null, outDir = "out", find = null;
        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--pak":   pak = args[++i]; break;
                case "--usmap": usmap = args[++i]; break;
                case "--oodle": oodle = args[++i]; break;
                case "--out":   outDir = args[++i]; break;
                case "--find":  find = args[++i]; break;
                default:
                    Console.Error.WriteLine($"unknown argument: {args[i]}");
                    return null;
            }
        }
        if (pak is null || usmap is null)
        {
            Console.Error.WriteLine("usage: PalDataExport --pak <Paks dir> --usmap <Mappings.usmap> "
                                    + "[--oodle <oo2core_9_win64.dll>] [--out <dir>]");
            return null;
        }
        return (pak, usmap, oodle, outDir, find);
    }
}
