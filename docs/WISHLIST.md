# Wishlist — Reference

Ground truth for the wishlist view in `pal_analyzer_template.html`. Added 2026-08-29.

The app now answers three different breeding questions and it is worth being precise
about which is which:

| | question | ranked by |
|---|---|---|
| `docs/BREEDING.md` | *what should I make?* — forward, unconstrained | combat score |
| `docs/BREED_REACH.md` | *given a payload, what's reachable?* — offline script | unique pairs |
| **this** | *I want **this** Pal with **these** passives — how?* | **total expected eggs** |

Inverting the question is what makes it affordable. With at most four named passives,
everything that matters about an intermediate Pal is `(species, which of the wanted
passives it carries, how much junk rides along)` — about 24,000 states rather than every
passive combination in the game.

---

## 1. A wish is a spec

A wish is a species plus **1–4** passives. Every passive named must be **bred**, with
exactly one liberty: a rank 1–3 `add_pal` passive is **bought** for `PASSIVE_GOLD` (50k)
rather than bred, because 50k is noise against even one extra hatch.

There is deliberately **no premium option**, no per-passive toggle and no side-by-side
comparison. Rank-4 passives (Demon God, Diamond Body) cost a scarce one-time consumable,
not gold — and if you would spend a token on one, you simply leave it out of the wish.
The `premium` assumption chip does not reach this view at all.

This split matters more than it looks, because the top craft passives are all cheap:

| wish | bred | bought | best-case final pool | last-step eggs |
|---|---|---|---|---|
| Legend + Demon God + Musclehead + Ferocious | 2 | 2 | `m=2` | 1.7 |
| Legend + Demon God + Lucky + Musclehead | 3 | 1 | `m=3` | 5.0 |
| Legend + Lucky + Idiosyncratic + Immortality | 4 | 0 | `m=4` | 10.0 |

Musclehead (×1.300), Burly Body, Ferocious and Heavyweight (×1.200) are all 50k buys, so
a four-passive wish usually collapses to breeding two things. Only Legend, Lucky,
Idiosyncratic, Lunker and Immortality (`add_pal:false`) plus the two rank-4 buyables are
genuinely un-buyable.

A cheap wished passive is dropped from the bred set but **still counts toward `m`** if a
parent carries it — it dilutes the pool like anything else. If it lands for free you save
50k the plan does not claim.

---

## 2. Junk is a price, not a wall

**This is the load-bearing correction, and getting it backwards costs 5×.**

A child draws `N` passives uniformly from the parents' *combined deduplicated* pool, so a
parent's junk is never handed to the child — it only enlarges the pool the wanted ones
must be drawn out of. `P(D ⊆ inherited)` falls as `m` grows but never reaches zero.
**A dirty parent is an expensive parent, not an unusable one.**

The same holds one level up, which is the part that is easy to get wrong: when breeding an
intermediate you do **not** have to discard every egg that comes out with extra passives.
Accepting a dirtier intermediate is *cheaper now and more expensive later*, and which side
wins is arithmetic. For `D = {Legend, Demon God}` where the only Legend carrier is
`Legend + 2 junk`:

| route | m | P | eggs |
|---|---|---|---|
| **use it dirty** — dirty Legend × clean Demon God → target | 4 | 0.250 | **4.0** |
| clean it first — hold out for an exact `{Legend}` hatch | 3 | 0.053 | 18.8 |
| …then clean Legend × clean Demon God → target | 2 | 0.600 | 1.7 |
| | | | **20.5** |

Cleaning costs 5× here. An implementation that requires junk-free intermediates returns
the 20-egg answer for a 4-egg job — and it gets worse, because the exact-match filter must
also reject every lottery roll, a flat ×2.5 charged on every intermediate for nothing.

