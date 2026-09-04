# Breeding Reachability — Reference

Ground truth for `tools/breed_reach.py`. Added 2026-07-28.

This is a **separate experiment** from the breeding path suggester in the app
(`docs/BREEDING.md`). That one asks *"which passives are worth chasing, and from which of
my Pals?"* This one deletes that question and asks *"given that a couple of Pals already
carry the passives I want, what can I make, and what does each thing cost?"*

Nothing here is wired into `pal_analyzer_template.html` or the build pipeline. It is a
standalone, stdlib-only, offline script that reads `data/` + `out/pals-all.json` and
writes a Markdown report.

---

## 1. The premise

The player acquired **Cawgnito** and **Sibelyx** carrying **Lucky + Demon God + Diamond
Body** — three of the best combat passives. Once a payload like that exists on two Pals,
it propagates by breeding, and passive *selection* stops being the interesting problem.
What's left is pathfinding.

Two kinds of parent, and **conflating them is the central trap** (see §3):

- **Carriers** — the seeds, plus anything bred from a step that had a carrier parent.
  These hold the payload.
- **Clean partners** — Pals the player owns with **zero** passives. They can't dilute an
  inherited set, so they're safe partners, but they carry nothing themselves. Parents are
  not consumed by breeding in Palworld, so one clean Pal of a species is an **unlimited**
  supply of partners: the pool is a *set of species*, not a budget of individuals.

The clean pool is read from the save export and optionally filtered by owner. The default
is every owner in the roster; the figures below come from a two-player subset
(`--owners PlayerA,PlayerB`), which yields **22 species** (25 zero-passive entries out of 503).
That tiny pool is what makes the problem non-trivial — see §6.

> The save export **predates** the seed acquisition. Neither Cawgnito nor Sibelyx in
> `out/pals-all.json` actually carries the three passives (the best is a Sibelyx with
> Lucky). The seeds are **asserted**, not looked up. If the save is re-ingested and the
> real carriers appear, nothing in the tool needs to change — but don't "fix" the seed
> list by grepping the roster.

## 2. Cost is unique breeding pairs, not depth

**Cost = the number of distinct species you must breed** in a target's derivation DAG.
Each one is a pen you actually have to set up; a species used twice is bred once and
reused. Cost is computed **per target in isolation** — "what does this specific Pal cost
me" — not against a shared pool of things you might build anyway.

Generational depth is a bad proxy and is demoted to a context column. Measured:

| target | depth | pairs |
| --- | ---: | ---: |
| Eidrolon Ignis | 8 | 17 |
| Ophydia | 8 | 14 |
| Moldron | 5 | 8 |
| Reptyro Cryst | 5 | 7 |
| Relaxaurus | 4 | 4 |

Depth does not even order these correctly. This was a user correction to an earlier
design that ranked by depth; rank by pairs, report depth alongside.

## 3. Two modeling traps, both load-bearing

**(a) Every step needs at least one carrier parent.** The first implementation treated
seeds and clean partners as one undifferentiated "free" set, and cheerfully emitted plans
like `Blazehowl* × Majex* → Bulldosu` — two passive-free parents producing a child that
inherits nothing. Enforcing the constraint raised real costs substantially (Eidrolon
Ignis 14 → 17 pairs). It is enforced structurally in `search()`: the `a` parent ranges
only over carriers while `b` ranges over everything, and `replay()` re-asserts it.

**(b) A plan must record *which instance* of a species each parent is.** A plan can
legitimately use the owned clean Ribbuny as a partner while *also* breeding a carrying
Ribbuny elsewhere. With parents stored as bare names that reads as a dependency cycle
(`build_order` raised `plan is cyclic: ['Broncherry Aqua', 'Cinnamoth', 'Fuack',
'Ribbuny']`). Plan values are therefore `((a, a_bred), (b, b_bred))`, and only `_bred`
parents are dependencies for cycle detection and topological ordering.

**Do not "simplify" (b) by forbidding pool species as intermediates.** It is tempting —
using the free clean one is always at least as cheap — but it breaks the case where a
child needs two parents that are *both* only in the clean pool. There, one of them must
be bred into a carrier first, because the step needs a carrier.

**(c) Plans are dicts, not sets of species.** Two sub-plans can each contain species X
derived a *different* way; their set-union counts X once while no single build order
actually produces it. Keeping the parent choices in the structure makes `cost ==
len(plan)` true by construction.

Also: `breeding_check.child_species` matches a gender-pinned unique combo only when the
caller supplies the pinned gender, so passing `""` silently drops the one pinned recipe
(Katress × Wixen). Gender is ignored in this experiment, so `gender_blind_combos()`
rebuilds the combo index with pins stripped. **`breeding_check.py` is a locked mirror —
never change its semantics**; rewrite the index it consumes instead.

## 4. The search, and how far to trust it

`search()` is a Bellman-Ford-style fixed-point relaxation over **plans**, keeping the
`--keep` (default 3) cheapest distinct plans per species rather than only the cheapest —
a slightly larger plan for one parent can overlap far more with its co-parent and win
overall. It converges in ~10 rounds, **~3.5s** for the full 255-species run.

**It is a heuristic upper bound.** Minimising a union of derivations is Steiner-tree
flavoured. Two guards:

- `--verify` replays every emitted plan against the real breeding rule (each step's
  child, parents-before-use, no species bred twice, and the carrier constraint), and
  brute-forces the relaxation against exhaustive search on a small synthetic table. Both
  pass at 0 errors as of 2026-07-28.
- For a **specific small target**, prove optimality exactly with the recipe in §5.3.
  Reuse it before calling any individual answer "optimal" — the relaxation and the exact
  search can disagree in principle even when they agree in practice.

