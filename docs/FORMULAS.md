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
- `PassiveBonus%` is the **sum** of that stat's percentage bonuses from all of the Pal's equipped passive skills — see `DATA_SOURCES.md` for the table this comes from. **Revised 2026-07-25:** the earlier note here said `HP_PassiveBonus%` is always 0. That was true of the *wiki* data only. `DT_PassiveSkill_Main` in the game files has two displayable max-HP passives — **God of Destruction** (Atk +40%, Def +20%, **Max HP −50%**) and **World Tree Seedbed** (**Max HP −20%**) — so all three stats can now carry a passive bonus. Only effects targeting the Pal itself count: `ToTrainer` effects (Vanguard, Stronghold Strategist) buff the *player*, not the Pal, and are excluded. This covers only the three flat stat effects; **element-conditional damage boosts are a separate multiplier class handled in §2**, because they never touch the displayed Attack stat. Additive stacking across multiple passives affecting the same stat is confirmed directly from the wiki's own explanation: *"HP_Bonus%, Attack_Bonus%, and Defense_Bonus% are each stat's bonuses added together as decimals. For example, if you have Musclehead (30% attack bonus) and Ferocious (20% attack bonus) you would add them as .3 + .2 = .5"*.
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

### Element boosts (added 2026-07-25)

"30% increase in Fire attack damage" passives — Flame Emperor, Lunker, Pyromaniac and 22 others — raise **damage dealt**, not the Attack stat. They are conditional on the move's element, so they cannot enter the stat formula in §1 and they never move the number on the Pal's status screen. They enter here instead, as their own multiplier on the attacker's side:

```
Damage ∝ Attack * (1 + ElementBoost%) / TargetDefense
```

The duel algebra carries through unchanged with `Attack → Attack * (1 + ElementBoost%)`, so:

```
CombatScore = (HP * Attack * (1 + ElementBoost%) * Defense) ** (1/3)
```

**`ElementBoost%` is a max, not a sum.** Every attack move is exactly one element, so a Pal can only ever cash in the boosts for a single element at a time. The rule is: for each element the Pal *has*, sum the boosts naming that element across its passives; take the largest such sum. Boosts for an element the Pal doesn't have are worth zero. Two examples:

- **Penking Lux** (Water/Electric) with **Lunker** (Water +20 / Ice +20 / Defense +20) → the Water leg matches, so **+20% Defense and +20% effective Attack**. The Ice leg is unusable and contributes nothing.
- A Fire/Water Pal with **Flame Emperor** (Fire +30) and **Lord of the Sea** (Water +30) → **+30%, not +60%** — it can use one or the other, never both. But Lunker (Water +20) *alongside* Lord of the Sea (Water +30) is **+50%**, because they name the same element.

This assumes the Pal is played using its best-boosted element, which is the intended reading of "is this Pal good in a fight". Moves off the Pal's own element type are not modeled.

**`ElementResist_*` is deliberately excluded.** Resistance keys off the *incoming* attack's element, which nothing in a Pal's own record can predict, so it has no defensible place in a single-number score.

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

**Amended 2026-07-25:** passives are a fourth assumption axis alongside condense/souls/trust. When the "Buy passives" / "+ top-tier passives" chips are on, `TargetScore` is computed from the *planned* passive set (§4) instead of the Pal's actual one. `CurrentScore` never takes any assumption — it is always actual level, actual augments, actual passives.

## 4. The passive planner — which passives to buy

A Pal has **4 passive slots**, and passives can be bought onto any Pal (see `AUGMENTS.md` §5 for the mechanic and its gating). Given a Pal's current 0–4 passives, the planner picks the best reachable set.

**Objective.** Passive bonuses are additive within a stat and the three stats enter the score as one multiplier class each (§1), so a passive set's whole effect on the score is the product

```
M(set) = (1 + ΣAttack%) * (1 + ΣDefense%) * (1 + ΣMaxHP%) * (1 + BestElementBoost%)
```

and `CombatScore ∝ M^(1/3)`. `M` is **level-independent**, which is why the planner optimizes it rather than the score itself — otherwise the recommended set would drift as the target level moved.

The element term makes the objective **species-dependent**: the same passive set is worth different amounts on different Pals, so the plan cache is keyed on the Pal's elements as well as its passives. It also means a passive with no flat stats at all can be the best thing in a slot — Flame Emperor (+30% Fire damage) beats Musclehead (+30% Attack) on a Fire Pal once flat attack is already stacked, because it multiplies a separate class. Conversely the same passive is dead weight on a Water Pal and gets evicted. Note the buyable rank-1 element boosts are only +10%, so they lose to the flat options in most slots; the ones worth keeping are usually the rank 3–4 boosts (+20–30%) a Pal already has.

