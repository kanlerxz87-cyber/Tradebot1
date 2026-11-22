#!/usr/bin/env node
// Static site generator.
//
// Fills templates/*.tpl from data/snapshot.json, data/sources.json,
// data/flags.json, data/live/*.json and data/account.json, and writes the
// published pages at the repository root and under categories/.
//
//   node scripts/build-site.mjs           # write the site
//   node scripts/build-site.mjs --check   # exit 1 if the committed HTML is stale
//
// Templates are stored with a .tpl extension so the link checker never mistakes
// them for published pages.
//
// Design rules enforced here:
//   * every table row carries a source link; a row without one fails the build
//   * a value that is not in the data is rendered as a dash, never as 0
//   * nothing is written that is not derived from a committed data file

import { readFile, writeFile, mkdir, readdir } from 'node:fs/promises';
import path from 'node:path';
import { existsSync } from 'node:fs';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname);
const TEMPLATES = path.join(ROOT, 'templates');
const CHECK = process.argv.includes('--check');

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const DASH = '—';
const money = (v, d = 2) => (v == null || v === '' || Number.isNaN(Number(v)) ? DASH : `$${Number(v).toFixed(d)}`);
const cents = (v) => (v == null || v === '' || Number.isNaN(Number(v)) ? DASH : `${+(Number(v) * 100).toFixed(2)}¢`);
const num = (v, d = 2) => (v == null || v === '' || Number.isNaN(Number(v)) ? DASH : Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }));
const int = (v) => (v == null || v === '' || Number.isNaN(Number(v)) ? DASH : Math.round(Number(v)).toLocaleString('en-US'));
const pct = (v, d = 1) => (v == null || v === '' || Number.isNaN(Number(v)) ? DASH : `${(Number(v) * 100).toFixed(d)}%`);
const signedMoney = (v, d = 2) => (v == null || v === '' || Number.isNaN(Number(v)) ? DASH : `${Number(v) > 0 ? '+' : Number(v) < 0 ? '−' : ''}$${Math.abs(Number(v)).toFixed(d)}`);
const stamp = (iso) => (!iso ? DASH : new Date(iso).toISOString().replace('T', ' ').slice(0, 16) + 'Z');
const timeOnly = (iso) => (!iso ? DASH : new Date(iso).toISOString().slice(11, 19) + 'Z');
const src = (url, label = 'source') => (url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer nofollow">${esc(label)}</a>` : `<span class="dim">${DASH}</span>`);

export const TOPICS = [
  { id: 'gas', label: 'Gas prices', href: 'categories/gas.html' },
  { id: 'elections', label: 'Elections', href: 'categories/elections.html' },
  { id: 'culture', label: 'Culture', href: 'categories/culture.html' },
  { id: 'crypto', label: 'Crypto', href: 'categories/crypto.html' },
  { id: 'golf', label: 'Golf', href: 'categories/golf.html' },
];

const PAGES = [
  { file: 'board.html', title: 'Live market board', nav: 'Board' },
  { file: 'dashboard.html', title: 'Live alerts', nav: 'Alerts' },
  { file: 'markets.html', title: 'Markets', nav: 'Markets' },
  { file: 'market.html', title: 'Market detail', nav: 'Market' },
  { file: 'portfolio.html', title: 'Simulated portfolio', nav: 'Portfolio' },
  { file: 'strategies.html', title: 'Strategies', nav: 'Strategies' },
  { file: 'demo-account.html', title: 'Demo account', nav: 'Demo account' },
  { file: 'executive-summary.html', title: 'Executive summary', nav: 'Summary' },
  { file: 'sources.html', title: 'Sources', nav: 'Sources' },
  { file: 'methodology.html', title: 'Methodology', nav: 'Method' },
  { file: 'suggestions.html', title: 'Suggestions', nav: 'Ideas' },
  { file: 'flagged.html', title: 'Flagged for review', nav: 'Flagged' },
  { file: 'api.html', title: 'API reference', nav: 'API' },
];

const CATEGORY_FILES = TOPICS.map((t) => ({ file: t.href, title: t.label, nav: t.label, topic: t.id }));

async function main() {
  const [snapshot, sources, flagged, liveState, liveFeed, portfolio, account] = await Promise.all([
    readJson('data/snapshot.json', {}),
    readJson('data/sources.json', {}),
    readJson('data/flags.json', { flags: [] }),
    readJson('data/live/state.json', { tracked: {}, resolutions: {}, coverage: {}, discovery: {} }),
    readJson('data/live/feed.json', { alerts: [], filteredIds: [], runs: [] }),
    readJson('data/live/portfolio.json', { positions: [], summary: {} }),
    readJson('data/account.json', { connected: false }),
  ]);

  const ctx = {
    generatedAt: new Date().toISOString(),
    snapshot, sources, flagged, liveState, liveFeed, portfolio, account,
    buildId: process.env.GITHUB_SHA?.slice(0, 7) ?? 'local',
  };

  const written = [];
  for (const page of [...PAGES, ...CATEGORY_FILES]) {
    const tplName = page.topic ? 'category.tpl' : `${page.file.replace('.html', '')}.tpl`;
    const tplPath = path.join(TEMPLATES, tplName);
    if (!existsSync(tplPath)) { console.warn(`skip ${page.file}: no template ${tplName}`); continue; }
    const tpl = await readFile(tplPath, 'utf8');
    const html = renderLayout(tpl, page, ctx);
    written.push({ file: page.file, html });
  }

  // 404 page
  if (existsSync(path.join(TEMPLATES, '404.tpl'))) {
    const tpl = await readFile(path.join(TEMPLATES, '404.tpl'), 'utf8');
    written.push({ file: '404.html', html: renderLayout(tpl, { file: '404.html', title: 'Not found', nav: '' }, ctx) });
  }

  validate(written, ctx);

  if (CHECK) {
    const stale = [];
    for (const { file, html } of written) {
      const full = path.join(ROOT, file);
      const current = existsSync(full) ? await readFile(full, 'utf8') : '';
      if (normalise(current) !== normalise(html)) stale.push(file);
    }
    if (stale.length) {
      console.error('Stale generated pages:', stale.join(', '));
      process.exit(1);
    }
    console.log(`Site is up to date (${written.length} pages).`);
    return;
  }

  for (const { file, html } of written) {
    const full = path.join(ROOT, file);
    await mkdir(path.dirname(full), { recursive: true });
    await writeFile(full, html);
  }
  console.log(`Wrote ${written.length} pages.`);
}

/** Ignore the generated-at line when comparing, so a no-op rebuild is a no-op. */
function normalise(html) {
  return html.replace(/data-generated="[^"]*"/g, 'data-generated=""');
}

function readJson(rel, fallback) {
  const full = path.join(ROOT, rel);
  if (!existsSync(full)) return Promise.resolve(fallback);
  return readFile(full, 'utf8').then((t) => JSON.parse(t)).catch(() => fallback);
}

/** Wrap a page template in the shared shell: head, header, nav, footer. */
function renderLayout(body, page, ctx) {
  const title = page.title === 'Live market board' ? 'Kalshi demo dashboard' : `${page.title} · Kalshi demo dashboard`;
  const newest = newestObservation(ctx);
  // Category pages live one directory down, so their asset and page links need
  // a prefix. Templates use the [[ASSET]] token for that.
  const prefix = page.file.includes('/') ? '../' : '';

  const rendered = body
    .replaceAll('[[ASSET]]', prefix)
    .replaceAll('[[TITLE]]', esc(page.title))
    .replaceAll('{{TITLE}}', esc(page.title))
    .replaceAll('{{BUILD_ID}}', esc(ctx.buildId))
    .replaceAll('{{GENERATED_AT}}', esc(ctx.generatedAt))
    .replaceAll('{{NEWEST_OBS}}', esc(newest ?? DASH))
    .replaceAll('{{NEWEST_OBS_REL}}', esc(newest ? relative(newest) : DASH));

  const topicLinks = TOPICS.map((t) => `<a href="${prefix}${t.href}">${esc(t.label)}</a>`).join(' · ');

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="A Kalshi demo-environment dashboard: live swing alerts at the $0.10 threshold, price charts and order-book liquidity for gas prices, elections, culture, crypto and golf, with simulated strategies and resolution tracking.">
<meta name="color-scheme" content="dark light">
<link rel="stylesheet" href="${prefix}assets/style.css">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><circle cx='16' cy='16' r='13' fill='%2322c98a'/></svg>">
</head>
<body data-generated="${esc(ctx.generatedAt)}">
<a class="skip" href="#main">Skip to content</a>
<header class="site">
  <div class="wrap site-inner">
    <a class="brand" href="${prefix}board.html"><span class="dot" aria-hidden="true"></span> Tradebot1 <small>Kalshi demo</small></a>
    <nav class="main" aria-label="Main">${navLinks(page)}</nav>
  </div>
</header>
<main id="main" class="wrap page">
${rendered}
</main>
<footer class="site">
  <div class="wrap cols">
    <div style="max-width:52ch">
      <strong>Tradebot1</strong> — a dashboard over the <a href="https://docs.kalshi.com/getting_started/demo_env" target="_blank" rel="noopener noreferrer">Kalshi demo environment</a>.
      Demo markets use mock funds and Kalshi warns their prices may not reflect real markets.
      This is not investment advice and nothing here is a forecast.
      <div class="src" style="margin-top:8px">Data captured through ${esc(ctx.liveState?.root ?? 'the official demo REST API')}.</div>
    </div>
    <div>
      <div><strong class="muted">Topics</strong></div>
      ${topicLinks}
    </div>
    <div>
      <div><strong class="muted">Review</strong></div>
      <a href="${prefix}flagged.html">Flagged for review</a> · <a href="${prefix}sources.html">Sources</a> · <a href="${prefix}methodology.html">Method</a>
      <div class="src" style="margin-top:8px">Newest observation: ${esc(newest ? `${stamp(newest)} (${relative(newest)})` : DASH)}</div>
    </div>
  </div>
</footer>
</body>
</html>`;
}

/** Links for the header, relative to the current page's depth. */
function navLinks(page) {
  const prefix = page.file.includes('/') ? '../' : '';
  return PAGES.filter((p) => p.nav !== 'Market').map((p) => {
    const active = p.file === page.file ? ' aria-current="page"' : '';
    return `<a href="${prefix}${p.file}"${active}>${esc(p.nav)}</a>`;
  }).join('');
}

function newestObservation(ctx) {
  const fromFeed = (ctx.liveFeed?.alerts ?? [])[0]?.observedAt;
  const tracked = Object.values(ctx.liveState?.tracked ?? {}).map((t) => t?.observedAt).filter(Boolean).sort().pop();
  const snap = ctx.snapshot?.meta?.capturedAt;
  return [fromFeed, tracked, snap].filter(Boolean).sort().pop() ?? null;
}

function relative(iso) {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/**
 * Publication gate. These are hard failures, not warnings: publishing a row
 * with no source is exactly the failure mode this project must not have.
 */
function validate(written, ctx) {
  const problems = [];
  let commentaryRows = 0;
  for (const { file, html } of written) {
    if (!html.includes('<!doctype html>')) problems.push(`${file}: missing doctype`);
    if (/undefined|NaN|\[object Object\]/.test(html.replace(/<script[\s\S]*?<\/script>/g, ''))) {
      problems.push(`${file}: rendered an undefined/NaN/[object Object] value`);
    }
    // Source gate.
    //
    // Every table is checked. A table marked data-check="rows" is a data table:
    // every non-placeholder row must carry a link. A table marked
    // data-nosource="true" is commentary (project rules, ideas, definitions) and
    // is allowed to cite prose instead of a URL - but the count is reported so
    // exemptions stay visible rather than silent. Anything unmarked is treated
    // as a data table, so a new table cannot opt out by accident.
    const tables = html.match(/<table[\s\S]*?<\/table>/g) ?? [];
    for (const table of tables) {
      const commentary = table.includes('data-nosource="true"');
      const rows = table.match(/<tr[^>]*>[\s\S]*?<\/tr>/g) ?? [];
      let exempted = 0;
      for (const row of rows) {
        if (row.includes('<th')) continue;
        if (/class="empty"/.test(row)) continue;
        if (/<a [^>]*href=/.test(row)) continue;
        if (commentary) { exempted += 1; continue; }
        problems.push(`${file}: a table row has no source link: ${row.replace(/\s+/g, ' ').slice(0, 140)}`);
      }
      if (exempted) commentaryRows += exempted;
    }
  }
  if (commentaryRows) console.log(`Note: ${commentaryRows} commentary rows exempted from the source gate (tables marked data-nosource).`);
  if (problems.length) {
    console.error('Publication gate failed:\n - ' + problems.slice(0, 20).join('\n - '));
    process.exitCode = 1;
    throw new Error('refusing to publish');
  }
}

// Helpers exposed to templates through simple {{TOKEN}} replacement plus a
// small set of generated fragments.
export { esc, money, cents, num, int, pct, signedMoney, stamp, timeOnly, src, DASH, ROOT };

main().catch((err) => {
  if (err.message !== 'refusing to publish') console.error(err);
  process.exitCode = 1;
});
