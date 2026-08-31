# Pal Augmentation Systems — Reference

Reference for the augmentation systems **beyond** level and IVs: **Condensing**, **Pal Enhancement (souls)**, **Trust**, **passive skill purchase** (§5, added 2026-07-25), and **Awakening**. Researched 2026-07-19 via web research (patch notes, palworld.wiki.gg, save-editor source code); facts are cited inline and anything unconfirmed is flagged. **Condensing, combat Soul ranks, and Trust were implemented on 2026-07-19**; the live scoring specification is in `docs/FORMULAS.md`. Awakening and Work Speed remain intentionally excluded. This document remains the ground truth for costs, thresholds, save fields, and research context.

**Version context:** current game version is **v1.0.1** (2026-07-15). v1.0 (2026-07-10, the 1.0 release out of early access) changed condensation costs and added Awakening. Trust shipped in **v0.6.0 "Tides of Terraria"** (2025-06-25). Soul cap was doubled in **v0.4.11 "Feybreak"** (2024-12-23). v1.0 also raised the level cap to **80** (was 65 in 0.6.x, 55 before that) — relevant to the app's target-level default of 55. The community wiki still lags v1.0 in places (see the freshness note in CLAUDE.md); where the wiki disagreed with official patch notes, the patch notes win below.

## 1. How the bonuses enter the stat formula

