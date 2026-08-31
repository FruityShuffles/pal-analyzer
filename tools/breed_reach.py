#!/usr/bin/env python3
"""Breeding reachability experiment: what can I make, and how many pairs does it cost?

This is EXPLORATORY and deliberately separate from the shipped breeding suggester in
pal_analyzer_template.html. That one asks "which passives are worth chasing"; this one
takes passive selection out of the model entirely.

Premise: a small set of seed Pals already carry the desired passive payload (Cawgnito
and Sibelyx with Lucky + Demon God + Diamond Body). Breeding a carrier against another
carrier, or against a Pal with NO passives (which cannot contaminate the inherited set),
propagates the payload. So the only open question is pathfinding: which species are
reachable, and what does each one cost?

COST IS UNIQUE BREEDING PAIRS, not generations. Each distinct species you must breed is
one pen you must actually set up; a species used twice in a derivation is bred once and
reused, because parents survive breeding in Palworld. Depth is reported alongside but is
a poor proxy -- measured on real data, one depth-8 target costs 15 pairs while another
depth-5 target costs 5.

Out of scope on purpose: inheritance probability (one pair == one successful egg),
gender and male_probability, gold/token cost, and matching concrete save entries (this
works at species granularity).

Run:
    python tools/breed_reach.py
    python tools/breed_reach.py --verify
    python tools/breed_reach.py --partner-value
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import breeding_check as BC      # noqa: E402  child-species rule, diffed 0-mismatch vs palcalc
import scoring_check as SC       # noqa: E402  the combat-score formula mirror

DEFAULT_SEEDS = ["Cawgnito", "Sibelyx"]
DEFAULT_OWNERS = []              # empty = every owner in the roster; --owners narrows it
# Lucky + Demon God + Diamond Body, summed from data/passives.json. These take DECIMALS,
# not percents. No element boosts among the three, so every reachable Pal gets the same
# multiplier and the ranking reduces to species base stats -- said again in the report.
PAYLOAD_ATK = 0.45
PAYLOAD_DEF = 0.50
PAYLOAD_HP = 0.00


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def gender_blind_combos(pals, unique):
    """Rebuild the unique-combo index with every gender pin stripped.

    breeding_check.child_species only matches a pinned combo when the caller supplies
    the pinned gender, so passing "" silently drops the one gender-pinned recipe
    (Katress x Wixen) through to the rank rule. Gender is ignored in this experiment,
    so pinned combos must always match. breeding_check.py is a locked mirror -- this
    rewrites the index it consumes rather than touching its semantics.
    """
    blind = [dict(c, ga="", gb="") for c in unique]
    return BC.build_index(pals, blind)


def clean_pool(roster_path, owners=None):
    """Species of which some owner has at least one zero-passive Pal.

    Species-level, not entry-level: parents are not consumed by breeding, so one clean
    Pal of a species is an unlimited supply of partners. `owners=None` means anyone.
    """
    with open(roster_path, encoding="utf-8") as f:
        entries = json.load(f)["pals"]
    want = set(owners) if owners else None
    return {e["species"] for e in entries
            if (want is None or e.get("owner") in want) and not e.get("passives")}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
class Breeder:
    """Child lookup with a symmetric cache; the raw rule is the whole runtime cost."""

    def __init__(self, pals, combos, pool):
        self.pals, self.combos, self.pool = pals, combos, pool
        self.cache = {}

    def child(self, a, b):
        key = (a, b) if a <= b else (b, a)
        got = self.cache.get(key)
        if got is None:
            got = BC.child_species(key[0], key[1], self.pals, self.combos, self.pool)
            self.cache[key] = got
        return got


def merge(plan_a, plan_b, child, parents):
    """Union two derivation plans and append one step. None if they cannot be merged.

    A plan is {species: ((a, a_bred), (b, b_bred))} -- a CONSISTENT derivation, not a
    bare set of species. Two things force this shape:

      * Storing sets instead is tempting and wrong: two sub-plans can each contain
        species X derived a different way, and their union counts X once while no single
        build order actually produces it. Keeping parent choices in the structure makes
        cost == len(plan) true by construction.
      * The `_bred` flag distinguishes the owned passive-free Pal of a species from a
        carrying one bred inside this plan. Both can appear in one plan -- using clean
        Ribbuny as a partner while also breeding a carrying Ribbuny elsewhere is legal,
        and without the flag it reads as a dependency cycle.

    A merge is closed (every bred parent is a key) because both inputs were, and cycles
    can only enter through a conflicting key, so only that path pays for the check.
    """
    merged = dict(plan_a)
    conflict = False
    for k, v in plan_b.items():
        if k in merged:
            if merged[k] != v:
                conflict = True
        else:
            merged[k] = v
    merged[child] = parents
    if conflict and not _acyclic(merged):
        return None
    return merged


def _acyclic(plan):
    """Kahn's algorithm. Only `_bred` parents are dependencies; owned ones are ready."""
    remaining = dict(plan)
    ready = set()
    while remaining:
        progressed = False
        for species, parents in list(remaining.items()):
            if all(not bred or name in ready for name, bred in parents):
                ready.add(species)
                del remaining[species]
                progressed = True
        if not progressed:
            return False
    return True


