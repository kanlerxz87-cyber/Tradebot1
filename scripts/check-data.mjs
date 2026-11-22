#!/usr/bin/env node
// Data contract check.
//
// The site trusts the committed JSON, so the JSON is held to a contract here:
// required fields present, source URLs on official hosts, prices inside 0-1,
// no NaN, every alert's arithmetic consistent with its own endpoints, and every
// simulator position internally balanced.
//
// Run: node scripts/check-data.mjs

import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { existsSync } from 'node:fs';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname);
const OFFICIAL_HOSTS = ['external-api.demo.kalshi.co', 'demo-api.kalshi.co', 'docs.kalshi.com', 'kalshi.com', 'assets.kalshi.com'];

let problems = 0;
function bad(msg) { console.error(`✗ ${msg}`); problems += 1; }
function ok(msg) { console.log(`✓ ${msg}`); }

async function json(rel) {
  const full = path.join(ROOT, rel);
  if (!existsSync(full)) { bad(`${rel}: missing`); return null; }
  try {
    return JSON.parse(await readFile(full, 'utf8'));
  } catch (err) {
    bad(`${rel}: invalid JSON (${err.message})`);
    return null;
  }
}

function isPrice(v) { return typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1; }

function checkNoNaN(value, trail) {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) bad(`${trail}: non-finite number`);
    return;
  }
  if (Array.isArray(value)) { value.forEach((v, i) => checkNoNaN(v, `${trail}[${i}]`)); return; }
  if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) checkNoNaN(v, `${trail}.${k}`);
  }
}

function officialHost(url) {
  try { return OFFICIAL_HOSTS.includes(new URL(url).host); } catch { return false; }
}