It **flips** at `|D| = 4`, where the final pool must be exactly 4: one junk passive on
either parent takes the last step from 10 eggs to 50, two takes it to 150. There, cleaning
is worth 19 eggs. Both regimes have to be reachable, so junk is a **Pareto axis on the
cost, never a filter**: a node is `(species, wanted mask, junk count)` and at every step
the solver chooses how picky to be, keeping whichever choice minimises the *total*.

`tools/js_check.js` pins the 4-egg answer so this cannot silently regress.

### `acceptProb(m, k, maxExtras)`

P(a hatch carries all `k` wanted passives and at most `maxExtras` others). It generalises
`inheritProb()`, which is exactly the `maxExtras < 0` (unlimited) case, and is mirrored by
`p_accept()` in `breeding_check.py` with a 17-row fixture the JS is checked against.

```
Σ over direct draws N=1..4, d = min(N, m), d ≥ k:
    P(N) · C(m−k, d−k)/C(m, d) · P(extras acceptable)
```

Unlike `inheritProb()` the **lottery matters**. A direct draw of `d` leaves `4−d` free
slots and the lottery fills up to 3 of them, so total extras are
`(d − k) + min(L, 4 − d)`. Being picky therefore means re-rolling lottery hits too. Two
consequences fall out and both are load-bearing:

- `acceptProb(m, 0, 0) = 0` for every `m > 0` — a child always draws at least one passive
  from a non-empty pool, so **a passive-free Pal can only come from two passive-free
  parents.** That is what makes the clean-partner pre-pass a plain shortest path.
- `acceptProb(0, 0, 0) = 0.40` — breeding a clean partner from two clean parents costs
  2.5 eggs, purely the odds of rolling no lottery passive.

Eggs at a step always means *expected hatches until one acceptable egg appears*, so eggs
you throw back are counted.

### Junk on the target is free

You cannot delete a passive, only overwrite one, and an overwrite costs the same 50k as
filling an empty slot. So junk on the **final** hatch costs nothing: it gets overwritten
by a 50k passive you were buying anyway, and the wish has exactly enough room by
construction (4 slots, `|bred| + |bought| ≤ 4`). The search takes the cheapest — most
permissive — acceptance for the target and the honest Pareto choice everywhere above it.

---

## 3. Cost

**Total expected eggs, and nothing else.** Gold is printed so you know to spend it; it
never enters the ranking. Breeding pairs and generational depth are neither budgeted nor
ranked.

A plan is a **map from node to the step that produces it**, never a list or a set of
species. Two sub-plans can each contain the same node reached a different way, and a set
union counts it once while no single build order produces it — keying by node makes
`eggs == Σ over the map` true by construction. Parents survive breeding, so a shared
intermediate is bred once and **paid for once**. `docs/BREED_REACH.md` §3 hit the identical
trap one dimension lower; here two nodes can share a species with different passive sets,
so bare species names are even less usable as keys.

### Gender

Deliberately **not** a dimension of the node. Two bred intermediates are both unhatched, so
neither has a gender targeted in advance — you take whichever comes and pair them.

- **bred × bred** — no factor.
- **bred × owned** — the bred side costs `× 1/P(gender)`, but only when the owned side is
  *gender-locked*: if the roster holds both a male and a female of that node, nothing is
  pinned and the factor drops away. Unknown gender charges nothing and is badged `⚠`.
- **owned × owned** — no eggs, only the distinct-ids/opposite-genders check.

Where a shared node is consumed by two steps with different demands the stricter one wins;
steps are shared objects between plans, so a demand clones rather than mutates.

**The clean-partner pre-pass obeys the same rules**, which is easy to forget because it
runs before the search proper. It did not, originally, and fuzzing 120 random wishes
against the real roster caught it: 6 of 106 plans contained a filler step pairing two Pals
that could never breed, and phase 2 then had no Pal to name for that parent, so the plan
came out with a hole in it. `tools/js_check.js` now pins an all-male clean pool.

---

## 4. The search

