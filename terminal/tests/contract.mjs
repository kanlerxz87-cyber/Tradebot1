#!/usr/bin/env node
/* terminal/tests/contract.mjs — the published terminal data must keep its promises.
 *
 * Run by the collector job after every collection, and by CI. It reads the committed
 * files and fails when any of the following stops being true:
 *
 *   1. every alert meets the ≥ $0.10 rule and carries both observation times;
 *   2. every row links the official endpoint it came from;
 *   3. no row names a market outside the five topics, and every row says how it was
 *      classified;
 *   4. prices are inside $0.00–$1.00 and a missing value is null, never 0;
 *   5. the file says where it came from and when, and never claims to be production;
 *   6. the last_prices map (the collector's memory between runs) is not empty when
 *      alerts exist, so a restart cannot silently re-alert everything.
 *
 *   node terminal/tests/contract.mjs            # check the committed files
 *   node terminal/tests/contract.mjs --quiet    # only exit status
 */
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(new URL('../..', import.meta.url).pathname);
const FILES = {
  alerts: path.join(ROOT, 'terminal/data/alerts.json'),
  snapshot: path.join(ROOT, 'terminal/data/snapshot.json'),
};
const FOCUS = new Set(['gas', 'elections', 'culture', 'crypto', 'golf']);
const quiet = process.argv.includes('--quiet');
const problems = [];
const notes = [];

const check = (cond, message) => { if (!cond) problems.push(message); };

function load(file, label) {
  if (!existsSync(file)) return null;
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch (err) {
    problems.push(`${label}: not valid JSON (${err.message})`);
    return null;
  }
}

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const isPrice = (v) => isNum(v) && v >= 0 && v <= 1;

const alerts = load(FILES.alerts, 'alerts.json');
if (alerts === null && !existsSync(FILES.alerts)) {
  notes.push('alerts.json not published yet — the scheduled collector creates it on its first successful run');
} else if (alerts) {
  check(alerts.schema === 'terminal-alerts/1', 'alerts.json: unexpected schema');
  check(typeof alerts.generated_at === 'string' && !Number.isNaN(Date.parse(alerts.generated_at)), 'alerts.json: generated_at must be an ISO timestamp');
  check(alerts.source && /^https:\/\/external-api\.demo\.kalshi\.co\//.test(alerts.source.rest_root || ''), 'alerts.json: source must be the demo root, never production');
  check(!/kalshi\.com\/trade-api/.test(JSON.stringify(alerts.source)), 'alerts.json: a production host must not appear as the source');
  check(Array.isArray(alerts.alerts), 'alerts.json: alerts must be an array');
  for (const [i, a] of (alerts.alerts || []).entries()) {
    const where = `alerts.json[${i}] ${a && a.ticker}`;
    check(!!a && typeof a.ticker === 'string' && a.ticker.length > 0, `${where}: ticker required`);
    check(isNum(a.abs_delta) && a.abs_delta >= 0.1 - 1e-9, `${where}: abs_delta must be ≥ 0.10`);
    check(a.direction === 'up' || a.direction === 'down', `${where}: direction must be up or down`);
    check(isNum(a.from_ts) && isNum(a.to_ts) && a.to_ts > a.from_ts, `${where}: both observation times required, to_ts after from_ts`);
    check(isPrice(a.from_price) && isPrice(a.to_price), `${where}: prices must be inside $0.00–$1.00`);
    check(Math.abs(Math.abs(a.to_price - a.from_price) - a.abs_delta) < 0.005, `${where}: abs_delta must equal |to − from|`);
    check(typeof a.source_url === 'string' && a.source_url.startsWith('https://external-api.demo.kalshi.co/'), `${where}: every row links its official source`);
    check(FOCUS.has(a.topic), `${where}: topic must be one of the five`);
  }
  const hasAlerts = (alerts.alerts || []).length > 0;
  check(!hasAlerts || (alerts.last_prices && Object.keys(alerts.last_prices).length > 0), 'alerts.json: alerts exist but last_prices is empty — the next run would re-alert everything');
}

const snapshot = load(FILES.snapshot, 'snapshot.json');
if (snapshot) {
  check(snapshot.schema === 'terminal-snapshot/1', 'snapshot.json: unexpected schema');
  check(Array.isArray(snapshot.markets), 'snapshot.json: markets must be an array');
  for (const [i, m] of (snapshot.markets || []).entries()) {
    const where = `snapshot.json[${i}] ${m && m.ticker}`;
    check(!!m && typeof m.ticker === 'string' && m.ticker.length > 0, `${where}: ticker required`);
    check(FOCUS.has(m.topic), `${where}: topic must be one of the five`);
    check(typeof m.topic_evidence === 'string' && m.topic_evidence.length > 0, `${where}: every row says how it was classified`);
    check(isPrice(m.price), `${where}: price must be a number inside $0.00–$1.00`);
    check(m.previous_price === null || isPrice(m.previous_price), `${where}: previous_price must be null or a price`);
    check(typeof m.source_url === 'string' && m.source_url.startsWith('https://external-api.demo.kalshi.co/'), `${where}: official source link required`);
    check(m.result === null || m.result === 'yes' || m.result === 'no', `${where}: result must be null, yes or no`);
  }
  check((snapshot.errors || []).length === 0 || (snapshot.markets || []).length > 0, 'snapshot.json: errors with no rows at all — refuse an empty publish');
}

if (!quiet) {
  for (const n of notes) console.log(`note: ${n}`);
  const count = (alerts && alerts.alerts ? alerts.alerts.length : 0);
  const rows = (snapshot && snapshot.markets ? snapshot.markets.length : 0);
  if (problems.length === 0) console.log(`OK: ${count} swing alerts and ${rows} focus-topic rows satisfy the terminal data contract`);
}
if (problems.length) {
  for (const p of problems.slice(0, 40)) console.error(`FAIL: ${p}`);
  if (problems.length > 40) console.error(`… ${problems.length - 40} more`);
  process.exit(1);
}