**This is a balance problem, not a sort.** Because `M` is a product of sums, the marginal value of an attack passive falls as attack accumulates. Two cases where taking the largest available attack bonuses is wrong:

| Pal has | greedy pick | `M` | optimal pick | `M` |
|---|---|---|---|---|
| Demon God, Lunker | + Musclehead, Ferocious | `1.80 × 1.25 = 2.250` | **+ Musclehead, Burly Body** | `1.60 × 1.45 = 2.320` |
| Legend | + Musclehead, Ferocious, Burly Body | `1.70 × 1.40 = 2.380` | **+ Musclehead, Burly Body, Heavyweight** | `1.50 × 1.60 = 2.400` |

The search is therefore exhaustive over every subset of size ≤4 of (existing passives ∪ buyable pool) — at most C(17,4) = 2380 per Pal, cached per passive signature.

**Passives can be overwritten, never deleted.** A purchase either fills an empty slot or replaces an existing passive, so a candidate set is only *reachable* when `purchases ≥ passives dropped`. This constraint is load-bearing, not bookkeeping: without it the search treats "shed this Pal's junk passives" as free and reports gains that can't be bought. It also fixes the cost curve's baseline — the zero-purchase plan is always the Pal's existing set, junk included.

**Mixed-sign passives are not prunable.** Sadist (+15 Atk / −15 Def) has `M = 1.15 × 0.85 = 0.9775 < 1` in isolation, so it looks like it could never be worth a slot. It can: added to a set with `A=0, D=0.40`, the change is `0.15(D − A) − 0.0225 = +0.0375`. Any pruning heuristic based on a passive's standalone `M` is wrong; the full search is what makes the planner correct.

**Componentwise-dominated passives are not prunable either** — a separate trap, and a more tempting one. Ferocious (+20 Atk) is dominated by Musclehead (+30 Atk) on every component, so it looks safe to drop from the buyable pool: both cost one purchase, so surely you would always rather buy the stronger one. That reasoning silently assumes you pick *one of the two*. You can take **both** — bonuses are additive across four slots, and the blank-Pal optimum below is exactly `Musclehead + Ferocious + Burly Body + Heavyweight`. Dropping Ferocious returns `1.30 × 1.40 × 1.10 = 2.002` in place of `2.100`, a 5% loss. This was implemented as a 4× speedup and reverted: it broke 2,931 of 4,770 real cases. `tools/js_check.js` now brute-forces `planPassives()` against an unpruned search, so any future attempt fails loudly rather than quietly costing score.

**Evictions need no protection list.** The maximizer keeps anything worth more per slot than the best buyable option, so Legend, Demon God and Lucky survive automatically. It correctly evicts negatives, junk, and God of Destruction (`1.40 × 1.20 × 0.50 = 0.84` — a net loss despite two positive legs). Its one blind spot is deliberate: a passive with no combat effect scores 0, so Artisan and the work-speed passives are evicted even though they matter on base workers. That is a limit of a combat-only score, surfaced in the UI rather than patched around.

**Blank-Pal ceiling.** The best buyable four with no top-tier purchases is Musclehead + Ferocious + Burly Body + Heavyweight → `1.50 × 1.40 = 2.10` → **×1.281 score**. Nearly every Pal can reach roughly this, so filling slots *compresses* the ranking rather than reshuffling it: Pals carrying junk gain most, Pals already holding Legend or Demon God gain least because their slots are occupied. The discriminating output is therefore cost, not rank — hence the `Gain/100k` column.

## 5. Projecting a Pal that doesn't exist yet — the bred child

The breeding panel (`docs/BREEDING.md`) has to score a Pal nobody owns. It reuses this
document's math unchanged — `computeAt()` at the target level with the assumption chips —
and only has to supply the two inputs a hypothetical Pal doesn't come with:

- **Passives.** The inherited unbuyable set is treated exactly like an owned Pal's
  existing passives: free to keep, and costing a purchase to drop. So the planned set is
  just `planPassives(inherited, tiers, elements)` — §4 applies verbatim, including the
  reachability constraint that makes the zero-purchase plan the inherited set itself.
- **IVs.** Projected as the **expected** result of inheritance,
  `E[IV] = (1.75/3)·(ivA+ivB)/2 + (1−1.75/3)·50`, not a best case. Two 100-IV parents
  average 79, so a bred Pal typically *loses* IVs against one already maxed — which is
  the honest signal that stops the tool recommending you replace a good Pal. The opt-in
  perfect-IV chip reframes the column as a ceiling; the derivation is in `BREEDING.md` §4.

A bred Pal also starts at **0★ / 0 souls / T0**, so its remaining augment bill is the full
48 fodder / 30 souls / 10 peaches — the same `costToFinish()` the ranked table uses.

Note the score of a bred child is *not* level-dependent in the §3 sense: it is only ever
computed at the target level, because there is no "current" state for a Pal that hasn't
hatched.