def search(breeder, seeds, pool, keep=3, max_rounds=40):
    """Fixed-point relaxation minimising the number of unique breeding pairs.

    Two kinds of free parent, and conflating them is the trap: `seeds` already CARRY the
    passive payload, while `pool` Pals are merely owned and passive-free. A child of two
    pool Pals inherits nothing, so every step must have at least one carrier parent --
    enforced structurally by letting `a` range only over carriers while `b` ranges over
    everything. Note a pool species is still worth breeding: your owned Blazehowl is not
    a carrier, so a carrying Blazehowl costs pairs like anything else.

    Keeps the `keep` cheapest distinct plans per species, not just the single cheapest:
    a slightly larger plan for one parent can overlap far more with its co-parent and
    win overall, and keeping only the minimum hides that.

    This is a heuristic upper bound. Minimising a union of derivations is Steiner-tree
    flavoured; --verify brute-forces it on a small synthetic table to keep the search
    honest, and every emitted plan is replayed against the breeding rule regardless.
    """
    plans = {s: [{}] for s in seeds}         # carrier species -> plans, cheapest first
    dirty = set(seeds)
    for _ in range(max_rounds):
        if not dirty:
            break
        carriers = list(plans)
        parents = sorted(set(carriers) | set(pool))
        touched = set()
        for a in carriers:
            a_dirty = a in dirty
            a_bred = a not in seeds
            for b in parents:
                if not a_dirty and b not in dirty:
                    continue
                c = breeder.child(a, b)
                if c in seeds:
                    continue
                for pa in plans[a]:
                    if c in pa:
                        continue                  # circular: a already needs c
                    for pb, b_bred in _parent_plans(plans, seeds, pool, b):
                        if c in pb:
                            continue
                        cand = merge(pa, pb, c, ((a, a_bred), (b, b_bred)))
                        if cand is not None and _offer(plans, c, cand, keep):
                            touched.add(c)
        dirty = touched
    return plans


def _parent_plans(plans, seeds, pool, species):
    """Ways to have this parent on hand, as (plan, is_bred).

    A pool species can be had both ways -- free and passive-free, or bred and carrying --
    and which one a step used has to be recorded, not inferred.
    """
    opts = []
    if species in pool or species in seeds:
        opts.append(({}, False))
    if species in plans and species not in seeds:
        opts.extend((p, True) for p in plans[species])
    return opts


def _offer(plans, species, cand, keep):
    """Insert cand into the species' plan list if it earns a slot. True if it did."""
    have = plans.get(species)
    if have is None:
        plans[species] = [cand]
        return True
    if len(have) >= keep and len(cand) >= len(have[-1]):
        return False
    key = frozenset(cand)
    if any(frozenset(existing) == key for existing in have):
        return False
    have.append(cand)
    have.sort(key=len)
    del have[keep:]
    return any(frozenset(p) == key for p in have)


def depths(breeder, seeds, pool):
    """Generations of breeding, for reporting only. Seeds are the only depth-0 carriers.

    Same carrier constraint as the main search: only carriers can be the `a` parent.
    """
    depth = {s: 0 for s in seeds}
    while True:
        carriers = list(depth)
        parents = sorted(set(carriers) | set(pool))
        gen = max(depth.values()) + 1
        new = {}
        for a in carriers:
            for b in parents:
                c = breeder.child(a, b)
                if c not in depth and c not in new:
                    new[c] = gen
        if not new:
            return depth
        depth.update(new)


