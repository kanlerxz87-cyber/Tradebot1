/* index.js — landing page live strip. Best-effort; falls back to em dashes. */
'use strict';

(function () {
  const $ = (sel) => document.querySelector(sel);

  async function pingExchange() {
    const res = await Kalshi.getExchangeStatus();
    if (res.ok && res.data) {
      const trading = res.data.trading_active ?? res.data.exchange_active ?? res.data.status;
      $('#hsStatus').textContent = trading === true || trading === 'open' || trading === 'active' ? 'OPEN' : String(trading ?? 'reachable').toUpperCase();
      $('#hsStatusNote').textContent = 'Kalshi demo exchange reachable from your browser';
      return true;
    }
    $('#hsStatus').textContent = 'UNREACHABLE';
    $('#hsStatusNote').textContent = 'demo API not reachable from this browser (network/CORS) — live pages will offer a simulated fallback';
    return false;
  }

  async function loadTopEvents() {
    const tbody = $('#topEventsBody');
    try {
      const res = await Kalshi.getEvents({ status: 'open', limit: 200 });
      if (!res.ok) throw new Error('HTTP ' + (res.status || 'network/CORS'));
      const flat = await Kalshi.flattenEvents(res);
      const rows = flat.map(({ event, market }) => {
        const row = Desk.buildRow(event, market);
        if (!row) return null;
        return { topic: row.topic, title: row.title, ticker: row.ticker, last: row.price, vol: row.volume, notional: row.notional24h };
      }).filter(Boolean);
      rows.sort((a, b) => b.notional - a.notional);
      $('#hsContracts').textContent = String(rows.length);
      const topics = new Set(rows.map(r => r.topic));
      $('#hsTopics').textContent = String(topics.size) + ' / 5';
      const top = rows.slice(0, 5);
      tbody.innerHTML = top.length ? top.map(r => `<tr>
        <td><span class="badge topic-${r.topic}">${escapeHtml((TOPIC_BY_ID[r.topic] || {}).short)}</span></td>
        <td style="max-width:420px" title="${escapeHtml(r.title)}">${escapeHtml(String(r.title).slice(0, 90))}${String(r.title).length > 90 ? '…' : ''}</td>
        <td class="num">${r.last != null ? '$' + r.last.toFixed(2) : '—'}</td>
        <td class="num">${fmtContracts(r.vol)}</td>
        <td class="num">${r.notional == null ? '—' : fmtUsd(r.notional, 0)}</td>
      </tr>`).join('') : '<tr class="empty-row"><td colspan="5">No tracked-topic contracts right now.</td></tr>';
      $('#topEventsNote').textContent = 'Live snapshot from the demo API, sorted by 24h estimated turnover (exchange 24h volume × current price — this page\'s arithmetic, labelled). Refreshes on each page load.';
    } catch (err) {
      $('#hsContracts').textContent = '—';
      $('#hsTopics').textContent = '—';
      tbody.innerHTML = '<tr class="empty-row"><td colspan="5">Live snapshot unavailable (' + escapeHtml(String(err.message || err)) + '). Open the Live Dashboard for the simulated fallback.</td></tr>';
      $('#topEventsNote').textContent = 'The demo API was unreachable from this browser. Values are never fabricated — see Verification for what was checked offline.';
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (!$('#hsStatus')) return;
    pingExchange();
    loadTopEvents();
  });
})();
