# Palworld Breeding — Reference

Ground truth for the breeding-path suggester, in the same spirit as `FORMULAS.md` and
`AUGMENTS.md`: everything here was read out of the game's own DataTables or verified
against an independent implementation, not taken from a guide. The scoring half of the
feature lives in `FORMULAS.md`; this document covers what breeding produces and what it
costs. Implemented 2026-07-26.

**Verification status.** The child-species algorithm below was diffed against
[`tylercamp/palcalc`](https://github.com/tylercamp/palcalc)'s precomputed
`PalCalc.Model/breeding.json` — an independent CUE4Parse-based implementation — over all
**44,552 parent pairs the two game builds share: 0 mismatches**. A 109-case slice of that
comparison is inlined in `breeding_check.py` so the checker stays offline, and
`tools/js_check.js` runs the same fixture through the shipped JS so the two ports cannot
drift.

---

## 1. Which Pal an egg hatches into

Three rules, in order. The first that applies wins.

1. **Same species × same species → that species.** Bypasses everything below, including
   unique combos, and is the only way to breed a legendary.
2. **Unique combo.** `DT_PalCombiUnique` holds **253 usable rows** (258 exported; 5 name
   species with no English name yet). Symmetric in the parents, with exactly one
   exception — see *Gender* below.
3. **Nearest breeding rank.** Otherwise:
   ```
   childRank = floor((rankA + rankB + 1) / 2)
   child     = the candidate minimising |combi_rank − childRank|
   ```
   `combi_rank` is the game's `CombiRank` (range 10–3080; `9999` is a sentinel on
   unreleased Pals). **The `+1` is inside the floor** — this is round-half-up, not
   truncation. Sources writing `floor((A+B)/2)` are wrong.

### The candidate pool is not "every Pal"

Two exclusions, each individually load-bearing. The pool is **183 species** out of 301:

- **`ignore_combi` species are never a rank-rule child** — 64 legendaries, raid bosses
  and event Pals. They remain perfectly legal *parents*; only the child side is
  restricted. Frostallion can be bred (via rule 1) but can never be the answer to rule 3.
- **A species that is the child of a unique combo can only be produced by that combo**,
  so it is struck from the pool too (116 species). Omitting this filter produced 1,844
  wrong children in testing — it is the single most commonly missed rule.

### Ties, and why they matter

Ranks are multiples of 10, so a `childRank` ending in 5 sits exactly midway between two
candidates. This is **not** an edge case: **12.4% of all pairs** hit an exact distance
tie. Ties break by:

1. **higher `combi_priority`** (`CombiDuplicatePriority`) — verified empirically, since
   public sources contradict each other. Across all 44,849 pairs, descending priority
   gives 60 mismatches against palcalc; ascending gives 14,070.
2. then the **non-variant** Pal, then the name, so the result never depends on object
   iteration order.

`combi_priority == combi_rank × 100` for every species **except 9**, all
`ZukanIndexSuffix == "B"` regional forms sitting at 571–581, far below any normal row.
So in practice the priority tiebreak *is* the prefer-the-ordinary-Pal rule, and it only
ever fires where it matters. `breeding_check.py` pins cases from this set deliberately.

---

## 2. Gender

There are **no genderless Pals**. `male_probability` is a percentage per species: 255 are
50/50, 44 are skewed, the extremes being Bellanoir and Queen Bee at 10% male and Woolipop
at 90%.

Gender enters in three places and *not* in a fourth:

- **Pair legality.** A pair needs one male and one female. Two same-gender Pals are never
  a pair, and — the trap that makes this a matching problem rather than a set union — a
  Pal cannot breed with *itself*.
- **One unique combo depends on it.** Katress × Wixen is the game's only gender-dependent
  outcome: male Katress + female Wixen → **Wixen Noct**; female Katress + male Wixen →
  **Katress Ignis**. Every other combo row is `EPalGenderType::None` on both parents.
- **Multi-step cost.** An intermediate has to hatch the *right* gender to be usable in the
  next step, so its egg count is multiplied by `1 / P(gender)` — usually ×2, but ×10 for
  the 10%-male species.
- **It does not affect passive inheritance at all.** For a one-step plan the child's own
  gender is irrelevant, so it never enters the egg estimate.

`ingest_save.py` reads `Gender` (an `EnumProperty`, `EPalGenderType::Male|Female`) with
the parser that was already there. The app treats **unknown gender as a first-class
value**: a roster imported before gender was captured has none, and excluding unknowns
would render the panel empty on first use and look broken. Such pairs are shown, badged
`⚠`, and ranked below verified ones.

---

## 3. Passive inheritance

From /u/mgxts's disassembly of the breeding routine, the model palcalc also uses. Two
independent draws:

| passives drawn from the parents | P | extra lottery passives added | P |
|---|---|---|---|
| 1 | 0.40 | 0 | 0.40 |
| 2 | 0.30 | 1 | 0.30 |
| 3 | 0.20 | 2 | 0.20 |
| 4 | 0.10 | 3 | 0.10 |

Capped at 4 total. Four lottery passives is impossible — the game indexes a 4-element
array with a 0..3 result. The passives drawn are chosen **uniformly at random from the
combined, deduplicated pool of both parents' passives**. There is no "distribute the
traits 2/2 across the parents" effect; the pool is a flat union.

*Confidence note: the passive table comes from a binary disassembly (strong). The IV table
in §4 comes from roughly 150 empirical samples (weaker).*

### The success event is a superset, not an exact match

For a wanted set `D` of size `k` drawn from a combined pool of size `m`:

```
P(D ⊆ inherited) = Σ_{N=1..4}  P(N) · C(m−k, N′−k) / C(m, N′)      N′ = min(N, m)
```

Requiring "exactly `D` and no lottery extras" would be wrong. **An unwanted inherited
passive is not a failure** — it can be overwritten for the same 50k an empty slot costs
to fill, which `planPassives()` already prices via its "a drop costs a buy" invariant.
Since a child has 4 slots either way, an unwanted passive costs nothing extra. The two
models are not a constant factor apart, and they rank pool size differently:

| m | k | `P(D ⊆ inh)` → eggs | exact-match → eggs |
|--:|--:|--:|--:|
| 1 | 1 | 1.000 → **1.0** | 0.400 → 2.5 |
| 2 | 1 | 0.800 → 1.2 | 0.080 → 12.5 |
| 4 | 1 | 0.500 → 2.0 | 0.040 → 25.0 |
| 8 | 1 | 0.250 → 4.0 | 0.020 → 50.0 |
| 2 | 2 | 0.600 → **1.7** | 0.240 → 4.2 |
| 4 | 2 | 0.250 → 4.0 | 0.020 → 50.0 |
| 6 | 3 | 0.030 → 33.3 | 0.004 → 250.0 |

Under the exact-match reading almost everything lands in the 25–250 egg range, where the
ranking stops discriminating between plans.

### Consequence: junk passives on a parent are expensive

`m` is the **full** deduped passive pool, not just the interesting passives. At `k=1`,
`m=2` costs 1.2 eggs and `m=8` costs 4.0. The roster this was built against has 1,176
Pals with exactly one passive and 294 with four, so which *individual* you breed routinely
matters more than which species. This is why the search carries a representative
individual per group (§5) and re-resolves the concrete pair at the end.

---

## 4. IV inheritance

Exactly `N` of the three IVs are copied from a parent, the rest re-rolled:
`P(1) = .50, P(2) = .25, P(3) = .25`. At least one is always inherited. An inherited stat
copies one parent at random.

The app projects the **expected** value per stat:

```
E[IV] = (1.75/3) · (ivA + ivB)/2  +  (1 − 1.75/3) · 50        ≈ 0.5833·avg + 0.4167·50
```

This is the default because it is **the only projection consistent with the egg count
printed beside it** — showing 100/100/100 next to "4 eggs" describes two different eggs.
It is also honest about the direction that matters: two 100-IV parents average **79**, so
a bred Pal usually *loses* IVs against one already maxed, and that is exactly what should
stop the tool recommending you throw good Pals away.

An opt-in **Assume perfect IVs** chip switches the projection to 100/100/100 and reframes
the column as a ceiling. That is legitimate — once the passive-locked pair exists, every
egg is the right species with the right passives, and IVs become a separate cheap re-roll
— it is just a different number of eggs, which is why the two are not mixed by default.

Rejected: `max(parents)` (no mechanic produces it) and IV = 0 (makes every plan look bad
and defeats the comparison).

---

## 5. How the search works

**The thesis.** Inheriting a passive is worth something whenever getting it another way
would cost you — and `add_pal: true` does **not** mean free. It means the passive *can* be
applied with an item: rank 1–3 for `PASSIVE_GOLD` (50k) a slot, rank 4 for a one-time
consumable. So a passive is worth breeding for in one of two currencies:

| | what inheriting it buys you | where it shows up |
|---|---|---|
| `add_pal: false`, or its tier's chip is **off** | the child cannot get it at all | **score** |
| buyable and the chip is **on** | the planner would have bought it | **cost** |

A bred Pal's ceiling is therefore **(chased passives inherited from its parents) +
(whatever the enabled tiers let it buy)**, ranked on both axes.