def build_order(plan):
    """Topologically ordered build list: [(parents, child), ...], parents before use."""
    remaining = dict(plan)
    done = set()
    order = []
    while remaining:
        progressed = False
        for species, parents in sorted(remaining.items()):
            if all(not bred or name in done for name, bred in parents):
                order.append((parents, species))
                done.add(species)
                del remaining[species]
                progressed = True
        if not progressed:
            raise AssertionError("plan is cyclic: %s" % sorted(remaining))
    return order


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_of(pals, species, level):
    p = pals[species]
    hp = SC.stat_hp(p["hp_stat"], level, 0, PAYLOAD_HP)
    atk = SC.stat_attack(p["attack_stat"], level, 0, PAYLOAD_ATK)
    dfn = SC.stat_defense(p["defense_stat"], level, 0, PAYLOAD_DEF)
    return SC.combat_score(hp, atk, dfn)


def pareto(rows):
    """Rows not beaten on BOTH cost and score by some other row."""
    out = []
    for r in rows:
        if not any(o is not r and o["pairs"] <= r["pairs"] and o["score"] >= r["score"]
                   and (o["pairs"] < r["pairs"] or o["score"] > r["score"]) for o in rows):
            out.append(r)
    return sorted(out, key=lambda r: r["pairs"])


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def replay(breeder, seeds, pool, species, plan):
    """Assert the plan is a real, self-contained, non-redundant recipe. Returns errors."""
    errors = []
    if species not in plan:
        errors.append("%s: target missing from its own plan" % species)
        return errors
    seen = set()
    for parents, child in build_order(plan):
        (a, a_bred), (b, b_bred) = parents
        for name, bred in parents:
            if bred and name not in seen:
                errors.append("%s: %s used before it is bred" % (species, name))
            if not bred and name not in seeds and name not in pool:
                errors.append("%s: %s is neither owned nor bred" % (species, name))
        # The payload only propagates from a parent that has it. A step between two
        # passive-free Pals produces a passive-free child and is worthless here.
        if not (a_bred or b_bred or a in seeds or b in seeds):
            errors.append("%s: %s x %s has no carrier parent" % (species, a, b))
        got = breeder.child(a, b)
        if got != child:
            errors.append("%s: %s x %s yields %s, plan claims %s" % (species, a, b, got, child))
        if child in seen:
            errors.append("%s: %s bred twice" % (species, child))
        seen.add(child)
    return errors


