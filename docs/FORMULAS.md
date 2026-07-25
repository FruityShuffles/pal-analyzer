# Palworld Combat Formulas — Reference

This document is ground truth for `scoring.py`. Every fact here was directly verified during the research/planning conversation (hand computation, or reading the source wikitext directly rather than trusting a summary) — do not re-derive or second-guess without reason.

## 1. Per-stat growth formula

Every Pal's HP/Attack/Defense at a given level, including implemented combat
augmentations, is:

```
EffectiveStat = SpeciesStat + FriendshipStat * TrustRank

HP      = floor( floor( 500 + 5*Level + EffectiveHP      * 0.5   * Level * (1 + HP_IV%) )      * (1 + HP_PassiveBonus%)      * (1 + 0.03*SoulHP)      * (1 + 0.05*Stars) )
Attack  = floor( floor( 100 +          EffectiveAttack * 0.075 * Level * (1 + Attack_IV%) )  * (1 + Attack_PassiveBonus%)  * (1 + 0.03*SoulAttack)  * (1 + 0.05*Stars) )
Defense = floor( floor( 50  +          EffectiveDefense* 0.075 * Level * (1 + Defense_IV%) ) * (1 + Defense_PassiveBonus%) * (1 + 0.03*SoulDefense) * (1 + 0.05*Stars) )
```

Where:
- `500 / 100 / 50` are **universal constants**, identical for every Pal in the game regardless of species.
- `HP_Stat / Attack_Stat / Defense_Stat` are **per-species growth coefficients** — see `DATA_SOURCES.md` for where these come from (`PalStat` Cargo table).
- `IV%` (in-game: "Talent") is a per-individual-Pal hidden value stored as an integer 0–100 in the save file. Convert with:
  ```
  IV% = TalentInt * 0.3 / 100
  ```
  (e.g. Talent 100 → 30% bonus, Talent 50 → 15%, Talent 0 → 0%.)
- `PassiveBonus%` is the **sum** of that stat's percentage bonuses from all of the Pal's equipped passive skills — see `DATA_SOURCES.md` for the `PassiveSkillEffect` table this comes from. **Verified 2026-07-18:** the wiki data has no max-HP passive at all, so `HP_PassiveBonus%` is always 0 in practice; only `Attack` and `Defense` passives ever contribute. Additive stacking across multiple passives affecting the same stat is confirmed directly from the wiki's own explanation: *"HP_Bonus%, Attack_Bonus%, and Defense_Bonus% are each stat's bonuses added together as decimals. For example, if you have Musclehead (30% attack bonus) and Ferocious (20% attack bonus) you would add them as .3 + .2 = .5"*.
- `SoulHP` / `SoulAttack` / `SoulDefense` are independent ranks 0–20, each adding 3% per rank. `Stars` is Condensing rank 0–4, adding 5% per star to all three combat stats. Passive, soul, and condenser multiplier classes multiply each other inside the **single outer floor**; there are still exactly two floors and no intermediate rounding.
- `TrustRank` is 0–10. Each species' friendship stat is added to its species stat once per Trust rank, before level scaling. The friendship-term × level-slope interaction shown above is the natural reading of the datamined formula, but has not yet been independently rounding-verified against an in-game Pal.
- Costs, save fields, thresholds, and source notes for these systems are in `AUGMENTS.md`. Awakening and Work Speed remain intentionally excluded from combat scoring.

### Known typo trap in the primary source

If you ever re-read `palworld.wiki.gg/wiki/Pal_Stats` directly: one paragraph in the article's prose (not its final formula block) writes the Defense base as "100 +". **That is a typo in the source article.** The correct base is **50**, confirmed by: (a) the same page's "Basics" section, which states base Defense = 50 for every Pal at level 0; (b) the page's own final "Formulas with rounding included" section, which correctly uses 50; and (c) our own hand-computation cross-check against real Pals, which only matches known values when using 50. Use 50. This is a good example of why raw source data was cross-checked internally rather than trusted verbatim from a single passage.

## 2. Damage model — why the combat score is what it is

Palworld's damage formula is a flat ratio, not a saturating "armor formula": `Damage ∝ Attacker's Attack / Target's Defense`. Doubling a target's Defense exactly halves incoming damage — there's no diminishing-returns curve like many other games use.

This means survivability (hits absorbed before dying) is `∝ HP × Defense`. Modeling a symmetric duel between two Pals X and Y trading hits simultaneously with equal move power: the time for X to kill Y is `T_Y = (HP_Y × Defense_Y) / Attack_X`. X wins the duel iff `T_Y < T_X`, which reduces algebraically to:

```
X wins iff   HP_X × Attack_X × Defense_X   >   HP_Y × Attack_Y × Defense_Y
```

So the **raw product of all three stats** directly predicts the winner of a fair, symmetric fight. The combat score is the cube root of that product — a monotonic rescale back to normal stat magnitude for display purposes only; it does not change any ranking:

```
CombatScore(HP, Attack, Defense) = (HP * Attack * Defense) ** (1/3)
```

## 3. The score is level-dependent — compute it at two levels

Because each stat is `universal_constant + species_slope * Level * (1+IV)`, the *relative* weight of the species-specific slope vs. the shared universal constant changes with level:
- At **low levels**, the universal constant dominates — scores compress, and species differences barely show.
- At **high levels**, the slope dominates — scores spread out, and species growth-rate differences matter a lot.

**Rank order between two Pals is therefore not guaranteed to be the same at level 1 vs. max level.** This isn't theoretical — it was proven with real species growth data (IV=0, no passives, for isolating the effect):

| Pal | HP_Stat | Attack_Stat | Defense_Stat | Score @ Level 1 | Score @ Level 50 |
|---|---|---|---|---|---|
| Mammorest | 150 | 85 | 90 | ~151.0 | ~899.6 |
| Kitsun | 100 | 115 | 100 | ~150.6 | ~901.8 |

Mammorest is ahead at level 1; **Kitsun has overtaken it by level 50.**

### Implication for the tool

Compute and display **two** scores per owned Pal:
- `CurrentScore` — at the Pal's actual current level and actual Condensing, Soul, and Trust ranks.
- `TargetScore` — at the selected target level (default: 80, the v1.0 cap), with each enabled investment assumption raised to its maximum. Disabling an assumption keeps that Pal's actual rank for the corresponding system.

The difference (`TargetScore - CurrentScore`) is the "headroom" signal that actually answers "is this Pal worth investing further into?" — a mediocre `CurrentScore` with a high `TargetScore` is a good investment candidate; a Pal already near its assumed ceiling is not.
