#!/usr/bin/env python3
"""Python mirror of the breeding math in docs/BREEDING.md.

Like scoring_check.py, this has no runtime role -- it LOCKS the algorithm before and
while porting it to the JS in pal_analyzer_template.html. The child-species rules are
the part worth locking: they are pure data lookups with two easy-to-get-wrong details
(the +1 sits inside the floor, and ties break toward the HIGHER combi_priority), plus
two candidate-pool exclusions that most public write-ups omit entirely.

Run: python breeding_check.py

Provenance of the expected values in CHILD_FIXTURE: this implementation was diffed
against tylercamp/palcalc's precomputed PalCalc.Model/breeding.json (an independent
CUE4Parse-based implementation) over all 44,552 parent pairs the two builds share --
0 mismatches. The fixture below is a representative slice of that comparison, kept
inline so this checker stays stdlib-only and offline like the rest of the repo.
"""
import json
import math
import os
import sys
from itertools import combinations

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


# ---------------------------------------------------------------------------
# Child species
# ---------------------------------------------------------------------------
def load_tables(data_dir=DATA):
    with open(os.path.join(data_dir, "pals.json"), encoding="utf-8") as f:
        pals = json.load(f)["pals"]
    with open(os.path.join(data_dir, "breeding.json"), encoding="utf-8") as f:
        unique = json.load(f)["breeding"]["unique"]
    return pals, unique


def build_index(pals, unique):
    """Precompute the unique-combo lookup and the generic candidate pool.

    Two exclusions define the pool, and both are load-bearing:
      * ignore_combi species (legendaries, raid/event Pals) are never produced by the
        rank rule -- though they may still be used as parents;
      * a species that is the child of a unique combo can ONLY be produced by that
        combo, so it is struck from the pool as well.
    """
    combos = {}
    for c in unique:
        combos.setdefault((c["a"], c["b"]), []).append((c["ga"], c["gb"], c["child"]))
        combos.setdefault((c["b"], c["a"]), []).append((c["gb"], c["ga"], c["child"]))
    combo_children = {c["child"] for c in unique}
    pool = [(n, p["combi_rank"], p["combi_priority"], p["variant"])
            for n, p in pals.items()
            if not p["ignore_combi"] and n not in combo_children]
    return combos, combo_children, sorted(pool)


def can_breed(name, pals):
    """Whether a species may be used as a PARENT at all.

    A third exclusion, independent of the two in build_index() and the only one on the
    parent side. ignore_combi bars a species from being a rank-rule child but leaves it
    a legal parent; these four (Astralym, Boltmane, Dragostrophe, Panthalus) fit in no
    breeding pen and so are neither. The flag is derived at import time from having no
    work suitability -- the game has no explicit "cannot breed" field, so this is an
    inference; see docs/DATA_SOURCES.md. Deliberately NOT folded into child_species():
    that stays a pure mirror of the game's rule, locked against palcalc.
    """
    p = pals.get(name)
    return bool(p) and p.get("can_breed", True)


def child_species(a, b, pals, combos, pool, gender_a="", gender_b=""):
    """The child of parents a x b. Genders only matter for gender-pinned combos."""
    if a == b:
        return a
    for pin_a, pin_b, child in combos.get((a, b), []):
        if (not pin_a or pin_a == gender_a) and (not pin_b or pin_b == gender_b):
            return child
    # The +1 is INSIDE the floor: this is round-half-up, not truncation.
    target = (pals[a]["combi_rank"] + pals[b]["combi_rank"] + 1) // 2
    # Nearest rank wins; ties go to the HIGHER combi_priority, then to the non-variant
    # Pal, then to the name so the result never depends on dict iteration order.
    return min(pool, key=lambda p: (abs(p[1] - target), -p[2], p[3], p[0]))[0]


# ---------------------------------------------------------------------------
# Inheritance probabilities
# ---------------------------------------------------------------------------
# Number of passives drawn directly from the parents' combined, deduplicated pool.
PASSIVE_DIRECT = {1: 0.40, 2: 0.30, 3: 0.20, 4: 0.10}
# Independently, this many extra passives are rolled from the lottery table. Four is
# impossible (the game indexes a 4-element array with a 0..3 result).
PASSIVE_RANDOM = {0: 0.40, 1: 0.30, 2: 0.20, 3: 0.10}
# Number of the three IVs taken from a parent; the rest are re-rolled. At least one is
# always inherited. Lower confidence than the passive table -- empirical, not disassembly.
IV_DIRECT = {1: 0.50, 2: 0.25, 3: 0.25}


