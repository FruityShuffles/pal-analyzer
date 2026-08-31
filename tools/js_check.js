#!/usr/bin/env node
/* Run the real runtime JS out of pal_analyzer.html under Node.
 *
 * There is no headless browser here, so the only way to exercise the shipping code
 * (rather than a re-implementation of it) is to extract the <script> and evaluate it
 * in a vm context with minimal document/localStorage stubs. Top-level `let` bindings
 * are not context properties, so an epilogue exposes the ones the tests need.
 *
 * The load itself runs the page's own console.assert self-test; this file adds the
 * checks that need a roster or would be too slow to run on every page load, and
 * cross-checks childSpecies() against the same fixture breeding_check.py asserts, and
 * validates every wishlist plan against the real breeding rule step by step.
 *
 * Run: node tools/js_check.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'pal_analyzer.html'), 'utf8');

const m = html.match(/<script>([\s\S]*)<\/script>/);
if (!m) { console.error('no <script> found in pal_analyzer.html'); process.exit(1); }

let failures = 0;
const fail = (msg) => { failures++; console.error('  FAIL  ' + msg); };
const check = (label, got, expected) => {
  const ok = JSON.stringify(got) === JSON.stringify(expected);
  if (!ok) fail(`${label}: got ${JSON.stringify(got)}, expected ${JSON.stringify(expected)}`);
  return ok;
};

// --- stubs -----------------------------------------------------------------
// init() touches the DOM on load, so every getElementById must return something
// inert rather than null. Nothing here needs to render.
const el = () => new Proxy({
  style: {}, dataset: {}, classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
  value: '', textContent: '', innerHTML: '', checked: false, disabled: false,
  addEventListener(){}, removeEventListener(){}, appendChild(){}, querySelectorAll(){ return []; },
  querySelector(){ return null; }, closest(){ return null; }, focus(){}, click(){}, remove(){},
  getAttribute(){ return null; }, setAttribute(){}, insertAdjacentHTML(){},
}, { get(t, k){ return k in t ? t[k] : (typeof k === 'string' ? el() : undefined); } });

let assertFailures = [];
const store = {};
const ctx = {
  console: {
    log(){},
    warn(){},
    error(){},
    assert(cond, ...rest){ if (!cond) assertFailures.push(rest.join(' ')); },
  },
  document: {
    getElementById: () => el(),
    createElement: () => el(),
    querySelectorAll: () => [],
    querySelector: () => null,
    addEventListener(){},
    body: el(),
  },
  localStorage: {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  },
  performance: { now: () => Number(process.hrtime.bigint() / 1000n) / 1000 },
  setTimeout, clearTimeout, Math, JSON, Date, Object, Array, Set, Map, String, Number,
  Boolean, isNaN, isFinite, parseInt, parseFloat, alert(){}, confirm: () => false,
  Blob: function(){}, URL: { createObjectURL: () => '', revokeObjectURL(){} },
  FileReader: function(){},
};
ctx.scrollTo = () => {};
ctx.window = ctx;
ctx.globalThis = ctx;

// Expose the top-level `let` bindings, which are not context properties.
const epilogue = `
;globalThis.__t = {
  get state(){ return state; }, set state(v){ state = v; },
  get activeOwners(){ return activeOwners; },
  PALS_DB, PASSIVES_DB, BREEDING_DB, CHILD_POOL, UNBUYABLE, BREED_COLUMNS,
  CHASE_BAR, CHASE_POOL, CRAFT_POOL, PREMIUM_POOL,
  get breedCache(){ return breedCache; }, set breedCache(v){ breedCache = v; },
  nodeSpecies, nodeId, POPCNT, ACCEPT, WISH_BUDGET_MS, wishResults, wishBusy,
};
`;
vm.createContext(ctx);
try {
  vm.runInContext(m[1] + epilogue, ctx, { filename: 'pal_analyzer.html' });
} catch (e) {
  console.error('script threw on load:', e && e.stack || e);
  process.exit(1);
}

console.log('loaded pal_analyzer.html script');
if (assertFailures.length) {
  console.error(`\n${assertFailures.length} in-page self-test assertion(s) failed:`);
  assertFailures.forEach(a => fail('in-page: ' + a));
} else {
  console.log('in-page self-test: no assertion failures');
}

// --- childSpecies cross-check against the Python fixture --------------------
// Same expectations breeding_check.py asserts, so the two ports cannot drift.
const py = fs.readFileSync(path.join(ROOT, 'breeding_check.py'), 'utf8');
const block = py.match(/CHILD_FIXTURE = \[([\s\S]*?)\n\]/);
if (!block) { fail('could not read CHILD_FIXTURE out of breeding_check.py'); }
else {
  const fixture = [];
  const re = /\(\s*'((?:[^'\\]|\\.)*)',\s*'((?:[^'\\]|\\.)*)',\s*'((?:[^'\\]|\\.)*)',\s*'((?:[^'\\]|\\.)*)',\s*'((?:[^'\\]|\\.)*)'\s*\)/g;
  let g;
  while ((g = re.exec(block[1]))) fixture.push(g.slice(1, 6).map(s => s.replace(/\\'/g, "'")));
  let bad = 0;
  for (const [a, b, ga, gb, expect] of fixture) {
    const got = ctx.childSpecies(a, b, ga, gb);
    if (got !== expect) {
      bad++;
      if (bad <= 5) fail(`childSpecies ${a} x ${b}: got ${got}, expected ${expect}`);
    }
  }
  console.log(`childSpecies fixture: ${fixture.length - bad}/${fixture.length} match breeding_check.py`);
  if (!fixture.length) fail('fixture parsed as empty -- the regex no longer matches');
}

// --- planPassives() is actually optimal --------------------------------------
// Brute-force the same objective with no frontier bookkeeping and no pruning, and
// require an exact match. This exists because an attempt to shrink the candidate list by
// dropping "dominated" buyables (Ferocious +20 Atk looks redundant beside Musclehead +30)
// silently cost up to 5% multiplier on ~60% of real rosters: bonuses are ADDITIVE, so a
// weaker passive is still worth a slot alongside a stronger one. Any future pruning of
// that walk has to pass this.
{
  const { PASSIVES_DB, CRAFT_POOL, PREMIUM_POOL } = ctx.__t;
  const boostFor = (p, e) => e ? ((p.element_boosts || {})[e] || 0) : 0;
  const bruteMult = (have, tiers, els) => {
    const pool = [];
    if (tiers.includes('craft')) pool.push(...CRAFT_POOL);
    if (tiers.includes('premium')) pool.push(...PREMIUM_POOL);
    const cand = have.concat(pool.filter(n => !have.includes(n)));
    const vec = n => { const p = PASSIVES_DB[n] || {};
      return [p.attack_pct||0, p.defense_pct||0, p.hp_pct||0, boostFor(p,els[0]), boostFor(p,els[1])]; };
    let best = 0;
    const rec = (i, pick) => {
      // A passive can only be dropped by buying over it: purchases >= passives dropped.
      const buys = pick.filter(x => x >= have.length).length;
      if (buys >= have.length - (pick.length - buys)) {
        let a=0,d=0,h=0,e0=0,e1=0;
        for (const x of pick) { const v = vec(cand[x]); a+=v[0]; d+=v[1]; h+=v[2]; e0+=v[3]; e1+=v[4]; }
        const mm = (1+a/100)*(1+d/100)*(1+h/100)*(1+Math.max(e0,e1)/100);
        if (mm > best) best = mm;
      }
      if (pick.length === 4) return;
      for (let j = i; j < cand.length; j++) { pick.push(j); rec(j+1, pick); pick.pop(); }
    };
    rec(0, []);
    return best;
  };
  // Cases chosen to cover: empty, junk-only, a max-tier passive already held, an
  // element-boost Pal, and a full 4-slot Pal that must buy over something.
  const cases = [
    [[], ['Water']], [['Hard Skin'], ['Water']], [['Legend'], ['Dragon']],
    [['Musclehead'], ['Ground']], [['Demon God', 'Legend'], ['Dark']],
    [['Insomnia','Serious','Work Slave','Infinite Stamina'], ['Ground']],
    [['Idiosyncratic','Ranch Master','Serious','Artisan'], ['Fire','Dark']],
    [['Pyromaniac'], ['Fire']], [['Brittle','Coward'], ['Ice']],
  ];
  let planBad = 0;
  for (const tiers of ['craft', 'premium', 'craft+premium']) {
    for (const [have, els] of cases) {
      const plan = ctx.planPassives(have, tiers, els);
      let a=0,d=0,h=0,e0=0,e1=0;
      for (const n of plan.passives) { const p = PASSIVES_DB[n] || {};
        a+=p.attack_pct||0; d+=p.defense_pct||0; h+=p.hp_pct||0;
        e0+=boostFor(p,els[0]); e1+=boostFor(p,els[1]); }
      const got = (1+a/100)*(1+d/100)*(1+h/100)*(1+Math.max(e0,e1)/100);
      const want = bruteMult(have, tiers, els);
      if (Math.abs(got - want) > 1e-9) {
        planBad++;
        console.error(`  planPassives suboptimal: tiers=${tiers} have=[${have}] els=[${els}] `
          + `got ${got.toFixed(6)} want ${want.toFixed(6)} plan=[${plan.passives}]`);
      }
    }
  }
  check('planPassives matches an unpruned brute force', planBad, 0);
}

// --- search invariants on a synthetic roster --------------------------------
// The bugs this guards against are all "the plan is fiction": pairing a Pal with
// itself, pairing two males, or naming a parent that isn't in the roster.
const mk = (o) => ctx.normalizeEntry(o);
const roster = [
  // A single Anubis carrying Legend: no plan may pair it with itself.
  mk({ id: 'a1', species: 'Anubis', passives: ['Legend'], gender: 'Male', level: 50 }),
  // Two same-gender Lamballs: no plan may pair these two either.
  mk({ id: 'b1', species: 'Lamball', passives: ['Lucky'], gender: 'Female', level: 50 }),
  mk({ id: 'b2', species: 'Lamball', passives: ['Musclehead'], gender: 'Female', level: 50 }),
  // A legitimate opposite-gender pair.
  mk({ id: 'c1', species: 'Jormuntide', passives: ['Lunker'], gender: 'Male', level: 50 }),
  mk({ id: 'c2', species: 'Jormuntide', passives: ['Legend'], gender: 'Female', level: 50 }),
];
ctx.__t.state.pals = roster;
const ids = new Set(roster.map(p => p.id));
const res = ctx.searchBreeding(roster, { depth: 1 });
console.log(`synthetic search: ${res.rows.length} rows from ${res.archetypes} archetypes`);

let selfPair = 0, sameGender = 0, unknownId = 0, missingPair = 0;
for (const r of res.rows) {
  if (!r.pair) { missingPair++; continue; }
  const { a, b } = r.pair;
  if (a.id === b.id) selfPair++;
  if (a.gender && b.gender && a.gender === b.gender) sameGender++;
  if (!ids.has(a.id) || !ids.has(b.id)) unknownId++;
}
check('no plan pairs a Pal with itself', selfPair, 0);
check('no plan pairs two same-gender Pals', sameGender, 0);
check('every parent id exists in the roster', unknownId, 0);
check('every returned row resolved to a concrete pair', missingPair, 0);
// The singleton Anubis has no partner of its own species, so Anubis-from-self is
// impossible; any Anubis row must have come from a different-species pair.
const anubisSelf = res.rows.filter(r => r.pair && r.pair.a.id === 'a1' && r.pair.b.id === 'a1');
check('singleton Anubis is never self-bred', anubisSelf.length, 0);

// --- buyable passives are still worth inheriting ----------------------------
// Regression guard for the bug where breeding only ever chased add_pal:false passives,
// so Demon God (+30% Atk / +5% Def, add_pal:true but paid for with a scarce token) could
// never appear in a suggestion no matter how many parents carried it. It must be chased
// in BOTH chip configurations: with premium off it is unbuyable and worth score, with
// premium on it is buyable and worth the token it saves.
check('Demon God is in the chase pool', ctx.__t.CHASE_POOL.has('Demon God'), true);
check('a sub-threshold buyable is not chased', ctx.__t.CHASE_POOL.has('Brave'), false);
for (const n of ctx.__t.UNBUYABLE) {
  if (!ctx.__t.CHASE_POOL.has(n)) fail(`unbuyable ${n} dropped out of the chase pool`);
}

const dgRoster = [
  mk({ id: 'd1', species: 'Anubis', passives: ['Demon God', 'Legend'], gender: 'Male', level: 50 }),
  mk({ id: 'd2', species: 'Anubis', passives: ['Legend'], gender: 'Female', level: 50 }),
];
for (const premium of [false, true]) {
  ctx.__t.state.assume.craft = true;
  ctx.__t.state.assume.premium = premium;
  const r = ctx.searchBreeding(dgRoster, { depth: 1 });
  const dg = r.rows.filter(x => x.inherited.includes('Demon God'));
  if (!dg.length) fail(`no plan inherits Demon God with premium=${premium}`);
  // Every row must still name real, distinct, opposite-gender parents.
  for (const x of dg) {
    if (!x.pair || x.pair.a.id === x.pair.b.id) fail('Demon God row has no valid pair');
  }
  if (premium) {
    // With premium on, inheriting Demon God cannot raise the score (the planner would
    // have bought it), so the ONLY way it can pay is a smaller bill. If this ever ties,
    // the cost plumbing has come undone and the row is pure wasted eggs.
    const same = r.rows.filter(x => !x.inherited.includes('Demon God')
      && Math.abs(x.score - dg[0].score) < 1e-9 && x.species === dg[0].species);
    for (const x of same) {
      if (dg[0].cost >= x.cost) fail('inheriting Demon God did not lower the cost at equal score');
    }
    if (dg[0].tokens >= 2) fail(`inherited Demon God should not still owe ${dg[0].tokens} tokens`);
  }
}
// Restore the chip defaults and the synthetic roster the later tests render from.
ctx.__t.state.assume.craft = false;
ctx.__t.state.assume.premium = false;
ctx.__t.state.pals = roster;

// --- view switching + owner scoping -----------------------------------------
try {
  ctx.__t.state.view = 'breed';  ctx.renderView();
  ctx.__t.state.view = 'roster'; ctx.renderView();
  ctx.__t.state.view = 'nonsense'; ctx.renderView();   // must fall back, not throw
} catch (e) { fail('renderView threw: ' + (e && e.message || e)); }
ctx.__t.state.view = 'roster';

// The owner filter must scope which Pals breeding may use as parents, and must be
// part of the cache key so changing it marks results stale rather than silently
// showing a plan built from a different set of Pals.
const keyBefore = ctx.breedKey();
ctx.__t.activeOwners.add('nobody-owns-this');
const keyAfter = ctx.breedKey();
if (keyBefore === keyAfter) fail('owner filter is not part of the breeding cache key');
check('owner filter scopes the breeding parent pool', ctx.ownerFiltered(ctx.__t.state.pals).length, 0);
ctx.__t.activeOwners.clear();
check('breedKey returns to its original value when owners are cleared', ctx.breedKey(), keyBefore);

// --- render() must never run the search -------------------------------------
const realSearch = ctx.searchBreeding;
let searchCalls = 0;
ctx.searchBreeding = function (...args) { searchCalls++; return realSearch.apply(this, args); };
ctx.render();
check('render() does not run the breeding search', searchCalls, 0);
// Prove the spy actually intercepts, so the check above can't pass vacuously.
ctx.searchBreeding(ctx.__t.state.pals, { depth: 1 });
check('the search spy is wired up', searchCalls, 1);
ctx.searchBreeding = realSearch;

// --- the panel renders without touching the DOM for real --------------------
// Cheap smoke test: every cell renderer must survive a real row, including the
// two-step path cell and the unknown-gender badge.
const searched = ctx.searchBreeding(ctx.__t.state.pals, { depth: 2 });
try {
  ctx.renderBreedChips();
  ctx.__t.breedCache = null;
  ctx.renderBreedPanel();          // empty state
  ctx.__t.breedCache = { key: 'k', rows: searched.rows, ms: searched.ms,
                         archetypes: searched.archetypes, bestOwnedAny: searched.bestOwnedAny };
  ctx.renderBreedPanel();          // populated -> runs renderBreedTable over every row
  console.log(`renderBreedPanel rendered ${searched.rows.length} rows (incl. 2-step paths)`);
} catch (e) { fail('renderBreedPanel threw: ' + (e && e.message || e)); }
// Every column must return a string for every row, including 2-step and unknown-gender rows.
try {
  for (const r of searched.rows) {
    for (const c of ctx.__t.BREED_COLUMNS) {
      if (typeof c.cell(r) !== 'string') fail(`column ${c.key} did not return a string`);
    }
  }
} catch (e) { fail('a breeding column renderer threw: ' + (e && e.message || e)); }
ctx.__t.breedCache = null;

// --- performance guard ------------------------------------------------------
// This roster is deliberately HARSHER than a real one: species and passives are drawn
// uniformly, so unbuyable passives show up ~4x more often than in the game and roughly
// twice as many archetypes carry one (~1070 groups vs ~580 for the real 2,330-Pal
// roster, which runs ~1.4s / ~2.7s). So these budgets are not a performance target --
// they exist to catch an order-of-magnitude blowup, e.g. the archetype key becoming the
// full passive set, which takes the pair count from ~125k to ~2.1M. Keep them loose
// enough not to flake on a busy machine.
const species = Object.keys(ctx.__t.PALS_DB);
const passives = Object.keys(ctx.__t.PASSIVES_DB);
const rnd = (() => { let s = 42; return () => (s = (s * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff; })();
const big = [];
for (let i = 0; i < 2330; i++) {
  const n = Math.floor(rnd() * 5);
  const ps = [];
  for (let j = 0; j < n; j++) ps.push(passives[Math.floor(rnd() * passives.length)]);
  big.push(mk({
    id: 'g' + i, species: species[Math.floor(rnd() * species.length)],
    passives: ps, gender: rnd() < 0.5 ? 'Male' : 'Female',
    level: 1 + Math.floor(rnd() * 80),
    ivHp: Math.floor(rnd() * 101), ivAtk: Math.floor(rnd() * 101), ivDef: Math.floor(rnd() * 101),
  }));
}
ctx.__t.state.pals = big;
let t = Date.now();
const r1 = ctx.searchBreeding(big, { depth: 1 });
const ms1 = Date.now() - t;
console.log(`depth 1 on ${big.length} Pals: ${ms1} ms, ${r1.archetypes} archetypes, ${r1.rows.length} rows`);
if (ms1 > 9000) fail(`depth-1 search too slow: ${ms1} ms (budget 9000 on the harsh synthetic roster)`);

t = Date.now();
const r2 = ctx.searchBreeding(big, { depth: 2 });
const ms2 = Date.now() - t;
console.log(`depth 2 on ${big.length} Pals: ${ms2} ms, ${r2.rows.length} rows`);
if (ms2 > 25000) fail(`depth-2 search too slow: ${ms2} ms (budget 25000 on the harsh synthetic roster)`);

// Same invariants must hold at scale and at depth 2.
let bad2 = 0;
for (const r of r2.rows) {
  if (!r.pair) { bad2++; continue; }
  if (r.pair.a.id === r.pair.b.id) bad2++;
  else if (r.pair.a.gender && r.pair.b.gender && r.pair.a.gender === r.pair.b.gender) bad2++;
}
check('depth-2 rows keep the pair invariants', bad2, 0);

// Both purchase chips ON is the slowest configuration, not the default one the runs
// above use: planPassives() runs its widest candidate walk there, and every extra chased
// passive is another distinct `inherited` set to plan for (~47k calls, ~16.5k of them
// cache misses). Measure it explicitly so a regression cannot hide behind a chips-off run.
//
// This roster is much harsher than a real one for THIS config in particular: passives are
// drawn uniformly from all 115, so the common buyables the chase pool now includes are
// ~4x over-represented. The real 2,330-Pal roster runs ~3.4 s here. The budget is set to
// catch an order-of-magnitude regression, not to hold the current number.
ctx.__t.state.assume.craft = true;
ctx.__t.state.assume.premium = true;
t = Date.now();
const r3 = ctx.searchBreeding(big, { depth: 1 });
const ms3 = Date.now() - t;
console.log(`depth 1, both purchase chips on: ${ms3} ms, ${r3.rows.length} rows`);
if (ms3 > 40000) fail(`depth-1 with purchases too slow: ${ms3} ms (budget 40000)`);
ctx.__t.state.assume.craft = false;
ctx.__t.state.assume.premium = false;

// --- wishlist: acceptProb mirrors the Python ---------------------------------
// p_accept() in breeding_check.py is the lock; this proves the shipped JS agrees with
// it cell for cell, and that the unlimited case still reproduces inheritProb() exactly.
{
  const block = py.match(/ACCEPT_FIXTURE = \[([\s\S]*?)\n\]/);
  if (!block) fail('could not find ACCEPT_FIXTURE in breeding_check.py');
  else {
    const rows = [...block[1].matchAll(/\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)\s*,\s*([\d.]+)\s*\)/g)]
      .map(r => [+r[1], +r[2], +r[3], +r[4]]);
    let bad = 0;
    for (const [m, k, x, expect] of rows) {
      if (Math.abs(ctx.acceptProb(m, k, x) - expect) > 1e-12) bad++;
    }
    check(`acceptProb matches the Python fixture (${rows.length} cases)`, bad, 0);
    if (rows.length < 15) fail(`ACCEPT_FIXTURE is suspiciously small (${rows.length} rows)`);
  }
  let drift = 0;
  for (let m = 0; m <= 12; m++) {
    for (let k = 0; k <= 4; k++) {
      if (Math.abs(ctx.acceptProb(m, k, -1) - ctx.inheritProb(m, k)) > 1e-12) drift++;
    }
  }
  check('acceptProb with unlimited extras IS inheritProb', drift, 0);
  // Being pickier is never easier. This is what makes the junk axis a real tradeoff
  // rather than a free win, so it has to hold everywhere.
  let mono = 0;
  for (let m = 0; m <= 12; m++) for (let k = 0; k <= Math.min(m, 4); k++) {
    for (let x = 1; x <= 4; x++) if (ctx.acceptProb(m, k, x) < ctx.acceptProb(m, k, x - 1)) mono++;
  }
  check('acceptProb is non-decreasing in how much junk you tolerate', mono, 0);
}

// --- wishlist: every emitted plan must be real --------------------------------
// The failure mode this guards is "the plan is fiction": a step whose child is not what
// those parents actually produce, a parent used before it exists, a Pal bred with
// itself, or an egg count that does not match the pool it claims to draw from.
function validateWishPlan(res, roster, label) {
  if (!res.plan || !res.order) return;
  const ids = new Set(roster.map(p => p.id));
  const { nodeSpecies, POPCNT } = ctx.__t;
  const seen = new Set();
  let total = 0;
  for (const [i, s] of res.order.entries()) {
    const aSp = nodeSpecies(s.aKey), bSp = nodeSpecies(s.bKey);
    const aMask = ((s.aKey / 5) | 0) & 15, aJ = s.aKey % 5;
    const bMask = ((s.bKey / 5) | 0) & 15, bJ = s.bKey % 5;
    // 1. the child is what the game says those two parents make
    const kids = [ctx.childSpecies(aSp, bSp, 'Male', 'Female'),
                  ctx.childSpecies(aSp, bSp, 'Female', 'Male')];
    if (!kids.includes(s.species)) fail(`${label}: step ${i + 1} claims ${aSp} x ${bSp} -> ${s.species}`);
    // 2. the wanted set comes from the parents, and the pool is the parents' pool
    if (s.mask & ~(aMask | bMask)) fail(`${label}: step ${i + 1} inherits a passive neither parent has`);
    if (s.m !== POPCNT[aMask | bMask] + aJ + bJ) fail(`${label}: step ${i + 1} has the wrong pool size`);
    // 3. the egg count is the one the odds imply
    const p = ctx.acceptProb(s.m, POPCNT[s.mask], s.j);
    if (!(p > 0) || Math.abs(s.eggs - 1 / p) > 1e-9)
      fail(`${label}: step ${i + 1} egg count ${s.eggs} does not match acceptProb`);
    // 4. parents exist before they are used, and each step is built exactly once
    if (s.aBred && !seen.has(s.aKey)) fail(`${label}: step ${i + 1} uses an unbuilt parent`);
    if (s.bBred && !seen.has(s.bKey)) fail(`${label}: step ${i + 1} uses an unbuilt parent`);
    if (seen.has(s.key)) fail(`${label}: step ${i + 1} builds the same node twice`);
    seen.add(s.key);
    // 5. named Pals are real, distinct, and can actually breed
    for (const [key, bred, entry, sp] of [[s.aKey, s.aBred, s.aEntry, aSp], [s.bKey, s.bBred, s.bEntry, bSp]]) {
      if (bred) { if (entry) fail(`${label}: a bred parent also names a roster Pal`); continue; }
      if (!entry) { fail(`${label}: step ${i + 1} has an unbred parent with no Pal behind it`); continue; }
      if (!ids.has(entry.id)) fail(`${label}: step ${i + 1} names Pal ${entry.id}, not in the roster`);
      if (entry.species !== sp) fail(`${label}: step ${i + 1} names a ${entry.species} where a ${sp} is needed`);
    }
    if (s.aEntry && s.bEntry) {
      if (s.aEntry.id === s.bEntry.id) fail(`${label}: step ${i + 1} breeds a Pal with itself`);
      else if (s.aEntry.gender && s.bEntry.gender && s.aEntry.gender === s.bEntry.gender)
        fail(`${label}: step ${i + 1} breeds two ${s.aEntry.gender}s`);
    }
    total += ctx.stepEggs(s);
  }
  // 6. the headline is the sum of the steps, and the last step is the wish
  if (Math.abs(total - res.eggs) > 1e-6) fail(`${label}: total ${res.eggs} != sum of steps ${total}`);
  if (res.order.length !== res.plan.steps.size)
    fail(`${label}: ${res.plan.steps.size} steps but only ${res.order.length} in the build order`);
  if (res.order.length) {
    const last = res.order[res.order.length - 1];
    if (last.species !== res.target) fail(`${label}: the plan does not end at ${res.target}`);
    const bredWanted = res.split.bred.length;
    if (ctx.__t.POPCNT[last.mask] !== bredWanted)
      fail(`${label}: the final Pal does not carry all ${bredWanted} bred passives`);
  }
}

// --- wishlist: junk is a price, not a wall -----------------------------------
// The load-bearing case. The only Legend carrier is filthy, and using it dirty costs 4
// eggs while cleaning it first costs ~20. An implementation that insists intermediates
// be junk-free returns the expensive answer -- and quotes 20 eggs for a 4-egg job.
{
  const A = 'Frostallion', B = 'Foxparks';
  const C = ctx.childSpecies(A, B, 'Male', 'Female');
  const dirty = [
    mk({ id: 'w1', species: A, passives: ['Legend', 'Clumsy', 'Pyromaniac'], gender: 'Female', level: 50 }),
    mk({ id: 'w2', species: B, passives: ['Demon God'], gender: 'Male', level: 50 }),
  ];
  const res = ctx.wishSolve(dirty, { species: C, passives: ['Legend', 'Demon God'] }, {});
  check('a dirty carrier is usable, not a dead end', !!res.plan, true);
  if (res.plan) {
    check('the dirty carrier is used directly, in one step', res.order.length, 1);
    check('...for 4.0 eggs, not the ~20 of cleaning it first', Math.round(res.eggs * 10) / 10, 4);
    check('...and the search proves it optimal', res.status, 'converged');
    validateWishPlan(res, dirty, 'junk case');
  }
  // Both wanted passives are unbuyable, so neither may be quietly bought instead.
  check('unbuyable passives are bred, not bought', res.split.buy.length, 0);
}

// --- wishlist: the 50k passives are bought, never bred ------------------------
{
  const s = ctx.wishSplit(['Legend', 'Demon God', 'Musclehead', 'Ferocious']);
  check('rank 1-3 add_pal passives are bought', s.buy.join(','), 'Musclehead,Ferocious');
  check('rank 4 and unbuyable passives are bred', s.bred.join(','), 'Legend,Demon God');
  check('an unknown passive is reported, not silently dropped',
        ctx.wishSplit(['Not A Passive']).unknown.length, 1);
}

// --- wishlist: blocked wishes explain themselves ------------------------------
{
  const tiny = [mk({ id: 'x1', species: 'Lamball', passives: [], gender: 'Male', level: 1 })];
  const r1 = ctx.wishSolve(tiny, { species: 'Anubis', passives: ['Legend'] }, {});
  check('a passive nobody carries blocks the wish', !!r1.blocked, true);
  if (r1.blocked && !r1.blocked.includes('Legend')) fail('the block does not name the missing passive');
  // Frostallion is never the child of two different species, so it can only come from
  // two Frostallions -- and that has to be said instantly, not after the full budget.
  // The carrier is present here, so this exercises the species rule and not the
  // missing-passive rule above it.
  // Both passives are carried by SOMETHING, and no single Frostallion has both, so the
  // only rule left is "two Frostallions" -- exactly what the message has to say.
  const lone = [
    mk({ id: 'x2', species: 'Frostallion', passives: ['Legend'], gender: 'Male', level: 50 }),
    mk({ id: 'x3', species: 'Lamball', passives: ['Lucky'], gender: 'Female', level: 50 }),
  ];
  const t0 = Date.now();
  const r2 = ctx.wishSolve(lone, { species: 'Frostallion', passives: ['Legend', 'Lucky'] }, {});
  const dt = Date.now() - t0;
  check('a self-only species blocks with an explanation', !!r2.blocked, true);
  if (r2.blocked && !/two different species/.test(r2.blocked))
    fail('the self-only block does not explain why');
  if (dt > 2000) fail(`self-only block took ${dt} ms; it must not burn the whole budget`);

  // Already in the box: the honest answer is "do nothing", not a breeding plan.
  const have = [mk({ id: 'h1', species: 'Anubis', passives: ['Legend', 'Musclehead'], gender: 'Male', level: 50 })];
  const r3 = ctx.wishSolve(have, { species: 'Anubis', passives: ['Legend', 'Musclehead'] }, {});
  check('a wish you already satisfy costs nothing', r3.eggs, 0);
  check('...and names the Pal', r3.have && r3.have.id, 'h1');
}

// --- wishlist: real plans on the synthetic roster ------------------------------
// `big` is the harsh uniform roster built above: every species, passives drawn flat.
{
  ctx.__t.state.pals = big;
  const wishes = [
    { species: 'Anubis', passives: ['Legend', 'Demon God', 'Musclehead', 'Ferocious'] },
    { species: 'Lamball', passives: ['Lucky'] },
    { species: 'Mammorest', passives: ['Legend', 'Lucky', 'Idiosyncratic'] },
    { species: 'Chikipi', passives: ['Legend', 'Musclehead'] },
    { species: 'Jormuntide Ignis', passives: ['Lucky', 'Burly Body'] },
    { species: 'Blazehowl', passives: ['Legend', 'Lucky', 'Demon God', 'Ferocious'] },
  ];
  for (const w of wishes) {
    const t0 = Date.now();
    const res = ctx.wishSolve(big, w, { budgetMs: 4000 });
    const dt = Date.now() - t0;
    const label = `${w.species} [${w.passives.join(', ')}]`;
    // Anytime means anytime: overshooting the budget by more than a round is a bug,
    // because the page is blocking a spinner on it.
    if (dt > 12000) fail(`${label}: took ${dt} ms against a 4000 ms budget`);
    if (res.blocked) { console.log(`  wish ${label}: blocked (${res.blocked.slice(0, 60)}...)`); continue; }
    console.log(`  wish ${label}: ${res.eggs.toFixed(1)} eggs, ${res.order.length} steps, `
      + `${res.status}, ${dt} ms`);
    validateWishPlan(res, big, label);
  }
}

// --- wishlist: the clean-partner pre-pass obeys the gender rules ---------------
// Caught by fuzzing 120 random wishes against the real roster: the pre-pass that works
// out the cheapest passive-free partner of each species did not check that a pair had
// one of each gender, so it could hand the search a filler chain nobody can actually
// breed. Phase 2 then failed to name a Pal for that parent and the plan came out with a
// hole in it (6 of 106 plans). Here every clean Pal is male, so no clean partner can be
// bred at all and every step must fall back to Pals that really can pair.
{
  const names = ['Lamball', 'Chikipi', 'Foxparks', 'Pengullet', 'Cattiva', 'Depresso'];
  const allMale = names.map((sp, i) => mk({ id: 'cg' + i, species: sp, passives: [], gender: 'Male', level: 1 }));
  const roster = allMale.concat(
    mk({ id: 'cg9', species: 'Frostallion', passives: ['Legend'], gender: 'Female', level: 50 }));
  let plans = 0;
  for (const target of ['Lamball', 'Mammorest', 'Anubis', 'Chikipi']) {
    const res = ctx.wishSolve(roster, { species: target, passives: ['Legend'] }, { budgetMs: 2500 });
    if (res.blocked) continue;
    plans++;
    validateWishPlan(res, roster, `all-male clean pool -> ${target}`);
    // Nothing in the plan may pair two Pals of the same known gender, at any depth.
    for (const step of res.order) {
      if (step.aEntry && step.bEntry && step.aEntry.gender === step.bEntry.gender)
        fail(`all-male clean pool: ${target} step pairs two ${step.aEntry.gender}s`);
    }
  }
  if (!plans) fail('the all-male clean-pool case produced no plans to check');
}

// --- wishlist: render() must never run the search -----------------------------
{
  const realIter = ctx.wishSolveIter;
  let solveCalls = 0;
  ctx.wishSolveIter = function (...a) { solveCalls++; return realIter.apply(this, a); };
  ctx.__t.state.wishlist = [ctx.normalizeWish({ species: 'Anubis', passives: ['Legend', 'Musclehead'] })];
  ctx.render();
  check('render() does not run the wishlist search', solveCalls, 0);
  ctx.wishSolveIter(big, ctx.__t.state.wishlist[0], { budgetMs: 1 }).next();
  check('the wishlist search spy is wired up', solveCalls, 1);
  ctx.wishSolveIter = realIter;
}

// --- wishlist: the panel renders every kind of result --------------------------
{
  const w = ctx.normalizeWish({ species: 'Anubis', passives: ['Legend', 'Demon God', 'Musclehead'] });
  ctx.__t.state.wishlist = [w];
  const cases = {
    'a solved plan': ctx.wishSolve(big, w, { budgetMs: 3000 }),
    'a blocked wish': ctx.wishSolve([mk({ id: 'z1', species: 'Lamball', passives: [], gender: 'Male', level: 1 })],
      w, { budgetMs: 500 }),
    'an already-owned wish': ctx.wishSolve(
      [mk({ id: 'z2', species: 'Anubis', passives: ['Legend', 'Demon God'], gender: 'Male', level: 50 })],
      w, { budgetMs: 500 }),
  };
  for (const [label, res] of Object.entries(cases)) {
    ctx.__t.wishResults.set(w.id, { stamp: 'x', res });
    try {
      ctx.renderWishlist();
      const html = ctx.wishBody(res);
      if (typeof html !== 'string') fail(`wishBody returned a non-string for ${label}`);
    } catch (e) { fail(`renderWishlist threw on ${label}: ` + (e && e.message || e)); }
  }
  ctx.__t.wishResults.clear();
  ctx.__t.state.wishlist = [];
  // The view must switch without throwing, the same as the other two.
  try { ctx.__t.state.view = 'wishlist'; ctx.renderView(); }
  catch (e) { fail('renderView threw on the wishlist view: ' + (e && e.message || e)); }
  ctx.__t.state.view = 'roster';
}

// --- wishlist: wishes survive a save/load round trip ---------------------------
// load() whitelists what it copies across, so anything added to `state` has to be listed
// there or it saves fine and silently never comes back.
{
  const before = [ctx.normalizeWish({ species: 'Anubis', passives: ['Legend', 'Musclehead'] })];
  ctx.__t.state.wishlist = before;
  ctx.save();
  ctx.__t.state.wishlist = [];
  ctx.load();
  check('wishes survive save/load', JSON.stringify(ctx.__t.state.wishlist), JSON.stringify(before));
  check('a wish with no passives is rejected', ctx.normalizeWish({ species: 'Anubis', passives: [] }), null);
  check('a wish is capped at 4 passives',
        ctx.normalizeWish({ species: 'Anubis', passives: ['a', 'b', 'c', 'd', 'e'] }).passives.length, 4);
  ctx.__t.state.wishlist = [];
}

console.log();
if (failures) { console.error(`${failures} check(s) failed`); process.exit(1); }
console.log('All JS checks passed.');
