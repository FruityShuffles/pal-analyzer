#!/usr/bin/env python3
"""Ingest a Palworld server `Level.sav` -> per-player import files for pal_analyzer.html.

Offline build-time step (mirrors build_data.py / build_report.py). Reads the world save,
extracts every owned Pal (species, level, IVs, passives, condensing, combat soul ranks,
and Trust rank), maps the save's internal code IDs to display names via
data/id_maps.json, and writes:

    out/pals-<Player>.json   one import-ready file per player (drop into the app's Import JSON)
    out/pals-all.json        the primary import: every player's Pals plus base-assigned
                             Pals, each entry tagged with an "owner" (player nickname,
                             or the owning guild's name for base workers)
    out/ingest_review.md     species/passives in the save that are missing from the app's
                             reference data -- combat-relevant ones flagged first

Ownership: party/palbox Pals carry OwnerPlayerUId; Pals assigned to a base do NOT --
they are attributed via their container (SlotID -> WorkerDirector -> base camp -> guild).
Unowned Pals in no base container are wild/roaming cached spawns and are skipped.

The save is Oodle-compressed (container magic `PlM1`), so decompression needs an Oodle DLL
(`oo2core_*_win64.dll`). Any game's copy works; this looks inside the Palworld install first.
`ctypes` is stdlib, so there are still no pip dependencies -- the DLL is the user's own
game file and is never redistributed.

Usage:
    python ingest_save.py [--level Level.sav] [--players .] [--out out] [--oodle PATH]
"""
import argparse
import ctypes
import glob
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET_LEVEL = 80  # matches the app's default target level (v1.0 cap)
GENDERS = {"EPalGenderType::Male": "Male", "EPalGenderType::Female": "Female"}
TRUST_THRESHOLDS = [6000, 13000, 21000, 30000, 40000, 55000, 80000, 110000, 150000, 200000]


def trust_rank(points):
    """Derive Trust rank 0..10 from cumulative points (docs/AUGMENTS.md section 4)."""
    p = points or 0
    return sum(1 for threshold in TRUST_THRESHOLDS if p >= threshold)

# Search roots for the Oodle DLL, most-specific first.
OODLE_ROOTS = [
    r"E:\SteamLibrary\steamapps\common\Palworld",
    r"C:\Program Files (x86)\Steam\steamapps\common",
    r"D:\SteamLibrary\steamapps\common",
    r"E:\SteamLibrary\steamapps\common",
]


# ----------------------------------------------------------------------------
# Oodle decompression
# ----------------------------------------------------------------------------
def find_oodle(explicit=None):
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        sys.exit(f"--oodle path not found: {explicit}")
    for root in OODLE_ROOTS:
        if not os.path.isdir(root):
            continue
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if re.match(r"oo2core_\d+_win64\.dll$", f, re.I):
                    return os.path.join(dp, f)
    sys.exit("No oo2core_*_win64.dll found. Pass one with --oodle "
             "(any Oodle-using game install has one).")


def decompress_level(path, oodle_dll):
    data = open(path, "rb").read()
    if data[8:12] != b"PlM1":
        sys.exit(f"Unexpected save magic {data[8:12]!r} (expected b'PlM1').")
    unc_len = struct.unpack("<I", data[0:4])[0]
    oo = ctypes.CDLL(oodle_dll)
    oo.OodleLZ_Decompress.restype = ctypes.c_int64
    dst = ctypes.create_string_buffer(unc_len)
    n = oo.OodleLZ_Decompress(
        ctypes.c_char_p(data[12:]), ctypes.c_int64(len(data) - 12),
        dst, ctypes.c_int64(unc_len),
        ctypes.c_int64(1), 0, 0,
        ctypes.c_void_p(0), 0, ctypes.c_void_p(0), ctypes.c_void_p(0),
        ctypes.c_void_p(0), 0, ctypes.c_int64(3))
    if n != unc_len:
        sys.exit(f"Oodle decompress failed (returned {n}, expected {unc_len}).")
    out = dst.raw[:n]
    if out[:4] != b"GVAS":
        sys.exit("Decompressed data is not GVAS.")
    return out


# ----------------------------------------------------------------------------
# Minimal GVAS tagged-property reader (only the property types we need)
# ----------------------------------------------------------------------------
def read_fstring(b, o):
    ln = struct.unpack("<i", b[o:o + 4])[0]
    o += 4
    if ln == 0:
        return "", o
    if ln < 0:  # UTF-16-LE, ln = -(chars incl. terminator)
        n = -ln * 2
        s = b[o:o + n]
        o += n
        return s[:-2].decode("utf-16-le", "replace"), o
    s = b[o:o + ln]
    o += ln
    return s[:-1].decode("utf-8", "replace"), o