def p_inherit(pool_size, wanted):
    """P(all `wanted` desired passives are among those drawn from the parent pool).

    This is a SUPERSET event, not an exact match: an extra inherited passive is not a
    failure, because a passive can be overwritten for the same gold an empty slot costs
    to fill (docs/AUGMENTS.md section 5). Scoring the exact-match event instead pushes
    almost every plan into the 25-250 egg range, where the ranking stops discriminating.
    """
    if wanted > pool_size or wanted > 4:
        return 0.0
    if wanted == 0:
        return 1.0
    total = 0.0
    for n, p_n in PASSIVE_DIRECT.items():
        drawn = min(n, pool_size)
        if drawn < wanted:
            continue
        total += p_n * (math.comb(pool_size - wanted, drawn - wanted)
                        / math.comb(pool_size, drawn))
    return total


def p_accept(pool_size, wanted, max_extras=None):
    """P(a hatch is ACCEPTABLE: it carries all `wanted` passives and at most
    `max_extras` others).

    Generalises p_inherit(), which is exactly the `max_extras is None` case. The extra
    dimension exists because junk is a PRICE, not a wall (docs/WISHLIST.md section 2):
    a dirty parent only enlarges the pool the wanted passives are drawn from, so at
    every step the breeder chooses how picky to be. Holding out for a cleaner egg costs
    hatches now and buys a smaller pool later, and which side wins is arithmetic.

    Unlike p_inherit(), the lottery matters here. A capped draw leaves `4 - drawn` free
    slots and the lottery fills up to 3 of them, so being picky also means re-rolling
    every lottery hit -- which is why an exact-match intermediate carries a flat 2.5x
    that the superset event never pays.
    """
    if wanted > 4 or wanted > pool_size:
        return 0.0
    total = 0.0
    for n, p_n in PASSIVE_DIRECT.items():
        drawn = min(n, pool_size)
        if drawn < wanted:
            continue
        p_draw = (math.comb(pool_size - wanted, drawn - wanted)
                  / math.comb(pool_size, drawn))
        if max_extras is None:
            total += p_n * p_draw
            continue
        # Total passives are capped at 4, so the lottery can only fill what the direct
        # draw left empty; anything beyond that is discarded by the game, not by us.
        room = 4 - drawn
        p_lot = sum(p_l for l, p_l in PASSIVE_RANDOM.items()
                    if (drawn - wanted) + min(l, room) <= max_extras)
        total += p_n * p_draw * p_lot
    return total


def expected_iv(iv_a, iv_b):
    """Expected child IV for one stat.

    E[N inherited] = 1.75 of 3, so each stat is inherited with probability 1.75/3; an
    inherited stat copies a random parent, and a re-rolled one averages 50.
    """
    p = sum(n * w for n, w in IV_DIRECT.items()) / 3.0
    return p * (iv_a + iv_b) / 2.0 + (1 - p) * 50.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
# (parent A, parent B, gender A, gender B, expected child). Display names, matching
# data/pals.json. Verified against palcalc's table -- see the module docstring.
# (pool size, wanted, max extras, expected P). max extras -1 == unlimited, which is
# the p_inherit() superset event. Hand-computable anchors for docs/WISHLIST.md section 2.
ACCEPT_FIXTURE = [
    (1, 1, -1, 1.0),
    (2, 1, -1, 0.8),
    (2, 2, -1, 0.6),
    (4, 2, -1, 0.25),
    (8, 1, -1, 0.25),
    (3, 3, -1, 0.3),
    (0, 0, -1, 1.0),
    # The last step of a 4-passive wish: one junk passive on either parent is a 5x
    # penalty, two is 15x. This is why cleaning pays at |D| = 4 and nowhere else.
    (4, 4, -1, 0.1),
    (5, 4, -1, 0.02),
    (6, 4, -1, 0.006666666666666667),
    # Picky hatches. A clean partner out of two clean parents is P(no lottery) = 0.4.
    (0, 0, 0, 0.4),
    (1, 1, 0, 0.4),
    (2, 1, 0, 0.08),
    (3, 1, 0, 0.05333333333333334),
    (2, 2, 0, 0.24),
    (3, 1, 1, 0.17333333333333334),
    # With all four slots taken by the direct draw the lottery has no room, so the
    # picky and permissive cases coincide.
    (4, 4, 0, 0.1),
]

