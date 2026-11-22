#!/usr/bin/env node
// Headless render check with jsdom.
//
// Loads each published page the way a browser would, runs its module scripts
// against the committed data files, and asserts that the page actually filled
// in its content: no "Loading…" left behind, no undefined/NaN in the output,
// no unhandled script error, and every data row still carrying a source link.
//
// Node's fetch is served from the local filesystem so the pages read the same
// files a browser would, and any outbound request is refused - this test never
// touches the network.
//
// Run: node scripts/check-render.mjs

import { JSDOM, VirtualConsole } from 'jsdom';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { existsSync } from 'node:fs';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname);

const PAGES = [
  { file: 'board.html', expectText: ['Highest dollar live events'], expectRows: '#rank-table tbody tr' },
  { file: 'dashboard.html', expectText: ['All swings'], expectRows: '#obs-table tbody tr' },
  { file: 'markets.html', expectText: ['Markets'], expectRows: null },
  { file: 'market.html?t=KXELONMARS-99', expectText: ['Liquidity'], expectRows: '#ladder-yes tr' },
  { file: 'portfolio.html', expectText: ['Simulated portfolio'], expectRows: null },
  { file: 'strategies.html', expectText: ['Momentum'], expectRows: null },
  { file: 'demo-account.html', expectText: ['demo account'], expectRows: null },
  { file: 'executive-summary.html', expectText: ['Executive summary'], expectRows: null },
  { file: 'sources.html', expectText: ['Sources'], expectRows: '#docs-table tbody tr' },
  { file: 'methodology.html', expectText: ['Methodology'], expectRows: null },
  { file: 'suggestions.html', expectText: ['Suggestions'], expectRows: null },
  { file: 'flagged.html', expectText: ['Flagged for review'], expectRows: null },
  { file: 'api.html', expectText: ['Base URLs'], expectRows: null },
  { file: 'categories/crypto.html', expectText: ['Crypto'], expectRows: '#discovery-table tbody tr' },
  { file: 'categories/golf.html', expectText: ['Golf'], expectRows: '#discovery-table tbody tr' },
];

let failures = 0;
function fail(msg) { console.error(`✗ ${msg}`); failures += 1; }
function pass(msg) { console.log(`✓ ${msg}`); }