async function main() {
  const [snap, sources, flags, feed, state, portfolio, account] = await Promise.all([
    json('data/snapshot.json'), json('data/sources.json'), json('data/flags.json'),
    json('data/live/feed.json'), json('data/live/state.json'), json('data/live/portfolio.json'),
    json('data/account.json'),
  ]);
  if (!snap || !sources || !flags) { process.exit(1); }

  // --- snapshot -------------------------------------------------------------
  let marketRows = 0;
  for (const m of snap.markets ?? []) {
    marketRows += 1;
    if (!m.ticker) bad(`snapshot market without a ticker: ${JSON.stringify(m).slice(0, 60)}`);
    if (!m.sourceUrl) bad(`snapshot market ${m.ticker}: no sourceUrl`);
    else if (!officialHost(m.sourceUrl)) bad(`snapshot market ${m.ticker}: sourceUrl is not an official host`);
    for (const f of ['yesBid', 'yesAsk', 'noBid', 'noAsk', 'lastPrice']) {
      if (m[f] != null && !isPrice(m[f])) bad(`snapshot market ${m.ticker}: ${f} outside 0-1 (${m[f]})`);
    }
  }
  if (!marketRows) bad('snapshot has no markets');
  else ok(`snapshot: ${marketRows} markets, each with an official source URL`);

  for (const s of snap.series ?? []) {
    if (!s.ticker) bad('snapshot series without a ticker');
    if (!s.topic) bad(`snapshot series ${s.ticker}: no topic`);
    if (!s.sourceUrl) bad(`snapshot series ${s.ticker}: no sourceUrl`);
    else if (!officialHost(s.sourceUrl)) bad(`snapshot series ${s.ticker}: sourceUrl is not an official host`);
  }
  ok(`snapshot: ${(snap.series ?? []).length} series routed to topics`);
  if (!snap.meta?.capturedAt) bad('snapshot: no capture time');
  if (!snap.meta?.whatThisIsNot) bad('snapshot: missing the "what this is not" disclaimer');

  // --- sources registry -----------------------------------------------------
  const sourceGroups = ['officialDocs', 'officialApiObservations', 'primaryDataPublishers', 'projectRules'];
  let sourceRows = 0;
  for (const g of sourceGroups) {
    for (const row of sources[g] ?? []) {
      sourceRows += 1;
      if (!row.id) bad(`sources.${g}: a row has no id`);
      if (g !== 'projectRules' && !row.url) bad(`sources.${g} ${row.id}: no url`);
      if (row.url && g !== 'primaryDataPublishers' && !/^https:\/\//.test(row.url)) bad(`sources.${g} ${row.id}: not https`);
    }
  }
  if (!sourceRows) bad('sources registry is empty');
  else ok(`sources: ${sourceRows} rows across ${sourceGroups.length} groups`);

  // Every API observation must point at a demo host.
  for (const row of sources.officialApiObservations ?? []) {
    if (!officialHost(row.url)) bad(`sources ${row.id}: API observation not on an official host`);
    if (!row.url.startsWith('https://external-api.demo.kalshi.co/') && !row.url.startsWith('https://demo-api.kalshi.co/')) {
      bad(`sources ${row.id}: API observation not on a demo host`);
    }
  }
  ok('sources: every API observation is on a demo host');

  // --- flags ----------------------------------------------------------------
  const ids = new Set();
  for (const f of flags.flags ?? []) {
    if (!f.id) bad('a flag has no id');
    if (ids.has(f.id)) bad(`duplicate flag id ${f.id}`);
    ids.add(f.id);
    if (!['high', 'medium', 'low', 'info'].includes(f.severity)) bad(`flag ${f.id}: bad severity ${f.severity}`);
    if (!f.title || !f.detail) bad(`flag ${f.id}: missing title or detail`);
    if (!(f.sources ?? []).length) bad(`flag ${f.id}: no source`);
    for (const s of f.sources ?? []) {
      if (!s.url || !/^https:\/\//.test(s.url)) bad(`flag ${f.id}: source url is not https (${s.url})`);
    }
  }
  ok(`flags: ${(flags.flags ?? []).length} flags, each with at least one https source`);

  // --- feed -----------------------------------------------------------------
  const threshold = feed.threshold;
  if (typeof threshold !== 'number' || Math.abs(threshold - 0.1) > 1e-9) bad(`feed: threshold is ${threshold}, expected 0.1`);
  for (const a of feed.alerts ?? []) {
    if (!a.id) bad('feed: an alert has no id');
    if (!a.marketTicker) bad(`feed ${a.id}: no market ticker`);
    if (!a.sourceUrl && !a.marketUrl) bad(`feed ${a.id}: no source link`);
    for (const f of ['from', 'to', 'delta', 'absDelta']) {
      if (typeof a[f] !== 'number' || !Number.isFinite(a[f])) bad(`feed ${a.id}: ${f} is not a finite number`);
    }
    // Arithmetic must hold: to - from = delta, and abs(delta) = absDelta.
    if (Math.abs((a.to - a.from) - a.delta) > 1e-6) bad(`feed ${a.id}: to - from != delta`);
    if (Math.abs(Math.abs(a.delta) - a.absDelta) > 1e-6) bad(`feed ${a.id}: |delta| != absDelta`);
    if (a.absDelta < threshold - 1e-9) bad(`feed ${a.id}: records a swing below the threshold`);
    if (a.direction && a.direction !== (a.delta > 0 ? 'up' : a.delta < 0 ? 'down' : 'flat')) bad(`feed ${a.id}: direction disagrees with delta`);
    if (a.isDemoExample && feed.filteredIds?.includes(a.id)) bad(`feed ${a.id}: a worked example must not be in the filtered feed`);
  }
  // Every filtered id must exist in the alerts.
  const alertIds = new Set((feed.alerts ?? []).map((a) => a.id));
  for (const id of feed.filteredIds ?? []) if (!alertIds.has(id)) bad(`feed: filteredIds contains ${id}, which is not an alert`);
  ok(`feed: ${(feed.alerts ?? []).length} alerts, arithmetic and threshold consistent`);

  // --- state ----------------------------------------------------------------
  if (state.marketCount != null && state.tracked) {
    // tracked is a map; marketCount counts this cycle, so they are not required to match.
  }
  for (const [ticker, t] of Object.entries(state.tracked ?? {})) {
    if (t.marketTicker !== ticker) bad(`state.tracked[${ticker}]: marketTicker mismatch`);
    for (const h of t.history ?? []) {
      if (!h.t) bad(`state.tracked[${ticker}]: history point with no time`);
      if (h.mid != null && !isPrice(h.mid)) bad(`state.tracked[${ticker}]: history mid outside 0-1`);
    }
  }
  for (const [ticker, r] of Object.entries(state.resolutions ?? {})) {
    if (r.ticker !== ticker) bad(`state.resolutions[${ticker}]: ticker mismatch`);
    if (r.result && !['yes', 'no', 'scalar', ''].includes(r.result)) bad(`state.resolutions[${ticker}]: unexpected result ${r.result}`);
  }
  ok(`state: ${Object.keys(state.tracked ?? {}).length} tracked markets, ${Object.keys(state.resolutions ?? {}).length} resolutions`);

  // --- portfolio ------------------------------------------------------------
  let positions = 0;
  for (const p of portfolio.positions ?? []) {
    positions += 1;
    if (!(p.contracts > 0)) bad(`portfolio ${p.ticker}: non-positive contracts`);
    if (!isPrice(p.entryPrice)) bad(`portfolio ${p.ticker}: entry price outside 0-1`);
    if (!['yes', 'no'].includes(p.side)) bad(`portfolio ${p.ticker}: side must be yes or no`);
    const expectedCost = Math.round(p.contracts * p.entryPrice * 100) / 100;
    if (Math.abs(expectedCost - p.entryCost) > 0.011) bad(`portfolio ${p.ticker}: cost ${p.entryCost} != contracts*price ${expectedCost}`);
    if (p.entryFee == null || p.entryFee < 0) bad(`portfolio ${p.ticker}: no fee recorded`);
    if (p.status === 'settled' && p.realizedPnl == null) bad(`portfolio ${p.ticker}: settled without a P&L`);
  }
  ok(`portfolio: ${positions} positions, each internally balanced`);

  // --- account --------------------------------------------------------------
  if (account.connected === false) {
    if (!account.reason) bad('account: disconnected without a reason');
    if (!account.howToConnect?.length) bad('account: disconnected without instructions');
    if (account.balance != null) bad('account: disconnected but carries a balance');
    ok('account: disconnected, with a reason and no invented balance');
  } else if (account.connected === true) {
    if (!account.balance) bad('account: connected but no balance');
    if (!account.checkedAt) bad('account: connected but no capture time');
    ok('account: connected snapshot present');
  } else {
    bad('account: connected flag is neither true nor false');
  }

  for (const [name, obj] of [['snapshot', snap], ['sources', sources], ['flags', flags], ['feed', feed], ['state', state], ['portfolio', portfolio], ['account', account]]) {
    checkNoNaN(obj, name);
  }

  if (problems) {
    console.error(`\n${problems} data contract problem(s).`);
    process.exitCode = 1;
  } else {
    console.log('\nAll committed data satisfies its contract.');
  }
}

main().catch((err) => { console.error(err); process.exitCode = 1; });
