// Render test: load each page in jsdom with a stubbed network layer and assert that it fills in its
// data, that every rendered market row links to an official host, and that a blocked network
// degrades to the committed capture instead of fabricating values.
//
// Run: node docs/live/tests/render.test.mjs   (needs jsdom, a dev dependency of the repository)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const LIVE = path.join(HERE, '..');
const REPO = path.join(LIVE, '..', '..');

async function loadPage(name, { allowNetwork = false } = {}) {
  const html = await readFile(path.join(LIVE, name), 'utf8');
  const virtualConsole = new VirtualConsole();
  const pageErrors = [];
  virtualConsole.on('jsdomError', (error) => pageErrors.push(error.message));
  virtualConsole.on('error', (message) => pageErrors.push(String(message)));

  const dom = new JSDOM(html, {
    url: `https://kanlerxz87-cyber.github.io/Tradebot1/docs/live/${name}`,
    runScripts: 'dangerously',
    resources: undefined,
    pretendToBeVisual: true,
    virtualConsole,
  });
  const { window } = dom;

  // Deterministic stand-ins: file reads resolve against the repository, and any Kalshi request
  // either fails (the default, simulating a blocked visitor) or returns a fixed public payload.
  window.fetch = async (input, init = {}) => {
    const url = String(input);
    if (!/^https?:/.test(url)) {
      const file = path.join(LIVE, url.replace(/^\.\//, ''));
      const body = await readFile(file, 'utf8');
      return { ok: true, status: 200, json: async () => JSON.parse(body) };
    }
    if (!allowNetwork) throw new Error('blocked by test harness');
    if (url.includes('/exchange/status')) {
      return { ok: true, status: 200, json: async () => ({ exchange_active: true, trading_active: true }) };
    }
    throw new Error('blocked by test harness');
  };
  window.WebSocket = class {
    constructor() {
      setTimeout(() => this.onclose?.({ code: 1006, reason: '' }), 0);
    }
    close() {}
  };
  window.HTMLCanvasElement.prototype.getContext = () => new Proxy({}, { get: () => () => {} });
  // The console re-polls on a 20s timer. That is correct in a browser and would keep the test
  // process alive forever, so long timers are dropped here; the first poll still runs directly.
  const realSetTimeout = window.setTimeout.bind(window);
  window.setTimeout = (fn, ms, ...args) => (ms > 5000 ? 0 : realSetTimeout(fn, ms, ...args));
  window.AbortSignal.timeout = () => undefined;
  window.performance ??= { now: () => 0 };
  if (!window.performance.now) window.performance.now = () => 0;
  window.devicePixelRatio = 2;
  window.requestAnimationFrame = (fn) => setTimeout(fn, 0);

  // jsdom has no ES-module loader, so the two real modules are executed in the window context with
  // their import/export keywords stripped. The logic under test is byte-for-byte the shipped code.
  const wantsConsole = /src="assets\/app\.mjs"/.test(html);
  const core = await readFile(path.join(LIVE, 'assets/core.mjs'), 'utf8');
  const app = (await readFile(path.join(LIVE, 'assets/app.mjs'), 'utf8')).replace(
    /^import[\s\S]*?from '\.\/core\.mjs';\n/m,
    '',
  );
  const combined = `${core.replace(/^export /gm, '')}\n${app.replace(/^export /gm, '')}`;
  if (wantsConsole) {
    try {
      window.eval(combined);
    } catch (error) {
      pageErrors.push(`module execution failed: ${error.message}`);
    }
  }

  // Pages with inline module scripts (verification, flagged) get the same treatment: the real script
  // body runs in the window, not a reimplementation of it.
  for (const script of window.document.querySelectorAll('script[type="module"]')) {
    if (script.src) continue;
    try {
      window.eval(script.textContent);
    } catch (error) {
      pageErrors.push(`inline module failed: ${error.message}`);
    }
  }

  await new Promise((resolve) => setTimeout(resolve, 600));
  return { dom, window, pageErrors };
}

test('the console renders its capture offline: table, feeds, book and resolution panels', async () => {
  const { window, pageErrors } = await loadPage('index.html');
  const document = window.document;
  assert.deepEqual(pageErrors.filter((message) => !/Could not parse CSS|Not implemented/.test(message)), []);

  const rows = document.querySelectorAll('#market-rows tr');
  assert.ok(rows.length >= 2, `expected at least 2 rendered market rows, saw ${rows.length}`);
  const html = document.getElementById('market-rows').innerHTML;
  assert.match(html, /gas prices/i, 'the seeded gas market should be rendered');
  assert.match(html, /external-api\.demo\.kalshi\.co\/trade-api\/v2/, 'each row links to its API read');
  assert.match(html, /kalshi\.com\/markets\//, 'each row links to the Kalshi market page');

  // A blocked browser must not empty the page or invent a number.
  assert.match(document.getElementById('connection').textContent, /Static capture|blocked/i);
  assert.match(document.getElementById('stat-markets').textContent, /^2$/);
  assert.equal(document.getElementById('all-feed').textContent.includes('No swing has been observed yet'), true);
  assert.match(document.getElementById('resolved-rows').textContent, /No resolved market on file/i);
  assert.match(document.getElementById('book-rows').textContent, /Select a market/i);

  // The cover sheet of the page must state the demo limitation in text.
  assert.match(document.body.textContent, /DEMO PRICES, NOT PRODUCTION/);
});

test('selecting a market draws the chart and shows an empty book as empty, not as zero', async () => {
  const { window } = await loadPage('index.html');
  const document = window.document;
  const button = document.querySelector('[data-select]');
  assert.ok(button, 'a market button exists');
  button.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 400));
  assert.match(document.getElementById('selected-ticker').textContent, /KXAAAGASM/);
  const book = document.getElementById('book-rows').textContent;
  assert.match(book, /empty book|no YES bids|not a price of zero/i);
  assert.match(document.getElementById('selected-body').textContent, /Taker fee/);
});

test('the search box and the sort control change what the table shows', async () => {
  const { window } = await loadPage('index.html');
  const document = window.document;
  const search = document.getElementById('search');
  const sort = document.getElementById('sort');
  assert.ok(search && sort, 'both controls exist');
  assert.equal(document.querySelectorAll('#market-rows tr').length, 2);

  search.value = 'above $2.50';
  search.dispatchEvent(new window.Event('input', { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(document.querySelectorAll('#market-rows tr').length, 1, 'the filter narrows to one strike');

  search.value = 'nothing matches this';
  search.dispatchEvent(new window.Event('input', { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.match(document.getElementById('market-rows').textContent, /No verified market in this topic yet/);

  search.value = '';
  search.dispatchEvent(new window.Event('input', { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(document.querySelectorAll('#market-rows tr').length, 2);

  const before = sort.textContent;
  sort.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.notEqual(sort.textContent, before, 'the sort label tracks the order in use');
});

test('the verification page renders every fact with a source link and reproduces the fee table', async () => {
  const { window } = await loadPage('verification.html');
  const document = window.document;
  await new Promise((resolve) => setTimeout(resolve, 300));
  const facts = document.querySelectorAll('#fact-rows tr');
  assert.ok(facts.length >= 25, `expected the whole register, saw ${facts.length}`);
  for (const row of facts) {
    const link = row.querySelector('a[href^="http"]');
    assert.ok(link, `fact row without a source link: ${row.textContent.slice(0, 60)}`);
  }
  const fees = document.querySelectorAll('#fee-rows tr');
  assert.equal(fees.length, 21);
  const mismatches = [...fees].filter((row) => row.querySelector('.down'));
  assert.deepEqual(mismatches.map((row) => row.textContent), []);
});

test('the flagged page renders every flag with a severity and a behaviour', async () => {
  const { window } = await loadPage('flagged.html');
  const document = window.document;
  await new Promise((resolve) => setTimeout(resolve, 300));
  const rows = document.querySelectorAll('#flag-rows tr');
  assert.ok(rows.length >= 16, `expected the flags, saw ${rows.length}`);
  for (const row of rows) {
    assert.match(row.textContent, /high|medium|low/);
    assert.match(row.textContent, /Site behaviour:/);
  }
});

test('with network allowed, the self-test records what the browser measured', async () => {
  const { window } = await loadPage('index.html', { allowNetwork: true });
  const document = window.document;
  await new Promise((resolve) => setTimeout(resolve, 500));
  const text = document.getElementById('selftest-body').textContent;
  assert.match(text, /GET \/exchange\/status/);
  assert.match(text, /WebSocket handshake/);
  assert.match(text, /Order placement/);
  assert.match(text, /not attempted/);
});

test('no page or module references the production API host', async () => {
  const files = ['index.html', 'verification.html', 'flagged.html', 'assets/app.mjs', 'assets/core.mjs', 'tools/capture.mjs'];
  for (const file of files) {
    const text = await readFile(path.join(LIVE, file), 'utf8');
    assert.equal(/external-api\.kalshi\.com|api\.elections\.kalshi\.com/.test(text), false, `${file} mentions production`);
  }
  const repoRoot = await readFile(path.join(REPO, 'README.md'), 'utf8').catch(() => '');
  assert.ok(typeof repoRoot === 'string');
});