**Nodes.** `(speciesIndex × 16 + wantedMask) × 5 + junk`, a plain integer. Node ids are
integers rather than strings because string keys and their allocations were the single
largest cost when this was profiled — the inner loop runs tens of millions of iterations.
`ACCEPT` is a 325-cell lookup table (`m ≤ 12`, `k ≤ 4`, junk `≤ 4`) and the child of every
species pair is cached in an `Int32Array`.

**Clean partners** are computed once per roster and reused by every wish, since they do not
depend on the wish: both parents must be clean (§2), so it is a shortest path over species
with a flat 2.5-egg edge. Allowing bred partners at all is deliberate — restricting
partners to Pals you own breaks the real case where a child needs two parents that are both
only available clean, so one of them has to be bred first.

**Iterative broadening.** Each pass is a fixed-point relaxation under a beam, and passes
widen fourfold until one finishes untruncated or the 10-second budget expires. The narrow
first pass is the point: it produces *some* complete route in a fraction of a second, and
every later pass inherits it as a **cost bound**. That bound is worth more than the wider
beam costs, because every step costs at least one egg and a plan contains its parents'
plans whole — so a node already dearer than the best complete route can never sit inside a
cheaper one.

**The beam is bucketed by how many wanted passives a node carries**, not taken straight off
the cheapest. Sorting on eggs alone fills it with cheap single-passive carriers and starves
the 3- and 4-passive nodes that are the only ones near the goal — which is exactly where
the expensive wishes live. Measured on the real 2,330-Pal roster, bucketing plus the bound
took `Anubis [Legend, Lucky, Idiosyncratic, Diamond Body]` from 177 eggs over 11 steps to
103 over 6.

**Partners are Pareto-pruned per species** each round: a partner with the same wanted
passives, no more junk and no more eggs makes every other redundant. On a mature roster
this is most of the pair space, since dozens of dirty no-passive variants per species
collapse to one.

**Two cycle guards.** A step is skipped if either parent's plan already contains the child
node (that would make the child its own ancestor), and re-breeding a parent into exactly
what it already is (`same species, same mask, no less junk`) is skipped as pure waste.

**Anytime, and it says so.** `converged` means a pass finished without ever hitting its own
beam and is optimal within the model; `budget` means the 10 seconds ran out and this is
merely the best found. The UI shows which.

**Phase 2** resolves every unbred parent to a concrete individual — distinct ids, opposite
genders where known. One individual may serve several steps, because parents survive
breeding, but never both sides of one step.

### Measured, real 2,330-Pal roster

| wish | eggs | steps | result |
|---|---|---|---|
| Anubis + Legend, Demon God, Musclehead, Ferocious | 11.9 | 4 | converged, 8s |
| Lamball + Legend | 12.9 | 6 | converged, 1.4s |
| Anubis + Legend, Lucky, Demon God, Idiosyncratic | 100.8 | 4 | budget |
| Anubis + Legend, Lucky, Idiosyncratic, Diamond Body | 102.9 | 6 | budget |

---

## 5. When there is no answer, say why

Four checks, all before the search where possible, because a named cause is the whole
value of a negative answer:

1. **A wanted passive nobody reachable carries**, and it cannot be bought. Definitive, and
   the message names the passive.
2. **A species that fits in no breeding pen** — Astralym, Boltmane, Dragostrophe,
   Panthalus. Not even rule 1 is open to these, so the answer is "catch one"; saying
   *"never the child of two different species"* here would be true but would imply that
   two of them in a pen is a route, and it is not. See `docs/BREEDING.md` §1. The same
   fact keeps them out of every parent pool, so they cannot turn up as somebody else's
   filler either.
3. **A self-only species.** 39 of the 41 `ignore_combi` Pals do have a unique combo
   (`Blue Slime × Enchanted Sword → Enchanted Sword`), but 28 species — all `ignore_combi`,
   Frostallion, Jetragon and Blazamut Ryu among them — are never the child of two
   *different* species, so rule 1 is the only way in and the passives must already be on
   that species. Checked up front against a cached cross-reachability sweep, which turns a
   10-second dead end into an instant explanation.