def prop_offset(span, name):
    """Offset just past the length-prefixed FString name tag, or None."""
    key = struct.pack("<i", len(name) + 1) + name.encode() + b"\x00"
    i = span.find(key)
    return i + len(key) if i >= 0 else None


def read_typed(span, o):
    """Read the value of a tagged property whose name FString ends at `o`."""
    typ, o = read_fstring(span, o)
    o += 8  # value size (int64) -- we don't need it
    if typ == "IntProperty":
        o += 1
        return struct.unpack("<i", span[o:o + 4])[0]
    if typ == "ByteProperty":
        # Level / Rank / Talent_* are single-byte enums with EnumName "None".
        _enum, o = read_fstring(span, o)
        o += 1
        return span[o]
    if typ == "BoolProperty":
        return span[o] != 0
    if typ in ("StrProperty", "NameProperty"):
        o += 1
        return read_fstring(span, o)[0]
    if typ == "EnumProperty":
        _enum, o = read_fstring(span, o)
        o += 1
        return read_fstring(span, o)[0]
    if typ == "ArrayProperty":
        inner, o = read_fstring(span, o)
        o += 1
        cnt = struct.unpack("<i", span[o:o + 4])[0]
        o += 4
        vals = []
        if inner in ("NameProperty", "StrProperty"):
            for _ in range(cnt):
                v, o = read_fstring(span, o)
                vals.append(v)
        return vals
    if typ == "StructProperty":
        st, o = read_fstring(span, o)
        o += 16 + 1  # struct guid + terminator
        if st == "Guid":
            return span[o:o + 16]
    return None


def field(span, name):
    o = prop_offset(span, name)
    return read_typed(span, o) if o is not None else None


def guid_hex(g):
    """First uint32 of an FGuid as 8 hex chars -- matches player-save filenames."""
    return f"{struct.unpack('<I', g[0:4])[0]:08X}" if g and len(g) >= 4 else None


def container_id(span):
    """Hex of the record's character-container GUID (SlotID -> ContainerId -> ID).

    There is no findable `SlotID` name tag in the raw stream; the nested
    `ContainerId` -> `ID` path is what actually appears, so anchor on that.
    """
    o = prop_offset(span, "ContainerId")
    if o is None:
        return None
    sub = span[o:o + 200]
    o2 = prop_offset(sub, "ID")
    if o2 is None:
        return None
    v = read_typed(sub, o2)
    return v.hex() if isinstance(v, (bytes, bytearray)) else None


# ----------------------------------------------------------------------------
# Save parsing
# ----------------------------------------------------------------------------
def parse_records(buf):
    """Yield one dict per character record, anchored on each CharacterID tag."""
    anchors = [m.start() for m in re.finditer(rb"\x0c\x00\x00\x00CharacterID\x00", buf)]
    anchors.append(len(buf))
    for i in range(len(anchors) - 1):
        span = buf[anchors[i]:anchors[i + 1]]
        yield {
            "species_id": field(span, "CharacterID"),
            "is_player": bool(field(span, "IsPlayer")),
            "nickname": field(span, "NickName") or "",
            "level": field(span, "Level"),
            "iv_hp": field(span, "Talent_HP"),
            "iv_atk": field(span, "Talent_Shot"),
            "iv_def": field(span, "Talent_Defense"),
            "rank": field(span, "Rank"),
            "rank_hp": field(span, "Rank_HP"),
            "rank_atk": field(span, "Rank_Attack"),
            # Soul tag is British "Defence"; the IV tag above is American "Defense".
            "rank_def": field(span, "Rank_Defence"),
            "friendship_pts": field(span, "FriendshipPoint"),
            "is_rare": bool(field(span, "IsRarePal")),
            # EnumProperty "EPalGenderType::Male" / "::Female". Breeding needs one of
            # each, so this is load-bearing for docs/BREEDING.md's pair feasibility.
            "gender": field(span, "Gender"),
            "passive_ids": field(span, "PassiveSkillList") or [],
            "owner": guid_hex(field(span, "OwnerPlayerUId")),
            "container": container_id(span),
            "_span": span,
        }