> This was originally written the other way round — breeding chased only `add_pal: false`
> passives, on the theory that `planPassives()` already covered everything buyable. That
> made **Demon God** (+30% Atk / +5% Def, ×1.365, the third-best combat passive in the
> game) permanently invisible: `buildArchetypes()` stripped it off every parent before the
> first pair was scored, so no roster, however stacked, could produce a suggestion
> carrying it. Two other rank-4-or-better buyables were hidden the same way.

A secondary role: the roster covers 257 of 301 species, so some species are reachable only
by breeding. Those appear as `D = ∅`, 1-egg "acquire" rows.

**`CHASE_POOL` and `CHASE_BAR`.** The pool is every `add_pal: false` combat passive (24,
unconditionally) plus every buyable one clearing `CHASE_BAR = 1.20` on its standalone
multiplier — 30 names in total. The bar is a **tuning knob, not game data**: the pool
drives the archetype count and the pair loop is quadratic in it. The passive list has a
natural cliff at 1.20; below it sit the +10% craft passives and the outright negatives,
which never justify extra eggs. Measured on the real 2,330-Pal roster:

| chase pool | carrier archetypes | `evalPair` calls |
|---|---|---|
| 24 — unbuyables only (the old behaviour) | 137 | ~70k |
| **30 — `CHASE_BAR` 1.20 (current)** | **346** | **~203k** |
| 52 — every combat-relevant passive | 933 | ~777k |
| 115 — the full passive set | 1,983 | ~2.2M |

The pool is deliberately **tier-independent**. Gating it on the assumption chips looks
tempting and is wrong: it makes a passive un-chaseable in exactly the case where the only
thing inheriting it saves you is money.

**Archetypes.** The roster is grouped by `(species, gender, chased set)` — 758 groups for
2,330 Pals, of which 346 carry something chased. Each group keeps the actual entry ids and
a **representative**: the individual with the fewest total passives (tie-break highest IV
sum). Grouping on the *full* passive set instead would take the group count to 2,107.

**Two phases.** Phase 1 ranks archetype pairs. Phase 2 takes the survivors and re-scans
the actual individuals to pick the concrete pair minimising `m`, subject to two distinct
entry ids and opposite genders. Everything the UI names — nicknames, owners, the ♂/♀
badges — comes from phase 2.

**Objective.** For each pair, the usable chased passives are those worth something *on the
child's elements* (a `Lord of the Sea` on a Fire child is worth zero — `elementBonus()`
already knows this), and every subset of size ≤4 is evaluated. This yields a small Pareto
frontier per pair rather than one plan, because **the 4th inherited passive is often
negative** (it displaces a better buyable one) and each extra one multiplies the egg cost.

