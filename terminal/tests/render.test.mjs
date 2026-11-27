/* terminal/tests/render.test.mjs — every terminal page is loaded in a real DOM with
 * the network stubbed, and must (a) execute all of its scripts without throwing and
 * (b) render its own static tables. This is the gate that catches a JavaScript error
 * like the one PR #50 had to fix after the site was already live.
 *
 * Network: fetch() is replaced before any module runs, so no test reaches Kalshi. The
 * stub answers the way the documented endpoints answer (empty but well-formed), which
 * exercises the "no data" path every visitor sees if they are offline.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { JSDOM, VirtualConsole } from 'jsdom';
import vm from 'node:vm';

const ROOT = path.resolve(new URL('../..', import.meta.url).pathname);
const PAGE_DIR = path.join(ROOT, 'terminal');

async function pages() {
  const entries = await readdir(PAGE_DIR, { withFileTypes: true });
  return entries.filter((e) => e.isFile() && e.name.endsWith('.html')).map((e) => path.join(PAGE_DIR, e.name));
}

/* A tiny static server so relative <script src> and fetch() work inside jsdom. */
function makeFetch() {
  return async (url) => {
    const u = String(url);
    if (u.includes('/exchange/status')) {
      return { ok: true, status: 200, text: async () => JSON.stringify({ exchange_active: true, trading_active: true }) };
    }
    if (u.includes('/events')) {
      return { ok: true, status: 200, text: async () => JSON.stringify({ events: [], cursor: '' }) };
    }
    if (u.includes('/candlesticks')) {
      return { ok: true, status: 200, text: async () => JSON.stringify({ ticker: 'T', candlesticks: [] }) };
    }
    if (u.includes('/orderbook')) {
      return { ok: true, status: 200, text: async () => JSON.stringify({ orderbook_fp: { yes_dollars: [], no_dollars: [] } }) };
    }
    if (u.includes('data/alerts.json')) {
      return { ok: false, status: 404, text: async () => 'not found' };
    }
    return { ok: false, status: 404, text: async () => 'not found' };
  };
}

test('every terminal page loads, runs its scripts and renders its own tables', async (t) => {
  for (const file of await pages()) {
    await t.test(path.basename(file), async () => {
      const html = await readFile(file, 'utf8');
      const errors = [];
      const vc = new VirtualConsole();
      vc.on('jsdomError', (e) => errors.push(e.message));
      vc.on('error', (e) => errors.push(String(e)));
      const dom = new JSDOM(html, {
        url: 'https://kanlerxz87-cyber.github.io/Tradebot1/terminal/' + path.basename(file),
        runScripts: 'outside-only',
        virtualConsole: vc,
        pretendToBeVisual: true,
      });
      const { window } = dom;
      window.fetch = makeFetch();
      window.HTMLCanvasElement.prototype.getContext = () => null;
      window.confirm = () => false;
      window.close = () => {};
      // Inject the page's own local scripts in order, from disk.
      const srcs = [...dom.window.document.querySelectorAll('script[src]')].map((s) => s.getAttribute('src'));
      /* Classic <script> tags share one global lexical scope in a browser. window.eval
         gives each file its own scope, which would hide `const SITE` from the next
         file, so evaluate in jsdom's actual VM context instead — same semantics as
         the browser. */
      const context = dom.getInternalVMContext();
      for (const src of srcs) {
        assert.ok(!/^https?:/.test(src), `${src} must be a local script`);
        const code = await readFile(path.join(PAGE_DIR, src.replace(/^\.\//, '')), 'utf8');
        vm.runInContext(code, context, { filename: src });
      }
      window.document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));
      // Let the boot promise settle (all fetches are local stubs).
      await new Promise((r) => setTimeout(r, 60));

      assert.deepEqual(errors, [], `${path.basename(file)} raised: ${errors.join(' | ')}`);
      const tables = [...window.document.querySelectorAll('table')];
      assert.ok(tables.length > 0, `${path.basename(file)} renders at least one table`);
      for (const table of tables) {
        const head = table.querySelector('thead');
        if (!head) continue;
        const cols = head.querySelectorAll('th').length;
        for (const row of table.querySelectorAll('tbody tr')) {
          const cells = row.querySelectorAll('td').length;
          if (cells === 1) {
            /* A single full-width cell is the explicit empty/loading state
               (colspan), which is correct markup — only a row that is *not*
               explained must match the header. */
            assert.ok(row.textContent.trim().length > 0, `${path.basename(file)}: a one-cell row must say why it is empty`);
            continue;
          }
          assert.equal(cells, cols, `${path.basename(file)}: a row has ${cells} cells, the header has ${cols}`);
        }
      }
      // The page must never claim live data it did not receive.
      const text = window.document.body.textContent;
      assert.ok(!/undefined|NaN/.test(text), `${path.basename(file)} rendered "undefined" or "NaN"`);
      dom.window.close();
    });
  }
});

test('the dashboard wires its two feeds and the movers board', async () => {
  const html = await readFile(path.join(PAGE_DIR, 'dashboard.html'), 'utf8');
  for (const id of ['feedAll', 'feedModel', 'moversBody', 'marketsBody', 'topicLeaders', 'bidsLadder', 'asksLadder', 'priceChart', 'chartBasis', 'candleInfo']) {
    assert.match(html, new RegExp(`id="${id}"`), `dashboard.html has #${id}`);
  }
  assert.match(html, /assets\/js\/desk\.js/, 'dashboard loads the shared rules module');
});