def resolve_player_names(records, owner_hexes):
    """Map each active owner-hex -> its in-game nickname via player records.

    A player's own UID appears as its FULL 16-byte GUID (4-byte prefix + 12 zero
    bytes) several times inside its own character record (owner field + instance
    data). Guildmates' UIDs appear in the same record too, but only as a couple of
    references in the group header -- and an inactive former member with no
    <UID>.sav (e.g. Doctasm) still leaves a lingering player record here that
    references active guildmates. So we can't just substring-match a hex across
    every record and keep the last hit: that let a ghost member's record hijack an
    active player's name (and a bare 4-byte prefix false-matched unrelated bytes).

    Instead, for each active hex pick the record whose span contains its full
    16-byte GUID the most times -- that maximum is the record the UID actually
    belongs to, and the ghost's fewer references never win.
    """
    players = [r for r in records if r["is_player"] and r["nickname"]]
    names = {}
    for h in owner_hexes:
        full = struct.pack("<I", int(h, 16)) + b"\x00" * 12
        best, best_cnt = None, 0
        for r in players:
            cnt = r["_span"].count(full)
            if cnt > best_cnt:
                best, best_cnt = r["nickname"], cnt
        if best is not None:
            names[h] = best
    return names


def read_raw_blob(buf, o):
    """Read a `RawData: ArrayProperty<ByteProperty>` whose name tag ends at `o`."""
    nm, o = read_fstring(buf, o)
    if nm != "RawData":
        return None
    _typ, o = read_fstring(buf, o)   # "ArrayProperty"
    o += 8                           # value size (int64)
    _inner, o = read_fstring(buf, o)  # "ByteProperty"
    o += 1                           # array terminator
    cnt = struct.unpack("<I", buf[o:o + 4])[0]
    o += 4
    return buf[o:o + cnt]


def parse_worker_containers(buf):
    """container GUID (hex) -> base-camp id (hex), one per base's WorkerDirector.

    Each BaseCampSaveData module map has a `WorkerDirector` entry whose RawData
    blob starts with the 16-byte base id and ends with the worker Pal container
    GUID at blob[-20:-4] (4 zero bytes trail it) -- verified against this save.
    """
    key = b"#\x00\x00\x00PalBaseCampSaveData_WorkerDirector\x00"
    out = {}
    for m in re.finditer(re.escape(key), buf):
        blob = read_raw_blob(buf, m.end() + 17)  # skip struct guid + terminator
        if not blob or len(blob) < 36:
            continue
        base_id = blob[:16].hex()
        cont = blob[-20:-4].hex()
        if cont.strip("0"):
            out[cont] = base_id
    return out


def parse_guilds(buf, player_names):
    """base-camp id (hex) -> guild display name, from the GroupSaveDataMap.

    Guild RawData layout, verified against this save (drifted from the older
    palworld-save-tools GROUP spec by two extra u32 fields): group_id guid,
    group_name fstring, individual_character_handle_ids (u32 count x 2 guids),
    org_type byte, u32 unknown, base_ids (u32 count x guid), u32 unknown,
    base_camp_level u32, base_camp_points (u32 count x guid), guild_name
    fstring, admin_player_uid guid, players.
    """
    out, seen = {}, set()
    for m in re.finditer(rb"\x15\x00\x00\x00EPalGroupType::Guild\x00", buf):
        blob = read_raw_blob(buf, m.end())
        if not blob:
            continue
        try:
            p = 16                                       # group_id
            _group_name, p = read_fstring(blob, p)
            n = struct.unpack("<I", blob[p:p + 4])[0]    # character handles
            p += 4 + n * 32
            p += 1 + 4                                   # org_type + unknown u32
            n = struct.unpack("<I", blob[p:p + 4])[0]    # base_ids
            p += 4
            if not (0 < n < 64):
                raise ValueError(f"implausible base_ids count {n}")
            base_ids = [blob[p + i * 16:p + (i + 1) * 16].hex() for i in range(n)]
            p += n * 16
            p += 4 + 4                                   # unknown u32 + base_camp_level
            n = struct.unpack("<I", blob[p:p + 4])[0]    # base camp points
            p += 4 + n * 16
            gname, p = read_fstring(blob, p)
            admin = guid_hex(blob[p:p + 16])
        except (struct.error, ValueError, IndexError) as e:
            print(f"  ! could not parse a guild blob ({e}) -- its base Pals will be skipped")
            continue
        label = gname or "Unnamed Guild"
        if label in seen:  # duplicate guild names -> disambiguate by admin player
            label = f"{label} ({player_names.get(admin, admin)})"
        seen.add(label)
        for b in base_ids:
            out[b] = label
    return out


