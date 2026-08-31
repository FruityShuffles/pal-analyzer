#!/usr/bin/env python3
"""Python mirror of the combat-score math in docs/FORMULAS.md.

This has no runtime role in the tool -- it exists only to LOCK the formula against
the known Mammorest/Kitsun crossover numbers before/while porting it to the JS in
pal_analyzer_template.html. If this passes and the JS reproduces the same numbers,
the port is faithful.

Run: python scoring_check.py
"""
import math


def iv_pct(talent_int):
    """IV% = TalentInt * 0.3 / 100  (Talent 100 -> 0.30, Talent 50 -> 0.15)."""
    return talent_int * 0.3 / 100.0


def stat_hp(hp_stat, level, hp_iv=0, hp_passive_pct=0.0, soul_rank=0, stars=0):
    inner = math.floor(500 + 5 * level + hp_stat * 0.5 * level * (1 + iv_pct(hp_iv)))
    return math.floor(inner * (1 + hp_passive_pct) * (1 + 0.03 * soul_rank) * (1 + 0.05 * stars))


def stat_attack(attack_stat, level, atk_iv=0, atk_passive_pct=0.0, soul_rank=0, stars=0):
    inner = math.floor(100 + attack_stat * 0.075 * level * (1 + iv_pct(atk_iv)))
    return math.floor(inner * (1 + atk_passive_pct) * (1 + 0.03 * soul_rank) * (1 + 0.05 * stars))


def stat_defense(defense_stat, level, def_iv=0, def_passive_pct=0.0, soul_rank=0, stars=0):
    # Base is 50, NOT 100 -- documented typo trap in the source (see FORMULAS.md).
    inner = math.floor(50 + defense_stat * 0.075 * level * (1 + iv_pct(def_iv)))
    return math.floor(inner * (1 + def_passive_pct) * (1 + 0.03 * soul_rank) * (1 + 0.05 * stars))


def combat_score(hp, attack, defense):
    """Cube root of the product of the three final stats."""
    return (hp * attack * defense) ** (1.0 / 3.0)


def element_bonus(element_boosts_by_passive, elements):
    """Best usable element boost, as a decimal.

    Element boosts raise damage dealt by attacks of one element, so they never touch
    the displayed Attack stat -- they enter the score as their own multiplier class.
    Every attack move is a single element, so only the best-boosted element the Pal
    actually HAS can be used; boosts naming the same element add. See FORMULAS.md.
    """
    best = 0.0
    for element in elements:
        best = max(best, sum(b.get(element, 0.0) for b in element_boosts_by_passive))
    return best / 100.0


def score_pal(hp_stat, attack_stat, defense_stat, level,
              hp_iv=0, atk_iv=0, def_iv=0,
              hp_passive=0.0, atk_passive=0.0, def_passive=0.0,
              soul_hp=0, soul_atk=0, soul_def=0, stars=0, trust=0,
              f_hp=0.0, f_atk=0.0, f_def=0.0, element_pct=0.0):
    hp = stat_hp(hp_stat + f_hp * trust, level, hp_iv, hp_passive, soul_hp, stars)
    atk = stat_attack(attack_stat + f_atk * trust, level, atk_iv, atk_passive, soul_atk, stars)
    dfn = stat_defense(defense_stat + f_def * trust, level, def_iv, def_passive, soul_def, stars)
    return hp, atk, dfn, combat_score(hp, atk * (1 + element_pct), dfn)