## 5. Recipes

### 5.1 The full report

```bash
python tools/breed_reach.py                   # -> out/breed_reach.md, ~4s
python tools/breed_reach.py --verify          # + replay and brute-force self-tests
python tools/breed_reach.py --partner-value   # + the acquisition sweep, a few minutes
```

Useful flags: `--seed` (repeatable), `--owners`, `--level`, `--top`, `--plans`, `--keep`,
`--partner-candidates {roster,all}`.

### 5.2 "What's the path to X?" — the common follow-up

```python
import sys; sys.path.insert(0, '.')
import tools.breed_reach as R, breeding_check as BC

pals, uniq = BC.load_tables()
combos, _, ranks = R.gender_blind_combos(pals, uniq)
br = R.Breeder(pals, combos, ranks)
pool  = {s for s in R.clean_pool('out/pals-all.json', ['PlayerA', 'PlayerB']) if s in pals}
seeds = {'Cawgnito', 'Sibelyx'}
plans = R.search(br, seeds, pool, keep=3)

for parents, child in R.build_order(plans['Loomen'][0]):
    (a, a_bred), (b, b_bred) = parents
    mark = lambda n, bred: n if (bred or n in seeds) else n + '*'
    print(mark(a, a_bred), 'x', mark(b, b_bred), '->', child)
```

`*` marks an owned clean partner; everything else carries the payload.

### 5.3 Proving a small target's cost is actually minimal

Enumerate every distinct reachable **carrier-set** by plan size, then check one more step
from each. If the target never appears at sizes 1..k, its minimum is > k.

```python
states = {frozenset()}
for size in range(1, 4):                    # 37 -> 1,060 -> 25,987 distinct states, ~2s
    nxt = set()
    for S in states:
        carriers = seeds | S
        for a in carriers:
            for b in sorted(carriers | pool):
                c = br.child(a, b)
                if c in seeds or c in S:
                    continue
                nxt.add(S | {c})            # check `c == target` here for a size-`size` hit
    states = nxt
```

Size 4 is ~2.5M states and impractical to store — instead take one step from every
size-3 state and test the child, which settles "is 4 pairs enough?" without materialising
the level. Verified results: **Robinquill = 2 pairs** (13 distinct routes; none at 1) and
**Loomen = 5 pairs** (absent at 1, 2, 3 and 4). Beyond ~5 pairs this method stops being
feasible and the relaxation's answer is the best available.

### 5.4 Answering "which one Pal should I go get?"

`--partner-value` re-runs the whole search once per candidate partner species and reports
the drop in total pairs across the top-N targets. **Default candidates are species someone
in the save already owns passive-free** (`--partner-candidates roster`, ~81 of them), so
every row is a trade a guildmate can actually make. `all` includes breeding-only species
and returns useless advice like "obtain a clean Eidrolon Ignis" — it is an upper bound,
not a recommendation.

## 6. What the current data says

Seeds Cawgnito + Sibelyx, clean pool from a two-player subset (22 species), level 80:

- **255 of 301 species reachable.** The pool size barely affects *reachability* — it
  affects *cost*. With every species allowed as a partner, top targets collapse to 2–3
  generations.
- **The ceiling is hard.** Astralym, Panthalus, Frostallion (+Noct), Paladius, Necromus,
  Shaolong, Bastigor, Shadowbeak, Jetragon and 8 others outscore everything reachable but
  are `ignore_combi` — never a breeding child, at any cost. Astralym and Panthalus (and
  Boltmane and Dragostrophe) are stricter still: they fit in no breeding pen, so they are
  not even usable as a *parent*, and `clean_pool()` drops them. See `docs/BREEDING.md` §1.
- **The Pareto frontier argues against chasing the top.** Warsect at 2 pairs scores 1884;
  Eidrolon Ignis at 17 pairs scores 2009. 6% more score for 8.5× the work.
- **Best single acquisition:** a clean **Cryolinx** saves 73 pairs across the top 15
  targets (up to 8 on one). Then Bellanoir 52, Menasting Terra 44, Moldron 37.

Scores assume the payload (Atk +45%, Def +50%, HP +0%) at level 80, IV 0, no
condense/souls/trust. **None of the three passives carries an element boost**, so every
reachable Pal gets an identical multiplier and the score column is a pure species base-stat
ranking — it ranks species, nothing more.

## 7. Known limitations

- **Inheritance probability is out of the model entirely.** One pair = one *successful*
  egg. A 3-passive inheritance is a low-probability roll, so a 17-pair plan is far more
  than 17 eggs of real work, and cheap plans are undersold relative to expensive ones by
  a factor this tool does not compute. `breeding_check.p_inherit` exists if this is ever
  wanted.
- **Gender is ignored**, including `male_probability` and the one gender-pinned unique
  combo. Real pens need a male and a female; a plan can name a species whose only clean
  owned entry is the wrong gender for the pairing.
- **Species granularity, not entry granularity.** Unlike the shipped suggester, which
  resolves real save entry ids, this never checks that a specific Pal exists and is
  available. `docs/BREEDING.md` §5 is emphatic that availability is a matching problem;
  that lesson is deliberately not applied here.
- **Optimality is heuristic above ~5 pairs** (§4).
- Hatchlings arrive at level 1; the levelling cost of a 17-step chain is not modelled.
- Work-speed value is not considered at all — this is a combat-only ranking.
- `out/` holds real players' rosters. `out/breed_reach.md` contains species names only,
  but it lives under the same rule: **never publish it as a Claude Artifact.**