# ----------------------------------------------------------------------------
# Mapping + reconciliation
# ----------------------------------------------------------------------------
def map_species(sid, id_maps):
    sp = id_maps["species"]
    lower = {k.lower(): v for k, v in sp.items()}
    # exact, then BOSS_-stripped base (caught alpha -> base species), each case-insensitive
    for cand in (sid, sid[5:] if sid[:5].upper() == "BOSS_" else None):
        if not cand:
            continue
        if cand in sp:
            return sp[cand]
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "Unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default=os.path.join(HERE, "Level.sav"))
    ap.add_argument("--players", default=HERE, help="folder containing the <UID>.sav player saves")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--oodle", default=None)
    args = ap.parse_args()

    id_maps = json.load(open(os.path.join(HERE, "data", "id_maps.json"), encoding="utf-8"))
    app_pals = set(json.load(open(os.path.join(HERE, "data", "pals.json"), encoding="utf-8"))["pals"])
    app_pass = set(json.load(open(os.path.join(HERE, "data", "passives.json"), encoding="utf-8"))["passives"])
    non_pal = set(id_maps.get("species_non_pal", []))
    pass_effect = id_maps.get("passives_effect", {})

    # Player UIDs come from the <32-hex>.sav filenames next to Level.sav.
    player_files = [os.path.basename(p) for p in glob.glob(os.path.join(args.players, "*.sav"))
                    if re.match(r"^[0-9A-Fa-f]{32}\.sav$", os.path.basename(p))]
    owner_hexes = sorted({f[:8].upper() for f in player_files})
    if not owner_hexes:
        sys.exit(f"No <UID>.sav player saves found in {args.players}")
    print(f"Players (by UID prefix): {', '.join(owner_hexes)}")

    oodle = find_oodle(args.oodle)
    print(f"Oodle DLL: {oodle}")
    buf = decompress_level(args.level, oodle)
    print(f"Decompressed Level.sav -> {len(buf):,} bytes")

    records = list(parse_records(buf))
    names = resolve_player_names(records, owner_hexes)

    # Base attribution: worker container -> base camp -> owning guild.
    base_of = parse_worker_containers(buf)
    guild_of = parse_guilds(buf, names)
    unmatched = sorted({b for b in base_of.values() if b not in guild_of})
    for b in unmatched:
        print(f"  ! base {b[:8]} belongs to no parsed guild -- its Pals will be skipped")
    base_owner = {c: guild_of[b] for c, b in base_of.items() if b in guild_of}
    print(f"Bases: {len(base_of)}, guilds: {', '.join(sorted(set(guild_of.values()))) or '(none)'}")

    # Build per-owner rosters + collect unknown IDs for the review report.
    # Owners are player nicknames (party/palbox Pals, via OwnerPlayerUId) or
    # guild names (base worker Pals, via their container). Unowned Pals in no
    # base container are wild/roaming cached spawns -- skipped.
    hex_label = {h: names.get(h, h) for h in owner_hexes}
    player_labels = [hex_label[h] for h in owner_hexes]
    owner_order = player_labels + sorted(set(base_owner.values()) - set(player_labels))
    rosters = {lab: [] for lab in owner_order}
    sp_seen, pv_seen = {}, {}   # id -> count (owned Pals only)
    counted = base_counted = skipped_human = 0
    gender_seen = {"Male": 0, "Female": 0, "unknown": 0}
    for r in records:
        if r["is_player"]:
            continue
        if r["owner"] in hex_label:
            label, is_base = hex_label[r["owner"]], False
        elif r["container"] in base_owner:
            label, is_base = base_owner[r["container"]], True
        else:
            continue
        sid = r["species_id"]
        if not sid or sid in non_pal:
            skipped_human += 1
            continue
        counted += 1
        base_counted += is_base
        sp_seen[sid] = sp_seen.get(sid, 0) + 1
        disp = map_species(sid, id_maps)
        passives = []
        for pid in r["passive_ids"][:4]:
            pv_seen[pid] = pv_seen.get(pid, 0) + 1
            pname = id_maps["passives"].get(pid)
            passives.append(pname if pname else pid)
        rosters[label].append({
            "species": disp or sid,
            "nickname": r["nickname"] or ("★ " + (disp or sid) if r["is_rare"] else ""),
            "level": r["level"] or 1,
            "ivHp": r["iv_hp"] or 0,
            "ivAtk": r["iv_atk"] or 0,
            "ivDef": r["iv_def"] or 0,
            # Rank is absent at its default 1, which means zero condense stars.
            "condense": max(0, min(4, (r["rank"] or 1) - 1)),
            "soulHp": max(0, min(20, r["rank_hp"] or 0)),
            "soulAtk": max(0, min(20, r["rank_atk"] or 0)),
            "soulDef": max(0, min(20, r["rank_def"] or 0)),
            "trust": trust_rank(r["friendship_pts"]),
            "passives": [p for p in passives if p],
            "gender": GENDERS.get(r["gender"], ""),
            "owner": label,
        })
        gender_seen[GENDERS.get(r["gender"], "unknown")] += 1

    os.makedirs(args.out, exist_ok=True)
    all_pals = []
    print("\nPer-owner Pal counts:")
    for label in owner_order:
        pals = sorted(rosters[label], key=lambda e: e["species"])
        all_pals.extend(pals)
        if label in player_labels:
            payload = {"version": 1, "targetLevel": TARGET_LEVEL, "player": label, "pals": pals}
            dest = os.path.join(args.out, f"pals-{safe_name(label)}.json")
            json.dump(payload, open(dest, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
            print(f"  {label:16} {len(pals):4} Pals -> {os.path.relpath(dest, HERE)}")
        else:
            print(f"  {label:16} {len(pals):4} base Pals (guild) -> pals-all.json only")
    json.dump({"version": 1, "targetLevel": TARGET_LEVEL, "pals": all_pals},
              open(os.path.join(args.out, "pals-all.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print(f"  {'ALL':16} {len(all_pals):4} Pals -> out/pals-all.json")

    write_review(args.out, sp_seen, pv_seen, id_maps, app_pals, app_pass, pass_effect,
                 counted, base_counted, skipped_human, gender_seen)
    print(f"\nReview report -> out/ingest_review.md")


def write_review(out_dir, sp_seen, pv_seen, id_maps, app_pals, app_pass, pass_effect,
                 counted, base_counted, skipped_human, gender_seen):
    L = ["# Save ingestion review\n",
         f"Parsed **{counted}** owned Pals ({counted - base_counted} player-owned, "
         f"{base_counted} assigned to guild bases; skipped {skipped_human} humans/NPCs).\n",
         # A sudden all-unknown reading here means the Gender tag moved in a patch;
         # breeding pair feasibility silently degrades without it (docs/BREEDING.md).
         f"Gender: **{gender_seen['Male']}** Male / **{gender_seen['Female']}** Female / "
         f"**{gender_seen['unknown']}** unknown.\n",
         "Everything below is present in the save but **missing from the app's reference "
         "data** (`data/pals.json` / `data/passives.json`). Combat-relevant passives are "
         "listed first — those silently score as 0. The fix is to re-run the game-data "
         "extraction (`tools/gamedata/README.md`) then `import_gamedata.py`; a non-empty "
         "report usually just means the export predates a game patch.\n"]

    # --- passives ---
    rows = []
    for pid, cnt in pv_seen.items():
        name = id_maps["passives"].get(pid)
        known = name in app_pass if name else False
        eff = pass_effect.get(pid)
        combat = bool(eff)
        if known:
            continue
        rows.append((combat, cnt, pid, name, eff))
    rows.sort(key=lambda r: (not r[0], -r[1]))
    L.append("\n## Passives needing review\n")
    if not rows:
        L.append("_None — every passive in the save maps to a known passive._\n")
    else:
        L.append("| Combat? | Pals | Internal ID | Display name | Save-pal effect |")
        L.append("|---|---:|---|---|---|")
        for combat, cnt, pid, name, eff in rows:
            e = "" if not eff else f"Atk {eff['atk_pct']:+g}%, Def {eff['def_pct']:+g}%".replace("Atk +0%, ", "").replace(", Def +0%", "")
            flag = "**YES**" if combat else "no"
            L.append(f"| {flag} | {cnt} | `{pid}` | {name or '—'} | {e} |")

    # --- species ---
    srows = []
    for sid, cnt in sp_seen.items():
        name = map_species(sid, id_maps)
        if name in app_pals:
            continue
        srows.append((cnt, sid, name))
    srows.sort(key=lambda r: -r[0])
    L.append("\n## Species needing review\n")
    if not srows:
        L.append("_None — every owned species maps to a known species._\n")
    else:
        L.append("| Pals | Internal ID | Display name | Note |")
        L.append("|---:|---|---|---|")
        for cnt, sid, name in srows:
            note = "no name mapping" if not name else "not in data/pals.json (export predates a patch?)"
            L.append(f"| {cnt} | `{sid}` | {name or '—'} | {note} |")

    open(os.path.join(out_dir, "ingest_review.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