CHILD_FIXTURE = [
    ('Lamball', 'Lamball', '', '', 'Lamball'),
    ('Anubis', 'Anubis', '', '', 'Anubis'),
    ('Jetragon', 'Jetragon', '', '', 'Jetragon'),
    ('Frostallion', 'Frostallion', '', '', 'Frostallion'),
    ('Chikipi', 'Chikipi', '', '', 'Chikipi'),
    ('Katress', 'Wixen', 'Male', 'Female', 'Wixen Noct'),
    ('Katress', 'Wixen', 'Female', 'Male', 'Katress Ignis'),
    ('Azurobe', 'Frostplume', '', '', 'Azurobe Cryst'),
    ('Beakon', 'Frostplume', '', '', 'Beakon Cryst'),
    ('Croajiro Noct', 'Venusa', '', '', 'Skutlass'),
    ('Hangyu Cryst', 'Xenolord', '', '', 'Dogen'),
    ('Bristla', 'Warsect', '', '', 'Lullu'),
    ('Univolt', 'Dogen', '', '', 'Valentail'),
    ('Wixen Noct', 'Lullu', '', '', 'Slowatt'),
    ('Dazzi', 'Xenogard', '', '', 'Carnibora'),
    ('Orserk', 'Daedream', '', '', 'Shroomer'),
    ('Whalaska Ignis', 'Caprity Noct', '', '', 'Verdash'),
    ('Gobfin', 'Souffline', '', '', 'Elphidran'),
    ('Xenovader', 'Sekhmet', '', '', 'Tropicaw'),
    ('Nitewing', 'Loomen', '', '', 'Tarantriss'),
    ('Lapiron', 'Celesdir', '', '', 'Helzephyr'),
    ('Dogen', 'Suzaku Aqua', '', '', 'Pierdon'),
    ('Warsect', 'Woolipop', '', '', 'Mossanda'),
    ('Wumpo Botan', 'Selyne', '', '', 'Astegon'),
    ('Killamari', 'Skutlass', '', '', 'Dinossom'),
    ('Lapiron', 'Dupin', '', '', 'Pierdon'),
    ('Pierdon', 'Souffline', '', '', 'Bushi'),
    ('Chillet Ignis', 'Finsider Ignis', '', '', 'Dinossom'),
    ('Quivern', 'Nitemary', '', '', 'Nitemary'),
    ('Pengullet', 'Herbil', '', '', 'Mozzarina'),
    ('Foxparks', 'Enchanted Sword', '', '', 'Lamball'),
    ('Herbil', 'Hoocrates', '', '', 'Fuddler'),
    ('Dumud', 'Swee', '', '', 'Galeclaw'),
    ('Pierdon Cryst', 'Dazzi Noct', '', '', 'Bulldosu'),
    ('Digtoise', 'Mossanda Lux', '', '', 'Prixter'),
    ('Dazemu', 'Nox', '', '', 'Galeclaw'),
    ('Beegarde', 'Celaray Lux', '', '', 'Cawgnito'),
    ('Elphidran Aqua', 'Jolthog', '', '', 'Tombat'),
    ('Munchill', 'Nox', '', '', 'Gloopie'),
    ('Sibelyx', 'Smokie', '', '', 'Elizabee'),
    ('Clovee', 'Elgrove Cryst', '', '', 'Maraith'),
    ('Kelpsea', 'Smokie', '', '', 'Dumud'),
    ('Starryon', 'Menasting', '', '', 'Omascul'),
    ('Hangyu Cryst', 'Ghangler', '', '', 'Carnibora'),
    ('Illuminant Bat', 'Prixter Lux', '', '', 'Pyrin'),
    ('Robinquill Terra', 'Mycora', '', '', 'Leafan'),
    ('Gumoss', 'Dazzi', '', '', 'Direhowl'),
    ('Gloopie Primo', 'Snock', '', '', 'Maraith'),
    ('Muffly', 'Clovee', '', '', 'Tocotoco'),
    ('Beakon', 'Prixter Lux', '', '', 'Warsect'),
    ('Kingpaca', 'Lamball', '', '', 'Herbil'),
    ('Bushi Noct', 'Azurobe', '', '', 'Mammorest'),
    ('Tetroise Primo', 'Ragnahawk', '', '', 'Wumpo Botan'),
    ('Loomen', 'Whalaska', '', '', 'Lapure'),
    ('Petallia Ignis', 'Loomen', '', '', 'Frostplume'),
    ('Woolipop', 'Flambelle', '', '', 'Cattiva'),
    ('Silvegis', 'Sekhmet', '', '', 'Whalaska'),
    ('Shroomer Noct', 'Lamball', '', '', 'Wispaw'),
    ('Prixter Lux', 'Blue Slime', '', '', 'Pyrin'),
    ('Daedream', 'Sibelyx', '', '', 'Puffolt'),
    ('Mau', 'Fuack', '', '', 'Sparkit'),
    ('Surfent', 'Bellanoir', '', '', 'Bakemi'),
    ('Solenne', 'Foxcicle', '', '', 'Helzephyr'),
    ('Herbil', 'Killamari', '', '', 'Flambelle'),
    ('Ophydia', 'Digtoise', '', '', 'Loomen'),
    ('Menasting', 'Arsox', '', '', 'Petallia'),
    ('Xenogard', 'Needoll', '', '', 'Maraith'),
    ('Mycora', 'Petallia', '', '', 'Palumba'),
    ('Dinossom', 'Mossanda', '', '', 'Wixen'),
    ('Menasting Terra', 'Menasting', '', '', 'Ghangler'),
    ('Lovander', 'Elgrove', '', '', 'Mossanda'),
    ('Foxparks', 'Beakon', '', '', 'Tombat'),
    ('Cattiva', 'Shroomer', '', '', 'Gorirat'),
    ('Univolt Cryst', 'Lyleen Noct', '', '', 'Flaracle'),
    ('Gumoss', 'Splatterina', '', '', 'Valentail'),
    ('Dazzi Noct', 'Amione', '', '', 'Kingpaca'),
    ('Paladius', 'Grintale', '', '', 'Starryon'),
    ('Purple Slime', 'Tropicaw', '', '', 'Yakumo'),
    ('Jormuntide Ignis', 'Menasting Terra', '', '', 'Blazamut'),
    ('Jolthog', 'Tropicaw', '', '', 'Dazemu'),
    ('Beegarde', 'Celesdir Noct', '', '', 'Mammorest'),
    ('Tropicaw', 'Kelpsea', '', '', 'Wixen'),
    ('Whalaska', 'Nitemary Botan', '', '', 'Majex'),
    ('Celesdir', 'Wumpo', '', '', 'Whalaska'),
    ('Vixy', 'Pengullet Lux', '', '', 'Hangyu'),
    ('Woolipop Terra', 'Jormuntide', '', '', 'Mammorest'),
    ('Bakemi', 'Munchill', '', '', 'Azurobe'),
    ('Quivern Botan', 'Beakon Cryst', '', '', 'Venusa'),
    ('Leezpunk Ignis', 'Jolthog Cryst', '', '', 'Celaray'),
    ('Azurobe Cryst', 'Omascul', '', '', 'Wistella'),
    ('Broncherry Aqua', 'Xenogard', '', '', 'Cryolinx'),
    ('Caprity Noct', 'Icelyn', '', '', 'Felbat'),
    ('Venusa', 'Tetroise Primo', '', '', 'Jormuntide'),
    ('Shadowbeak', 'Cryolinx Terra', '', '', 'Dualith'),
    ('Mossanda', 'Celaray Lux', '', '', 'Kingpaca'),
    ('Tombat', 'Jolthog Cryst', '', '', 'Croajiro'),
    ('Mycora', 'Dandilord', '', '', 'Blazamut'),
    ('Elgrove Cryst', 'Chikipi', '', '', 'Smokie'),
    ('Shadowbeak', 'Roujay', '', '', 'Roujay'),
    ('Hoodle', 'Foxparks Cryst', '', '', 'Gorirat'),
    ('Tombat', 'Kingpaca', '', '', 'Elphidran'),
    ('Tanzee', 'Mossanda Lux', '', '', 'Sweepa'),
    ('Skutlass', 'Jetragon', '', '', 'Moldron'),
    ('Purple Slime', 'Warsect Terra', '', '', 'Valentail'),
    ('Woolipop', 'Gildane', '', '', 'Snock'),
    ('Clovee', 'Beakon Cryst', '', '', 'Snock'),
    ('Univolt Cryst', 'Turtacle', '', '', 'Vaelet'),
    ('Woolipop Terra', 'Caprity', '', '', 'Arsox'),
    ('Elizabee', 'Reptyro Cryst', '', '', 'Suzaku'),
]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def near(x, y, tol=1e-9):
    return abs(x - y) < tol