One subset filter is worth calling out: a plan may chase **at most one passive the child
could simply buy** under the enabled tiers. The saving from such a passive is a fixed
price and therefore *additive*, while the egg cost is *multiplicative* — `inheritProb`
falls off a cliff with each extra wanted passive. One is a real trade ("hatch it carrying
Demon God, save the token"); two never is. This also pays for itself in time: on the real
roster with both chips on it is ~4.6 s → ~3.4 s, and without it the top rows are 700-egg
plans chasing three passives the child could have bought outright.

**Ranking.** Score, then **eggs**, then **cost**. Eggs lead because they are what the
panel is *for*: when a passive is buyable under the current tiers, inheriting it and
buying it produce the identical passive set and an exactly equal score, and paying 50k to
skip 600 hatches is the right default.

The per-species cap of 3 is applied by **dominance, not rank**: a row earns a slot only if
it is cheaper in eggs *or* in gold than every row already kept for that species. Taking
the top 3 outright would spend all three on near-identical plans and hide the real
tradeoff — which is exactly where an inherited-instead-of-bought passive lives, since it
ties on score and loses on eggs, so it can only ever surface on the cost axis.

**Depth 2** is opt-in. It collapses the depth-1 output into virtual intermediates, keeps
the best 150, pairs them only against archetypes carrying a chased passive the intermediate
lacks, applies the gender multiplier and a 100-egg budget, and — importantly — **drops any
two-step plan a one-step plan already dominates** on both score and eggs. Without that
last filter the panel fills with "breed X, then breed X again" loops that are strictly
worse than breeding X once.

**Owner scoping.** The owner chips scope breeding exactly as they scope the party of 5:
only the selected owners' Pals are usable as parents. They are part of `breedKey()`, so
changing them marks a completed search stale rather than leaving results on screen that
were built from a different set of Pals.

**Performance.** Depth 1 on the 2,330-Pal roster, by assumption chips:

| chips | time | note |
|---|---|---|
| neither | ~1.6 s | no `planPassives()` calls at all |
| craft only | ~3.3 s | |
| craft + premium | ~3.4 s | widest planner walk; ~47k calls, ~16.5k cache misses |

Up from ~1.4 s before the chase pool widened from 24 names to 30. The extra time is real
work — more archetypes (577 → 758) and more distinct `inherited` sets to plan for — and it
buys the ~17–144 Demon God rows per config that were previously unreachable. The search
runs **only** from the button, never from `render()`, which already re-decorates the whole
roster on every keystroke. `tools/js_check.js` asserts this and enforces timing budgets
against a deliberately harsher synthetic roster (uniform passive draw, so the common
buyables are ~4× over-represented and the chips-on case runs ~18 s there).

**Do not try to speed up `planPassives()` by pruning "dominated" buyables.** Ferocious
(+20 Atk) looks redundant beside Musclehead (+30 Atk), and dropping it takes the subset
walk from ~6,000 nodes to a few dozen — a 4× overall speedup. It is also **wrong**:
bonuses are additive across the four slots, so the weaker passive is still worth a slot
*alongside* the stronger one. The best craft set for a Water Pal is Musclehead + Ferocious
+ Burly Body + Heavyweight at ×2.100; pruning Ferocious silently returns ×2.002. This was
tried, and it broke 2,931 of 4,770 real cases. `tools/js_check.js` now brute-forces the
planner against an unpruned search so the same mistake fails loudly.

**Where it lives in the UI.** Breeding is a separate *view*, not a section appended to the
page. The ranked table runs to thousands of rows, so anything below it is unreachable in
practice; a sticky switcher at the top of `<main>` toggles `#viewRoster` / `#viewBreed`
(persisted as `state.view`). The shared controls — target level, assumption chips, owner
filter — are **mirrored into both views** and write the same state, so neither view is a
dead end and there is no second source of truth. If you add another shared control,
render it into both containers the way `renderAssumeChips()` and `renderOwnerChips()` do.

---

## 6. Known limitations

- **The representative is a heuristic.** Fewest-passives is not provably the pair that
  minimises `m`, since a larger parent set could overlap more. Phase 2 re-picks the real
  individuals, which limits the damage to *ranking*, not to the numbers displayed.
- **Depth-2 intermediates are modelled optimistically.** An intermediate is assumed to
  carry its inherited set plus the partner's passives, ignoring lottery junk it may pick
  up along the way. Real two-step chains will run somewhat longer than quoted.
- **Work-speed passives are invisible**, the same blind spot `planPassives()` has: a
  combat score cannot see Artisan, so the planner will happily evict it. Do not run the
  panel's advice on your base workers.
- **Eggs are not hours.** Cake cost, ranch throughput, incubation time and how many farms
  you have are not modelled. The number is "how many eggs before it lands", which is the
  part that depends on the mechanics rather than on your base layout.
- **There is no eggs↔gold exchange rate, on purpose.** Inheriting a buyable passive trades
  extra hatches for a saved purchase, and which side wins depends on an economy the app
  does not model. So cost is a *sortable column and a tiebreak*, never a term folded into
  the score. Folding them into one number would bury the assumption inside a ranking
  instead of showing it. `PREMIUM_GOLD_EQUIV` (a token priced at 500k gold) is a
  player-reported guess and exists only so mixed gold/token plans stay sortable — if
  tokens are your real bottleneck, edit it.
- **Buyables below `CHASE_BAR` are not chased.** A +10% craft passive is inheritable in
  the game but the search will never breed for one, because the pool it would add to the
  archetype key costs more than the advice is worth (§5). They are still bought and shown
  in the planned set; they just never appear as a *bred* pill.
- **A bred Pal starts at 0★ / 0 souls / T0**, so the full condensing and soul bill is
  still ahead of it. The projected score assumes the assumption chips, exactly as the main
  table does.
- **The IV model is the weakest link** (§4) — empirical, not disassembled.

---

## 7. Sources and attribution

- **Primary:** the game's own `DT_PalMonsterParameter` (`CombiRank`,
  `CombiDuplicatePriority`, `IgnoreCombi`, `MaleProbability`, `ZukanIndexSuffix`) and
  `DT_PalCombiUnique`, extracted by `tools/gamedata/PalDataExport`. See
  `docs/GAMEDATA_EXTRACTION.md`.
- **Inheritance probabilities:** /u/mgxts's disassembly,
  <https://www.reddit.com/r/Palworld/comments/1af9in7/passive_skill_inheritance_mechanics_in_breeding/>
- **Cross-check and prior art:** [`tylercamp/palcalc`](https://github.com/tylercamp/palcalc)
  (`PalBreedingCalculator.cs`, `GameConstants.cs`, and the `breeding.json` table used as a
  regression fixture). Its solver README is also the reference for the effort-estimation
  approach this feature adapts.