4. **No route inside the budget.** Says so, rather than implying impossibility.

A wish you already satisfy returns **0 eggs and names the Pal** — checked before
everything else, since it is also the only way a self-only species can succeed.

---

## 6. Known limitations

- **bred × bred pairings undercount by roughly one hatch.** No gender is targeted, but the
  second intermediate still has to land opposite the first. Deliberate: targeting a gender
  that is not actually pinned would be a worse error in the other direction.
- **Junk on two different parents is treated as disjoint**, the maximum-dilution reading.
  Real overlap makes some plans slightly cheaper than quoted. Exact at the leaves, where
  the passive names are known.
- **One plan is kept per node.** `breed_reach.py` keeps three, on the grounds that a
  slightly larger plan can overlap far more with its co-parent; the sharing-aware merge
  here removes most of that pathology, but not all of it.
- **A bred filler partner may be cheaper to catch in the wild**, and no catchability data
  exists in the game export (`BREED_REACH.md` §5.4 hit the same wall), so those steps are
  an upper bound and are badged as such.
- **Eggs are not hours.** Cake, ranch throughput and incubation time are out of the model,
  the same boundary `docs/BREEDING.md` §6 draws.
- **IVs are not modelled at all**, unlike the breeding panel. A wish is about species and
  passives; the IV re-roll is a separate, cheaper problem.
- **Optimality is claimed only when the status says `converged`.**
- A bred target hatches at level 1 / 0★ / 0 souls / T0, so the whole condensing and soul
  bill is still ahead of it.

---

## 7. Where it lives

A third view behind the sticky switcher (`state.view === 'wishlist'`, `#viewWishlist`),
for the same reason breeding is: the ranked table runs to thousands of rows and anything
below it is unreachable in practice.

- `state.wishlist = [{id, species, passives:[…]}]`, normalised through `normalizeWish()`.
  **It must be listed in `load()`'s whitelist** or it saves fine and silently never comes
  back. `exportBtn` serialises all of `state`, and import only replaces `state.pals`, so
  wishes survive a roster re-ingest — which is the point, since `out/` is re-imported often.
- The **owner chips scope the parent pool**, exactly as they do for breeding: you can only
  breed with Pals you can physically put in a pen. They are part of the result stamp, so
  changing them marks a result stale rather than leaving a plan built from other people's
  Pals on screen.
- The search **must never run from `render()`** — only from a wish's Solve button.
  `tools/js_check.js` asserts this, as it does for the breeding panel. It runs as a
  generator driven in ~100 ms slices off the event loop, yielding inside a round as well as
  between rounds, because one round on the hard wishes runs well over a second and a frozen
  spinner reads as a hung page.

## 8. Verification

- `python breeding_check.py` — `p_accept` against a 17-row fixture, its agreement with
  `p_inherit` wherever pickiness is unlimited, and monotonicity in both arguments.
- `node tools/js_check.js` — the JS `acceptProb` against that same Python fixture, plus a
  **plan validator** that re-derives every emitted plan against the real breeding rule:
  each step's child is what those parents actually make, the pool size and egg count match
  the odds claimed, parents exist before use, no node is built twice, every named Pal is in
  the roster and of the right species, no Pal breeds with itself or with the same gender,
  and the total is the sum of the steps. It also pins the 4-egg junk case in §2, the
  clean-partner gender rule (§3), the blocked-wish diagnoses, the save/load round trip,
  and that `render()` never searches.
- The validator is the part worth keeping sharp. It is what caught the clean-partner
  gender bug, and it caught it by being run over *many* wishes rather than a chosen few —
  so when changing the solver, point it at a few dozen random wishes on the real roster
  before trusting the fixed cases.