Per [palworld.wiki.gg/wiki/Pal_Stats](https://palworld.wiki.gg/wiki/Pal_Stats) (rounding analysis credited to u/blahable's datamine): still **exactly two floors**, but the outer floor wraps the product of **all** multiplicative bonus classes:

```
Stat = floor( floor( base_part ) * (1 + Passive%) * (1 + Soul%) * (1 + Condenser%) )

HP      = floor( floor( 500 + 5*L + (HP_Stat + friendship_hp * TrustRank)          * 0.5   * L * (1+IV%) ) * (1 + HP_Passive%)      * (1 + 0.03*Rank_HP)      * (1 + 0.05*Stars) )
Attack  = floor( floor( 100 +       (Attack_Stat + friendship_shotattack * TrustRank) * 0.075 * L * (1+IV%) ) * (1 + Attack_Passive%)  * (1 + 0.03*Rank_Attack)  * (1 + 0.05*Stars) )
Defense = floor( floor( 50  +       (Defense_Stat + friendship_defense * TrustRank)  * 0.075 * L * (1+IV%) ) * (1 + Defense_Passive%) * (1 + 0.03*Rank_Defence) * (1 + 0.05*Stars) )
```

- The three multiplier classes (passives, souls, condenser) are **multiplicative with each other**; passives remain **additive within** their class. No extra floors between the multipliers.
- **HP gains an outer multiplier stage.** Soul and condenser bonuses apply to HP — including the `500 + 5*L` part. Max-HP passives are rare but real (God of Destruction −50%, World Tree Seedbed −20%), so `HP_Passive%` is not always 0; the earlier note here saying no HP passives exist described the superseded wiki data. See `FORMULAS.md` §1.
- **Trust is different in kind:** it adds a flat per-species amount to the **base stat, before level scaling** (see §4) — modeled above as `friendship_* * TrustRank` added to the species stat. Caveat: the wiki demonstrates the addition on the base stat; whether the game multiplies the friendship term by the level slope exactly as written above is our (natural) reading, not an independently verified rounding-level fact — verify against an in-game Pal when implementing. All defaults (rank 0 / 0 stars) reduce every new term to identity, so the existing Mammorest/Kitsun anchors in `scoring_check.py` remain valid.
- Awakening (§6) is a further overall multiplier, numbers unconfirmed — out of scope for now.

## 2. Condensing (Pal Essence Condenser)

- **+5% per star to HP, Attack, and Defense** (same value all three; Work Speed NOT affected). Max **4 stars = +20%**. There is no 5-star rank — "level 5" seen in tables is the **Partner Skill level** reached at 4 stars (skill starts at 1, +1 per star). [wiki/Pal_Condensation](https://palworld.wiki.gg/wiki/Pal_Condensation), [game8](https://game8.co/games/Palworld/archives/440237)
- 4 stars also grants +1 to all Work Suitabilities — combat-irrelevant.
- **Cost (v1.0, current): 4 / 8 / 12 / 24 same-species Pals per star = 48 total.** Official v1.0 changelog wording: "from 116 total to 48 (4/8/12/24)". Pre-1.0 it was 4/16/32/64 = 116 — many guides and even wiki pages still show the old table; the wiki's Condenser page briefly showed 4/8/16/24 (=52) mid-update. **Trust the official 48.** [paldb v1.0.0 changelog](https://paldb.cc/en/v1.0.0), [game8 1.0 notes](https://game8.co/games/Palworld/archives/607287)
- Already-condensed fodder counts as itself plus everything it consumed (a 1-star Pal counts as 5). Variants (e.g. Jolthog Cryst) are separate species for condensing.
- Cost calibration: fodder is farmable via breeding — **moderate, much cheaper post-1.0**.

## 3. Pal Enhancement (Statue of Power / Pal Souls)

- Four independently enhanceable stats: HP, Attack, Defense, Work Speed. **20 ranks per stat, +3% per rank, max +60% per stat.** (Was 10 ranks / +30% until Feybreak v0.4.11 doubled it and added Giant Pal Souls for ranks 11–20.) [wiki/Pal_Enhancement](https://palworld.wiki.gg/wiki/Pal_Enhancement), [gamerant on the Feybreak change](https://gamerant.com/palworld-feybreak-update-pal-enhancement-change/)
- **Souls per stat:** ranks 1–4 cost 1/2/3/4 **Small** (10 total); 5–7 cost 1/2/3 **Medium** (6); 8–10 cost 1/2/3 **Large** (6); 11–20 cost **Giant** souls totaling 30 (exact per-rank split for 11–20 not itemized in any single source; the 30 total is consistent everywhere). **Full max, one stat: 10S + 6M + 6L + 30G. All four stats: 40S + 24M + 24L + 120G.**
- **Crusher conversion: 4 Small = 2 Medium = 1 Large** (2:1 per step, both directions). **Giant souls cannot be crafted upward** — only broken down (1 Giant → 2 Large). [wiki/Giant_Pal_Soul](https://palworld.wiki.gg/wiki/Giant_Pal_Soul)
- Cost calibration: S/M/L farmable (ground wisps, dungeon chests, dark-Pal drops) — cheap-to-moderate. **Giant souls are the bottleneck** (raid bosses, 100% from Panthalus, rare ground spawns) and dominate any "max this Pal" cost. Souls are a **shared account-level wallet** — assuming max souls on every Pal simultaneously is a ranking device, not an achievable state.

## 4. Trust

- Per-Pal cumulative point counter, **rank 0–10**. Each rank adds a flat per-species **"friendship stat"** to base HP / Attack / Defense (and Work Speed), applied **before level scaling and all multipliers**. Wiki example: Lamball base HP 70, +5.5/rank → 125 base at rank 10. Linear: `effective_base = base + friendship_stat * rank`. Because it's additive to base, it's proportionally strongest on weak species (the wiki frames it as making weak Pals viable). No other combat effects — the stat boost is the whole mechanic. [wiki/Trust](https://palworld.wiki.gg/wiki/Trust)
- **Per-species friendship values are NOT in our wiki Cargo pull.** They exist in palworld-save-pal's `data/json/pals.json` as `friendship_hp`, `friendship_shotattack`, `friendship_defense`, `friendship_craftspeed` (e.g. Melpaca: 4.5/3.5/2.9/0) — same repo `build_id_maps.py` already consumes (keep its attribution). [palworld-save-pal](https://github.com/oMaN-Rod/palworld-save-pal)
- **Rank thresholds (cumulative points):** 6,000 / 13,000 / 21,000 / 30,000 / 40,000 / 55,000 / 80,000 / 110,000 / 150,000 / **200,000** for rank 10. Verified against palworld-save-pal `data/json/friendship.json` (`Friendship_Rank_0..10`). That file also defines negative ranks (−1/−2/−3 at −1,000/−10,000) but no confirmed way to lose trust exists — treat negatives as latent.
- **Gain rates:** in party ≈100 pts/hr real time (Pal need not be on-field); at base ≈1 pt/hr (negligible); petting +10; Little Kinship Peach +2,000; **Kinship Peach +20,000** (~30,000 gold at Bounty Shop 1, 100% from Hard expedition/enemy-camp treasure boxes; internal ID `AffectionFruit_01`). The ≈100/hr figure is the wiki's approximation, not datamined. [game8 Trust](https://game8.co/games/Palworld/archives/531753), [paldb Kinship_Peach](https://paldb.cc/en/Kinship_Peach)
- **Cost to max: 200,000 pts ≈ 10 Kinship Peaches (~300k gold) or ~2,000 party-hours.** Calibration: **cheap-to-moderate** via peaches; absurd via time alone.

## 5. Passive skill purchase (the 4 passive slots)

Unlike the systems above, this one is **not a rank to raise** — it's a set of 4 slots whose contents can be bought. A Pal has **4 passive slots**; a purchase either fills an empty slot or replaces an existing passive, at the same price either way. This is what the app's passive planner models (`FORMULAS.md` §4).

- **Two price tiers.** Ordinary passives cost **~50,000 gold each**. Top-tier passives need a much costlier one-time consumable instead of gold. Both figures are the **player's own report from the live game**, not datamined — the 50k constant is `PASSIVE_GOLD` in `pal_analyzer_template.html`, and the consumable has no gold price at all (the planner's `PREMIUM_GOLD_EQUIV` is a stated assumption purely so one sortable denominator exists). Correct either constant if the in-game numbers differ.
- **The tier split is `DT_PassiveSkill_Main.Rank`**, imported verbatim as `rank` in `data/passives.json`: **1–3** = ordinary/gold, **4** = top tier/consumable, **5** = World Tree exclusives, **−1 to −3** = the red-arrow negative traits. This matches the observed split exactly — Musclehead is rank 2, Ferocious and Burly Body rank 3, Demon God and Legend rank 4.
- **Eligibility is `AddPal`, not rank.** `DT_PassiveSkill_Main.AddPal` is the game's own "legal on an ordinary Pal" flag, imported as `add_pal`. It is load-bearing and independent of rank: **Lunker** (+20 Def, rank 4), **Whopper** (+5 Def, rank 3) and **Otherworldly Cells** (+10 Atk, rank 1) are all `AddPal:false` — boss/alpha-only. **Legend** (rank 4) is in no pool at all and **Lucky** (rank 4) is `AddRarePal` (shiny-only). All of these can be *kept* on a Pal that already has them but can never be *bought*, so a rank-only filter would offer purchases that don't exist.
- **Full buyable combat pool** (`add_pal && 1 ≤ rank ≤ 3`, nonzero combat stat): Musclehead (+30 Atk), Ferocious (+20 Atk), Burly Body (+20 Def), Heavyweight (+20 Def), Hooligan (+15 Atk), Serenity (+10 Atk), Brave (+10 Atk), Hard Skin (+10 Def), plus the mixed-sign Sadist (+15/−15), Masochist (−15/+15) and Aggressive (+10/−10). The top tier (`add_pal && rank == 4`) is exactly two: **Demon God** (+30 Atk/+5 Def) and **Diamond Body** (+30 Def).
- **Buyable element boosts.** There is also one rank-1 `add_pal` element-damage passive per element, each **+10%**: Pyromaniac (Fire), Hydromaniac (Water), Capacitor (Electric), Fragrant Foliage (Grass), Power of Gaia (Ground), Coldblooded (Ice), Veil of Darkness (Dark), Blood of the Dragon (Dragon), Spirit of Zen (Neutral). The planner only ever offers a Pal the boost for an element it actually has. The strong element boosts are **not** buyable: the rank-3 "Emperor/Lord" singles (+30%) and the rank-4 duals — Eternal Flame, Invader, Savior, Siren of the Void (+30% to two elements) — plus Lunker and Whopper are all `add_pal:false`.
- `LotteryWeight` is also imported (`lottery_weight`) for reference. It governs the *roll* odds on wild/bred Pals, not the shop, so nothing scores off it — but it cleanly separates the common rank-3 passives (weight 100) from the rare rank-4 ones (weight 5).
- **Cost calibration: cheap.** Filling all 4 slots on a Pal is 200k gold and takes it to **×1.281 combat score** from blank. Gold is the least scarce of the resources in this document, which is why the planner's headline output is `Gain/100k` rather than raw score.

## 6. Awakening (v1.0 — flagged, numbers unconfirmed)

One-time permanent per-Pal boost of **~8% to overall stats** (community-measured 7–10%; no official figure). Costs Awakening Gems combined from elemental Radiant Gems farmed in the World Tree endgame zone (unlock ≈ all Tower Bosses + Panthalus questline, ~level 80). Displayed on the Pal status screen as a stat layer distinct from Souls. Exact bonus, gem quantities, and formula placement all **unconfirmed** as of 2026-07-19 — the system is days old. Revisit once the wiki/dataminers settle; until then it is intentionally excluded from scoring. [nexttier guide](https://nexttier.pro/guide/palworld-awakening), [sportskeeda](https://www.sportskeeda.com/mmo/how-awaken-pals-palworld-awakening-system-explained)

## 7. Save-file representation (Level.sav character records)

All fields live in the same `SaveParameter` block `ingest_save.py` already parses; each is one `field()` call. Encodings confirmed from save-editor source ([KrisCris/Palworld-Pal-Editor](https://github.com/KrisCris/Palworld-Pal-Editor) `pal_entity.py`, corroborated by palworld-save-pal and PalworldSaveTools):

| Field | Type | Meaning | Encoding gotchas |
|---|---|---|---|
| `Rank` | Int | Condense rank | **1 = zero stars** … 5 = 4 stars. **Absent when value is 1** (editors pop the key) → default missing to 0 stars. `Stars = Rank − 1`. |
| `Rank_HP` | Int | Soul rank, HP | 0–20 legit. **Absent when 0.** Bonus% = `3 * rank`. |
| `Rank_Attack` | Int | Soul rank, Attack | same |
| `Rank_Defence` | Int | Soul rank, Defense | **British spelling** — vs the IV field `Talent_Defense` (American). Easy to trip on. |
| `Rank_CraftSpeed` | Int | Soul rank, Work Speed | combat-irrelevant |
| `FriendshipPoint` | Int | Trust, cumulative points | Derive rank by thresholding against §4 table. Confirmed in palworld-save-pal source (`psp-core/src/domain/pal.rs`). |

## 8. Known discrepancies (do not re-litigate without new evidence)

- **Condense fodder split:** official changelog 4/8/12/24 (48) vs wiki page 4/8/16/24 (52) vs old 116 table — go with official 48.
- **Defense base 50 vs 100:** the wiki Pal_Stats prose typo (see `FORMULAS.md`) is independent of everything here; nothing in this research contradicts 50.
- **"5-star condensing"** — doesn't exist; it's Partner Skill level 5 at 4 stars.
- Giant-soul per-rank split (11–20), Awakening numbers, and the 100 trust-pts/hr rate are the known soft spots.