def main():
    # Mammorest 150/85/90, Kitsun 100/115/100 -- IV=0, no passives.
    cases = {
        ("Mammorest", 1): (150, 85, 90, 1, 151.0),
        ("Mammorest", 50): (150, 85, 90, 50, 899.6),
        ("Kitsun", 1): (100, 115, 100, 1, 150.6),
        ("Kitsun", 50): (100, 115, 100, 50, 901.8),
    }
    print(f"{'Pal':<12}{'Lvl':>4}  {'HP':>5}{'Atk':>5}{'Def':>5}  {'Score':>8}  {'Expect':>8}")
    results = {}
    all_ok = True
    for (name, lvl), (h, a, d, level, expect) in cases.items():
        hp, atk, dfn, score = score_pal(h, a, d, level)
        results[(name, lvl)] = score
        ok = abs(score - expect) < 0.1
        all_ok = all_ok and ok
        print(f"{name:<12}{lvl:>4}  {hp:>5}{atk:>5}{dfn:>5}  {score:>8.1f}  {expect:>8.1f}  {'OK' if ok else 'FAIL'}")

    # Crossover: Mammorest leads at L1, Kitsun leads at L50.
    l1_ok = results[("Mammorest", 1)] > results[("Kitsun", 1)]
    l50_ok = results[("Kitsun", 50)] > results[("Mammorest", 50)]
    print(f"\nMammorest > Kitsun @ L1 : {l1_ok}")
    print(f"Kitsun > Mammorest @ L50: {l50_ok}")
    crossover_ok = l1_ok and l50_ok

    assert all_ok, "score values did not match expected crossover numbers"
    assert crossover_ok, "crossover relationship not reproduced"

    augmented = {
        "Mammorest max souls + stars": score_pal(
            150, 85, 90, 50, soul_hp=20, soul_atk=20, soul_def=20, stars=4),
        "Kitsun synthetic T10": score_pal(
            100, 115, 100, 50, trust=10, f_hp=4.5, f_atk=3.5, f_def=2.9),
        "Mammorest ordering probe": score_pal(
            150, 85, 90, 50, atk_passive=0.20, soul_atk=20, stars=4,
            trust=10, f_hp=4.5, f_atk=3.5, f_def=2.9),
    }
    print("\nAugmented regression vectors:")
    for name, (hp, atk, dfn, score) in augmented.items():
        print(f"  {name}: hp={hp}, atk={atk}, def={dfn}, score={score:.6f}")
    expected_augmented = {
        "Mammorest max souls + stars": (8640, 802, 743, 1726.734799),
        "Kitsun synthetic T10": (4375, 662, 533, 1155.724763),
        "Mammorest ordering probe": (6750, 1267, 595, 1720.015859),
    }
    for name, (hp, atk, dfn, score) in augmented.items():
        exp_hp, exp_atk, exp_def, exp_score = expected_augmented[name]
        assert (hp, atk, dfn) == (exp_hp, exp_atk, exp_def), f"{name} stat vector changed"
        assert abs(score - exp_score) < 1e-6, f"{name} score changed"
    assert abs(score_pal(150, 85, 90, 50)[3] - results[("Mammorest", 50)]) < 1e-12
    assert augmented["Mammorest max souls + stars"][3] > results[("Mammorest", 50)]
    assert augmented["Kitsun synthetic T10"][3] > results[("Kitsun", 50)]
    assert augmented["Mammorest ordering probe"][3] > results[("Mammorest", 50)]

    # Element boosts: best usable element only, off-element boosts are worth nothing,
    # same-element boosts add. Mirrors elementBonus() in the template.
    lunker = {"Water": 20.0, "Ice": 20.0}
    flame, sea = {"Fire": 30.0}, {"Water": 30.0}
    assert element_bonus([lunker], ["Water", "Electric"]) == 0.20
    assert element_bonus([flame], ["Water"]) == 0.0
    assert element_bonus([flame, sea], ["Fire", "Water"]) == 0.30, "best element, not the sum"
    assert element_bonus([lunker, sea], ["Water"]) == 0.50, "same-element boosts add"

    # Penking Lux (Water/Electric, 105/105/100) with Lunker: +20% Defense and a +20%
    # Water damage boost the stat screen never shows. Both legs must land.
    bare = score_pal(105, 105, 100, 50)
    lunk = score_pal(105, 105, 100, 50, def_passive=0.20,
                     element_pct=element_bonus([lunker], ["Water", "Electric"]))
    print("\nElement-boost vector (Penking Lux + Lunker @ L50):")
    print(f"  bare  : hp={bare[0]}, atk={bare[1]}, def={bare[2]}, score={bare[3]:.6f}")
    print(f"  Lunker: hp={lunk[0]}, atk={lunk[1]}, def={lunk[2]}, score={lunk[3]:.6f}")
    assert lunk[1] == bare[1], "an element boost must not move the displayed Attack stat"
    assert lunk[2] == round(bare[2] * 1.2), "Lunker's Defense leg"
    assert abs(lunk[3] / bare[3] - 1.2 ** (2 / 3)) < 1e-3, "score gains both 20% legs"
    print("\nALL CHECKS PASSED -- formula locked.")


if __name__ == "__main__":
    main()