/** A fetch that resolves site-relative paths from disk and refuses the network. */
async function localFetch(input, init) {
  const url = String(input);
  // Same-origin reads (the committed data files) are served from disk, exactly
  // as a static host would serve them.
  const origin = globalThis.window?.location?.origin ?? 'https://example.test';
  if (url.startsWith(origin + '/')) {
    const rel = url.slice(origin.length + 1);
    const clean = rel.split('?')[0].split('#')[0];
    const full = path.join(ROOT, clean);
    if (!existsSync(full)) return { ok: false, status: 404, text: async () => '', json: async () => ({}) };
    const text = await readFile(full, 'utf8');
    return { ok: true, status: 200, url, text: async () => text, json: async () => JSON.parse(text), headers: { get: () => 'application/json' } };
  }
  if (/^https?:\/\//.test(url) && !url.startsWith('file:')) {
    // The pages probe the Kalshi demo API first. Refusing it exercises the
    // snapshot fallback, which is the path most visitors will take.
    throw new TypeError(`network disabled in this test: ${url}`);
  }
  const clean = url.replace(/^file:\/\//, '').split('?')[0].split('#')[0];
  const full = path.isAbsolute(clean) ? clean : path.join(ROOT, clean);
  if (!existsSync(full)) {
    return { ok: false, status: 404, text: async () => '', json: async () => ({}) };
  }
  const text = await readFile(full, 'utf8');
  return {
    ok: true, status: 200, url,
    text: async () => text,
    json: async () => JSON.parse(text),
    headers: { get: () => 'application/json' },
  };
}

async function runPage(entry) {
  const [file, query = ''] = entry.file.split('?');
  const html = await readFile(path.join(ROOT, file), 'utf8');
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', (e) => errors.push(e.message));
  vc.on('error', (e) => errors.push(String(e)));

  const url = `https://example.test/${file}${query ? `?${query}` : ''}`;
  const dom = new JSDOM(html, {
    url,
    runScripts: 'dangerously',
    resources: undefined, // do not fetch external resources; modules are injected below
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      window.fetch = localFetch;
      window.HTMLCanvasElement.prototype.getContext = function getContext() {
        // A recording 2D context: enough for the chart code, and it lets the
        // test assert that something was actually drawn.
        const calls = [];
        const handler = {
          get(_t, prop) {
            if (prop === '__calls') return calls;
            if (prop === 'canvas') return this;
            return (...args) => { calls.push([prop, ...args]); return undefined; };
          },
          set() { return true; },
        };
        return new Proxy({}, handler);
      };
      window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
      // The pages refresh on a timer. In a test the timer would keep the process
      // alive forever, so it is recorded and never fired.
      const intervals = [];
      window.setInterval = (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; };
      window.clearInterval = () => {};
    },
  });

  const { window } = dom;

  // Node imports the page modules into the process, not into jsdom's realm, so
  // the browser globals they expect have to be installed here. These pages are
  // run one at a time, so a single global set per page is enough.
  globalThis.window = window;
  globalThis.document = window.document;
  Object.defineProperty(globalThis, 'location', { value: window.location, configurable: true, writable: true });
  globalThis.fetch = localFetch;
  globalThis.devicePixelRatio = 1;
  globalThis.requestAnimationFrame = window.requestAnimationFrame;
  globalThis.HTMLCanvasElement = window.HTMLCanvasElement;

  // Execute the page's own module scripts in document order. jsdom does not run
  // type="module" scripts, so they are imported here.
  const scripts = [...window.document.querySelectorAll('script[type="module"]')].map((s) => s.getAttribute('src'));
  for (const src of scripts) {
    const resolved = path.resolve(ROOT, path.dirname(file), src.replace(/^https?:\/\/[^/]+\//, ''));
    if (!existsSync(resolved)) { fail(`${entry.file}: missing script ${src}`); continue; }
    try {
      await import(`${resolved}?v=${Date.now()}-${Math.random()}`).catch(async (err) => {
        // Modules reference `window`/`document`; give them the jsdom globals.
        throw err;
      });
    } catch (err) {
      fail(`${entry.file}: script ${src} threw: ${err.message}`);
    }
  }

  // Give promise chains a turn to settle.
  await new Promise((r) => setTimeout(r, 350));

  const text = window.document.body.textContent ?? '';
  for (const needle of entry.expectText) {
    if (!text.includes(needle)) fail(`${entry.file}: expected text "${needle}" not rendered`);
  }
  if (/Loading…/.test(text)) fail(`${entry.file}: left a "Loading…" placeholder on the page`);
  if (/undefined|NaN|\[object Object\]/.test(text)) fail(`${entry.file}: rendered undefined/NaN/[object Object]`);
  if (errors.length) fail(`${entry.file}: script errors: ${errors.slice(0, 2).join(' | ')}`);

  if (entry.expectRows) {
    const rows = window.document.querySelectorAll(entry.expectRows);
    if (!rows.length) fail(`${entry.file}: expected rows in ${entry.expectRows}, found none`);
    else {
      let withoutLink = 0;
      let dataRows = 0;
      for (const row of rows) {
        // A placeholder row says "nothing here yet" and is marked as such by the
        // page; only real data rows are required to carry a source link.
        if (row.getAttribute('data-nosource') === 'true' || row.classList.contains('empty')) continue;
        dataRows += 1;
        if (!row.querySelector('a[href]')) withoutLink += 1;
      }
      if (!dataRows) pass(`${entry.file}: no data rows yet, ${rows.length} placeholder row(s) rendered`);
      if (withoutLink) fail(`${entry.file}: ${withoutLink} of ${rows.length} rendered rows have no source link`);
      else if (dataRows) pass(`${entry.file}: ${dataRows} rows rendered, each with a source link`);
    }
  }

  window.clearInterval = () => {};
  dom.window.close();
  return errors;
}

async function main() {
  for (const entry of PAGES) {
    if (!existsSync(path.join(ROOT, entry.file.split('?')[0]))) { fail(`${entry.file}: not built`); continue; }
    const before = failures;
    await runPage(entry);
    if (failures === before) pass(`${entry.file} renders`);
  }
  if (failures) {
    console.error(`\n${failures} render check(s) failed.`);
    process.exitCode = 1;
  } else {
    console.log('\nAll pages render their data with source links intact.');
  }
}

main().then(() => {
  // Nothing should keep the process alive; exit explicitly so a stray timer in a
  // page module cannot make the test hang.
  process.exit(failures ? 1 : 0);
}).catch((err) => { console.error(err); process.exit(1); });