def brute_force_check():
    """Brute-force the metric on a synthetic table where exhaustion is feasible.

    Guards the one thing the real run cannot self-check: that the relaxation's plan
    sizes are actually minimal, not merely valid.
    """
    import itertools

    names = ["s%d" % i for i in range(8)]
    rules = {}
    for a, b in itertools.combinations_with_replacement(names, 2):
        rules[(a, b)] = names[(names.index(a) * 3 + names.index(b) * 5 + 1) % len(names)]

    class Fake:
        def child(self, a, b):
            return rules[(a, b) if a <= b else (b, a)]

    fake, seeds, pool = Fake(), {"s0"}, {"s1", "s2"}
    plans = search(fake, seeds, pool, keep=8)

    # Exhaustive: grow every closed plan up to a size bound, keep the cheapest per target.
    # Mirrors the carrier constraint -- `a` must already carry the payload.
    best = {}
    frontier = [dict()]
    seen_keys = {frozenset()}
    for _ in range(6):
        nxt = []
        for plan in frontier:
            for a in sorted(set(seeds) | set(plan)):
                for b in sorted(set(seeds) | set(pool) | set(plan)):
                    c = fake.child(a, b)
                    if c in seeds or c in plan:
                        continue
                    grown = dict(plan)
                    grown[c] = (a, b)
                    if c not in best or len(grown) < best[c]:
                        best[c] = len(grown)
                    key = frozenset(grown)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    nxt.append(grown)
        frontier = nxt
        if not frontier:
            break

    errors = []
    for species, size in best.items():
        got = plans.get(species)
        if not got:
            errors.append("brute force reached %s, relaxation did not" % species)
        elif len(got[0]) != size:
            errors.append("%s: relaxation %d pairs, brute force %d" % (species, len(got[0]), size))
    return errors


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def write_report(path, rows, plans, pool, seeds, unreachable_top, partners, args, elapsed):
    order_by_cost = sorted(rows, key=lambda r: (r["pairs"], -r["score"]))
    order_by_score = sorted(rows, key=lambda r: -r["score"])
    front = pareto(rows)

    out = []
    w = out.append
    w("# Breeding reachability\n")
    w("Seeds: **%s** (assumed to carry the full passive payload).  " % ", ".join(seeds))
    w("Clean partner pool: **%d species** owned by %s with no passives.  "
      % (len(pool), ", ".join(args.owners) or "all owners"))
    w("Reached **%d** species in %.1fs. Cost is **unique breeding pairs**; depth is "
      "generations, shown for context only.\n" % (len(rows), elapsed))
    w("> Scores assume Lucky + Demon God + Diamond Body (Atk +45%%, Def +50%%, HP +0%%) "
      "at level %d, IV 0, no condense/souls/trust. None of the three carries an element "
      "boost, so every reachable Pal gets an identical multiplier and this ranking "
      "reduces to species base stats.\n" % args.level)

    w("\n## Pareto frontier\n")
    w("Species no other species beats on both cost and score -- the shortlist.\n")
    w("| species | pairs | depth | score | elements |")
    w("| --- | ---: | ---: | ---: | --- |")
    for r in front:
        w("| %s | %d | %d | %.0f | %s |" % (r["species"], r["pairs"], r["depth"],
                                            r["score"], ", ".join(r["elements"])))

    w("\n## Best combat Pals, by score\n")
    w("| species | pairs | depth | score | elements |")
    w("| --- | ---: | ---: | ---: | --- |")
    for r in order_by_score[:args.top]:
        w("| %s | %d | %d | %.0f | %s |" % (r["species"], r["pairs"], r["depth"],
                                            r["score"], ", ".join(r["elements"])))

    w("\n## Cheapest to reach\n")
    w("| species | pairs | depth | score | elements |")
    w("| --- | ---: | ---: | ---: | --- |")
    for r in order_by_cost[:args.top]:
        w("| %s | %d | %d | %.0f | %s |" % (r["species"], r["pairs"], r["depth"],
                                            r["score"], ", ".join(r["elements"])))

    if unreachable_top:
        w("\n## Out of reach forever\n")
        w("These outscore everything above but are `ignore_combi` -- they are never "
          "produced by breeding, at any cost.\n")
        w("| species | score | elements |")
        w("| --- | ---: | --- |")
        for species, sc, els in unreachable_top:
            w("| %s | %.0f | %s |" % (species, sc, ", ".join(els)))

    if partners:
        w("\n## Worth acquiring\n")
        w("One more clean partner species, measured against the top %d targets. "
          "Candidates are species someone in the save already owns passive-free, so "
          "each row is a trade you can actually make.\n" % args.plans)
        w("| clean partner | pairs saved | targets improved | best single target |")
        w("| --- | ---: | ---: | ---: |")
        for saved, best, improved, cand in partners[:15]:
            w("| %s | %d | %d | %d |" % (cand, saved, improved, best))

    w("\n## Build plans\n")
    w("Ordered: every parent is either owned or bred on an earlier line. "
      "`*` marks a Pal you already own with no passives -- a partner, not a carrier. "
      "Everything unmarked carries the payload.\n")

    def mark(name, bred):
        return name if bred or name in seeds else name + "*"

    for r in order_by_score[:args.plans]:
        plan = plans[r["species"]][0]
        w("\n### %s -- %d pairs, score %.0f\n" % (r["species"], r["pairs"], r["score"]))
        for i, (parents, c) in enumerate(build_order(plan), 1):
            (a, a_bred), (b, b_bred) = parents
            w("%d. %s x %s -> **%s**" % (i, mark(a, a_bred), mark(b, b_bred), c))

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def partner_value(breeder, seeds, pool, targets, base_cost, keep, limit):
    """Cost drop across `targets` if one clean Pal of species X were added to the pool.

    The measured collapse when the partner pool grows makes this the most actionable
    output here: it says which single Pal to go get, rather than which path to walk.
    """
    results = []
    for cand in sorted(limit):
        plans = search(breeder, seeds, pool | {cand}, keep=keep)
        saved, improved, best = 0, 0, 0
        for t in targets:
            got = plans.get(t)
            new = len(got[0]) if got else base_cost[t]
            drop = max(0, base_cost[t] - new)
            saved += drop
            improved += 1 if drop else 0
            best = max(best, drop)
        if saved:
            results.append((saved, best, improved, cand))
    return sorted(results, reverse=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", action="append", dest="seeds", metavar="SPECIES")
    ap.add_argument("--owners", default=",".join(DEFAULT_OWNERS))
    ap.add_argument("--roster", default=os.path.join(ROOT, "out", "pals-all.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "breed_reach.md"))
    ap.add_argument("--level", type=int, default=80)
    ap.add_argument("--top", type=int, default=30, help="rows per table")
    ap.add_argument("--plans", type=int, default=15, help="build plans to print")
    ap.add_argument("--keep", type=int, default=3, help="plans retained per species")
    ap.add_argument("--verify", action="store_true", help="replay + brute-force self-test")
    ap.add_argument("--partner-value", action="store_true",
                    help="sweep: which single extra clean partner would save the most")
    ap.add_argument("--partner-candidates", choices=("roster", "all"), default="roster",
                    help="roster: species SOMEONE in the save owns clean (actionable -- "
                         "a guildmate can hand it over). all: every reachable species.")
    args = ap.parse_args()

    args.seeds = args.seeds or DEFAULT_SEEDS
    args.owners = [o.strip() for o in args.owners.split(",") if o.strip()]

    pals, unique = BC.load_tables()
    combos, _, pool_ranks = gender_blind_combos(pals, unique)
    breeder = Breeder(pals, combos, pool_ranks)

    for s in args.seeds:
        if s not in pals:
            ap.error("unknown seed species: %s" % s)
    pool = {s for s in clean_pool(args.roster, args.owners) if s in pals}
    seeds = set(args.seeds)

    t0 = time.time()
    plans = search(breeder, seeds, pool, keep=args.keep)
    elapsed = time.time() - t0

    reachable = {s for s in plans if s not in seeds}
    depth = depths(breeder, seeds, pool)
    rows = [{"species": s, "pairs": len(plans[s][0]), "depth": depth.get(s, 0),
             "score": score_of(pals, s, args.level), "elements": pals[s]["elements"]}
            for s in reachable]

    best_reachable = max(r["score"] for r in rows) if rows else 0.0
    unreachable_top = sorted(
        ((s, score_of(pals, s, args.level), pals[s]["elements"])
         for s in pals if s not in plans and score_of(pals, s, args.level) > best_reachable),
        key=lambda t: -t[1])

    print("clean pool: %d species from %s" % (len(pool), ", ".join(args.owners) or "all owners"))
    print("reached %d species in %.1fs (%d unreachable outscore the best reachable)"
          % (len(rows), elapsed, len(unreachable_top)))

    if args.verify:
        errors = []
        for s in sorted(reachable):
            errors += replay(breeder, seeds, pool, s, plans[s][0])
        print("replay: %d plans, %d errors" % (len(reachable), len(errors)))
        bf = brute_force_check()
        print("brute force: %d errors" % len(bf))
        for e in (errors + bf)[:20]:
            print("  !", e)
        if errors or bf:
            return 1

    found = []
    if args.partner_value:
        targets = [r["species"] for r in sorted(rows, key=lambda r: -r["score"])[:args.plans]]
        base_cost = {r["species"]: r["pairs"] for r in rows}
        if args.partner_candidates == "all":
            # Includes species that can only be bred, so several answers will be
            # "obtain the thing you were trying to breed". An upper bound, not advice.
            candidates = {r["species"] for r in rows} - pool - seeds
        else:
            candidates = clean_pool(args.roster) - pool - seeds
        print("sweeping %d partner candidates (%s)..." % (len(candidates), args.partner_candidates))
        found = partner_value(breeder, seeds, pool, targets, base_cost, args.keep, candidates)
        for saved, best, improved, cand in found[:20]:
            print("  a clean %-20s -> %3d pairs saved across %d targets (best single: %d)"
                  % (cand, saved, improved, best))
        if not found:
            print("  (none improve any target)")

    write_report(args.out, rows, plans, pool, args.seeds,
                 unreachable_top[:10], found, args, elapsed)
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
