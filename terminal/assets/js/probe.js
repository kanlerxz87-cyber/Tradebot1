/* probe.js — run one request against each endpoint the dashboard depends on and report
 * exactly what came back. No retries, no caching, no fallback host except the one the
 * dashboard itself uses (and that is labelled when it happens). */
'use strict';

(function () {
  const $ = (sel) => document.querySelector(sel);

  /* Each probe: a label, the URL, a short "what it means" sentence, and the shape check
     that turns a 200 into a pass (a 200 with the wrong body is still a failure). */
  const PROBES = [
    {
      name: 'Exchange status',
      url: () => `${SITE.demoRest}/exchange/status`,
      docs: 'https://docs.kalshi.com/api-reference/exchange/get-exchange-status',
      means: 'The demo exchange answers and reports whether trading is active.',
      check: (d) => d && (typeof d.trading_active === 'boolean' || typeof d.exchange_active === 'boolean' || d.status),
    },
    {
      name: 'Open events, nested markets',
      url: () => `${SITE.demoRest}/events?status=open&limit=5&with_nested_markets=true`,
      docs: 'https://docs.kalshi.com/api-reference/events/get-events',
      means: 'The exact call the dashboard starts from: five events with their markets embedded.',
      check: (d) => d && Array.isArray(d.events),
    },
    {
      name: 'Open events, no nesting (fallback path)',
      url: () => `${SITE.demoRest}/events?status=open&limit=5`,
      docs: 'https://docs.kalshi.com/api-reference/events/get-events',
      means: 'What the dashboard falls back to when nesting is not returned; markets are then fetched per event.',
      check: (d) => d && Array.isArray(d.events),
    },
    {
      name: 'Markets by event (per-event fallback)',
      url: (ctx) => (ctx.eventTicker ? `${SITE.demoRest}/markets?event_ticker=${encodeURIComponent(ctx.eventTicker)}` : null),
      docs: 'https://docs.kalshi.com/api-reference/market/get-markets',
      means: 'Fetches every market of one event when the nested list was empty.',
      check: (d) => d && Array.isArray(d.markets),
      needs: 'eventTicker',
    },
    {
      name: 'Order book',
      url: (ctx) => (ctx.ticker ? `${SITE.demoRest}/markets/${encodeURIComponent(ctx.ticker)}/orderbook` : null),
      docs: 'https://docs.kalshi.com/getting_started/orderbook_responses',
      means: 'The liquidity ladder: YES/NO bid levels with contract counts.',
      check: (d) => d && (d.orderbook_fp || d.orderbook),
      needs: 'ticker',
    },
    {
      name: 'Candlesticks (1-minute)',
      url: (ctx) => (ctx.series && ctx.ticker
        ? `${SITE.demoRest}/series/${encodeURIComponent(ctx.series)}/markets/${encodeURIComponent(ctx.ticker)}/candlesticks?start_ts=${Math.floor(Date.now() / 1000) - 3600}&end_ts=${Math.floor(Date.now() / 1000)}&period_interval=1`
        : null),
      docs: 'https://docs.kalshi.com/api-reference/market/get-market-candlesticks',
      means: 'The chart history: one-minute candles for the selected contract over the last hour.',
      check: (d) => d && Array.isArray(d.candlesticks),
      needs: 'series',
    },
    {
      name: 'Alternate demo host',
      url: () => `${SITE.demoRestAlt}/exchange/status`,
      docs: 'https://docs.kalshi.com/getting_started/api_environments',
      means: 'The documented alternate demo host, which the client falls back to when the primary fails.',
      check: (d) => d && (typeof d.trading_active === 'boolean' || typeof d.exchange_active === 'boolean' || d.status),
    },
    {
      name: 'Signed portfolio route, unsigned (expected 401)',
      url: () => `${SITE.demoRest}/portfolio/balance`,
      docs: 'https://docs.kalshi.com/api-reference/portfolio/get-balance',
      means: 'Proves the account routes exist and are protected. A 401 here is the correct answer, not a defect.',
      expect401: true,
    },
  ];

  function row(p, res, ms, extra) {
    const ok = p.expect401 ? res.status === 401 : (res.ok && p.check(res.data));
    const cls = ok ? 'ok' : 'err';
    const status = res.status === 0 ? 'network' : String(res.status);
    const detail = res.ok
      ? summarize(p.name, res.data)
      : escapeHtml((res.error || (res.data && (res.data.error || res.data.raw)) || '').toString().slice(0, 160));
    return `<tr>
      <td><strong>${escapeHtml(p.name)}</strong><div class="muted small">${escapeHtml(p.means)}</div></td>
      <td class="small"><a href="${escapeHtml(extra.url || '')}" target="_blank" rel="noopener noreferrer">${escapeHtml(shorten(extra.url || ''))}</a></td>
      <td class="num ${cls}">${escapeHtml(status)}</td>
      <td class="num">${ms}</td>
      <td class="small ${cls}">${ok ? 'PASS' : p.expect401 ? 'unexpected' : 'FAIL'}<div class="muted">${detail}</div></td>
      <td class="small"><a href="${escapeHtml(p.docs)}" target="_blank" rel="noopener noreferrer">endpoint doc ↗</a></td>
    </tr>`;
  }

  function summarize(name, data) {
    try {
      if (name === 'Open events, nested markets' && data.events) {
        const withMarkets = data.events.filter((e) => Array.isArray(e.markets) && e.markets.length);
        return escapeHtml(`${data.events.length} events, ${withMarkets.length} with embedded markets`);
      }
      if (name === 'Open events, no nesting (fallback path)' && data.events) return escapeHtml(`${data.events.length} events`);
      if (name.startsWith('Markets by event') && data.markets) return escapeHtml(`${data.markets.length} markets`);
      if (name === 'Order book') {
        const ob = data.orderbook_fp || data.orderbook || {};
        const yes = (ob.yes_dollars || ob.yes || []).length;
        const no = (ob.no_dollars || ob.no || []).length;
        return escapeHtml(`${yes} YES bid levels, ${no} NO bid levels`);
      }
      if (name.startsWith('Candlesticks') && data.candlesticks) return escapeHtml(`${data.candlesticks.length} candles`);
      return escapeHtml(JSON.stringify(data).slice(0, 120));
    } catch {
      return '';
    }
  }

  const shorten = (u) => u.replace(SITE.demoRest, '…/trade-api/v2').replace(SITE.demoRestAlt, '…demo-api/trade-api/v2');

  async function runAll() {
    const tbody = $('#probeBody');
    const status = $('#probeStatus');
    tbody.innerHTML = '';
    status.textContent = 'Running…';
    const ctx = {};

    for (const p of PROBES) {
      if (p.needs && !ctx[p.needs]) {
        tbody.insertAdjacentHTML('beforeend', `<tr class="empty-row" style="display:table-row"><td colspan="6" class="small muted">${escapeHtml(p.name)} — skipped: needs ${escapeHtml(p.needs)} from an earlier probe, which did not return one.</td></tr>`);
        continue;
      }
      const url = p.url(ctx);
      const started = performance.now();
      const res = await fetchJson(url, {}, 12000);
      const ms = Math.round(performance.now() - started);
      tbody.insertAdjacentHTML('beforeend', row(p, res, ms, { url }));
      /* Seed the context for the dependent probes from what actually came back. */
      if (p.name === 'Open events, nested markets' && res.ok && res.data && res.data.events) {
        const ev = res.data.events.find((e) => Array.isArray(e.markets) && e.markets.length);
        if (ev) {
          ctx.eventTicker = ev.event_ticker;
          const m = ev.markets[0];
          ctx.ticker = m.ticker;
          ctx.series = m.series_ticker || ev.series_ticker;
        }
      }
      if (p.name === 'Signed portfolio route, unsigned (expected 401)' && res.status === 0) {
        tbody.insertAdjacentHTML('beforeend', `<tr><td colspan="6" class="small muted">The signed route could not be reached at all (network), so this row says nothing about authentication. That is the network failure above, not a failure of the account API.</td></tr>`);
      }
    }
    const fails = [...document.querySelectorAll('#probeBody td.err')].length;
    status.textContent = fails === 0
      ? 'All probes passed in this browser. The dashboard should be live.'
      : `${fails} probe${fails === 1 ? '' : 's'} did not pass. Read the “What it means” column on each row; nothing is cached or invented.`;
  }

  document.addEventListener('DOMContentLoaded', () => {
    const btn = $('#probeAll');
    if (btn) btn.addEventListener('click', runAll);
  });
})();