def main():
    pals, unique = load_tables()
    combos, combo_children, pool = build_index(pals, unique)
    failures = []

    def check(label, got, expected, tol=None):
        ok = near(got, expected, tol) if tol is not None else got == expected
        if not ok:
            failures.append(f"{label}: got {got!r}, expected {expected!r}")
        return ok

    print(f"{len(pals)} species, {len(unique)} unique combos, "
          f"{len(combo_children)} combo-only children, {len(pool)} in the generic pool")

    # -- child species ------------------------------------------------------
    bad = 0
    for a, b, ga, gb, expect in CHILD_FIXTURE:
        got = child_species(a, b, pals, combos, pool, ga, gb)
        if got != expect:
            bad += 1
            if bad <= 8:
                pin = f" ({ga or '-'}/{gb or '-'})" if (ga or gb) else ""
                failures.append(f"child {a} x {b}{pin}: got {got}, expected {expect}")
    print(f"child fixture: {len(CHILD_FIXTURE) - bad}/{len(CHILD_FIXTURE)} pass")

    # Symmetry: only the gender-pinned pair may depend on argument order.
    asym = [(a, b) for a, b, ga, gb, _ in CHILD_FIXTURE if not (ga or gb)
            if child_species(a, b, pals, combos, pool)
            != child_species(b, a, pals, combos, pool)]
    check("unpinned combos are symmetric", asym, [])

    # The one gender-dependent outcome in the game.
    check("Katress(M) x Wixen(F)",
          child_species("Katress", "Wixen", pals, combos, pool, "Male", "Female"),
          "Wixen Noct")
    check("Katress(F) x Wixen(M)",
          child_species("Katress", "Wixen", pals, combos, pool, "Female", "Male"),
          "Katress Ignis")

    # -- pool exclusions ----------------------------------------------------
    names = {p[0] for p in pool}
    check("ignore_combi species are not breedable children",
          sorted(n for n in names if pals[n]["ignore_combi"]), [])
    check("combo-only children are not in the generic pool",
          sorted(names & combo_children), [])
    check("Frostallion (legendary) excluded from the pool", "Frostallion" in names, False)
    # ...but legendaries must still work as parents, via the same-species rule.
    check("Frostallion x Frostallion", child_species("Frostallion", "Frostallion",
                                                     pals, combos, pool), "Frostallion")

    # -- parent exclusions --------------------------------------------------
    # Independent of the child pool above: these four cannot be penned at all. If this
    # list moves, a game patch changed the underlying work-suitability data and every
    # breeding answer the app gives moved with it.
    check("species that cannot be bred at all",
          sorted(n for n in pals if not can_breed(n, pals)),
          ["Astralym", "Boltmane", "Dragostrophe", "Panthalus"])
    check("a legendary is still a legal parent", can_breed("Frostallion", pals), True)
    # child_species() must be untouched by the parent gate -- it stays the locked mirror.
    check("Panthalus x Panthalus still resolves by the raw rule",
          child_species("Panthalus", "Panthalus", pals, combos, pool), "Panthalus")

    # Every pool rank is unique, which is what makes the priority tiebreak a total order.
    ranks = [p[1] for p in pool]
    check("pool combi_ranks are distinct", len(set(ranks)), len(ranks))

    # -- the tiebreak actually matters --------------------------------------
    # Ranks are multiples of 10, so a target ending in 5 sits exactly between two
    # candidates. Confirm such ties exist and that flipping the tiebreak changes answers.
    def child_low_priority_wins(a, b):
        target = (pals[a]["combi_rank"] + pals[b]["combi_rank"] + 1) // 2
        return min(pool, key=lambda p: (abs(p[1] - target), p[2], p[3], p[0]))[0]

    flipped = sum(1 for a, b, ga, gb, _ in CHILD_FIXTURE
                  if not (ga or gb) and a != b and (a, b) not in combos
                  and child_species(a, b, pals, combos, pool) != child_low_priority_wins(a, b))
    if flipped == 0:
        failures.append("tiebreak direction is untested -- no fixture case discriminates it")
    print(f"tiebreak: {flipped} fixture cases distinguish higher- from lower-priority wins")

    # -- probabilities ------------------------------------------------------
    check("direct-draw probabilities sum to 1", sum(PASSIVE_DIRECT.values()), 1.0, 1e-9)
    check("random-add probabilities sum to 1", sum(PASSIVE_RANDOM.values()), 1.0, 1e-9)
    check("IV-count probabilities sum to 1", sum(IV_DIRECT.values()), 1.0, 1e-9)

    # Hand-computable anchors (docs/BREEDING.md section 3).
    # One wanted from a pool of one: every draw takes it.
    check("p_inherit(1, 1)", p_inherit(1, 1), 1.0, 1e-12)
    # Pool of 2, want 1: P(1)*1/2 + P(2)*1 + P(3..4 clamp to 2)*1 = .2+.3+.2+.1 = .8
    check("p_inherit(2, 1)", p_inherit(2, 1), 0.80, 1e-12)
    # Pool of 2, want both: only draws of 2+ can contain both = .30+.20+.10 = .60
    check("p_inherit(2, 2)", p_inherit(2, 2), 0.60, 1e-12)
    check("p_inherit(4, 2)", p_inherit(4, 2), 0.25, 1e-12)
    check("p_inherit(8, 1)", p_inherit(8, 1), 0.25, 1e-12)
    check("p_inherit(3, 3)", p_inherit(3, 3), 0.30, 1e-12)
    check("p_inherit(5, 5) is impossible (4 slots)", p_inherit(5, 5), 0.0, 1e-12)
    check("p_inherit(n, 0) is certain", p_inherit(6, 0), 1.0, 1e-12)

    # Monotonic in both arguments: more junk on the parents is never better, and
    # wanting more passives is never easier.
    for k in (1, 2, 3):
        vals = [p_inherit(m, k) for m in range(k, 12)]
        if vals != sorted(vals, reverse=True):
            failures.append(f"p_inherit is not decreasing in pool size at k={k}: {vals}")
    for m in (4, 6, 8):
        vals = [p_inherit(m, k) for k in range(1, 5)]
        if vals != sorted(vals, reverse=True):
            failures.append(f"p_inherit is not decreasing in wanted at m={m}: {vals}")

    # -- acceptance probability (the wishlist solver) -----------------------
    # p_accept generalises p_inherit with a "how picky am I" dimension. The two must
    # agree exactly wherever pickiness is unlimited, or the wishlist and the breeding
    # panel are quoting different games.
    for m in range(0, 10):
        for k in range(0, 5):
            if not near(p_accept(m, k), p_inherit(m, k), 1e-12):
                failures.append(f"p_accept({m},{k},None) != p_inherit({m},{k})")
    bad = 0
    for m, k, x, expect in ACCEPT_FIXTURE:
        got = p_accept(m, k, None if x < 0 else x)
        if not near(got, expect, 1e-12):
            bad += 1
            failures.append(f"p_accept({m},{k},{x}): got {got!r}, expected {expect!r}")
    print(f"accept fixture: {len(ACCEPT_FIXTURE) - bad}/{len(ACCEPT_FIXTURE)} pass")

    # Being pickier is never easier, and never harder than impossible.
    for m in range(0, 8):
        for k in range(0, min(m, 4) + 1):
            vals = [p_accept(m, k, x) for x in range(0, 5)] + [p_accept(m, k)]
            if vals != sorted(vals):
                failures.append(f"p_accept is not increasing in max_extras at m={m},k={k}")

    # A hatch with all four slots filled by the direct draw has no room for the
    # lottery, so pickiness costs nothing there -- the one place the two coincide.
    check("p_accept(4,4,0) == p_inherit(4,4)", p_accept(4, 4, 0), p_inherit(4, 4), 1e-12)
    # ...and the one place it is most expensive: a single wanted passive out of a
    # 3-pool, insisting on nothing else, is 18.8 eggs against 3.0 for the superset.
    check("cleaning a dirty carrier costs 18.8 eggs",
          1 / p_accept(3, 1, 0), 18.75, 1e-9)
    check("the same carrier used dirty costs 4.0 eggs", 1 / p_accept(4, 2), 4.0, 1e-9)

    # -- IVs ----------------------------------------------------------------
    check("expected_iv(100, 100)", expected_iv(100, 100), 79.16666666666667, 1e-9)
    check("expected_iv(0, 0)", expected_iv(0, 0), 20.833333333333336, 1e-9)
    check("expected_iv(50, 50) is a fixed point", expected_iv(50, 50), 50.0, 1e-9)
    check("expected_iv is symmetric", expected_iv(10, 90), expected_iv(90, 10), 1e-12)

    # -- report -------------------------------------------------------------
    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        sys.exit(f"{len(failures)} check(s) failed")
    print("All breeding checks passed.")


if __name__ == "__main__":
    main()
