/* portfolio.js — paper trading ledger (this browser) + optional Kalshi DEMO account.
   Demo API keys are stored ONLY in localStorage and are sent ONLY to the Kalshi demo
   hosts when you click connect. They are never committed to the repo or sent elsewhere. */
'use strict';

(function () {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  function switchTab(name) {
    $$('.pf-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    $$('.pf-pane').forEach(p => { p.style.display = p.dataset.pane === name ? 'block' : 'none'; });
  }

  /* ---------- live marks (best effort) ---------- */
  async function fetchMarks() {
    try {
      const res = await Kalshi.getEvents({ status: 'open', limit: 200 });
      if (!res.ok) return null;
      const flat = await Kalshi.flattenEvents(res);
      const map = {};
      for (const { market } of flat) {
        const p = Kalshi.priceOf(market, 'last');
        if (p != null && market.ticker) map[market.ticker] = p;
      }
      return map;
    } catch { return null; }
  }

  /* ---------- PAPER ---------- */
  function renderPaper(marks) {
    const p = PaperPortfolio.load();
    if (marks) PaperPortfolio.mark(marks);
    const p2 = PaperPortfolio.load();
    const eq = PaperPortfolio.equity(marks || {});

    $('#paperEquity').textContent = fmtUsd(eq.equity);
    $('#paperCash').textContent = fmtUsd(eq.cash);
    $('#paperOpenValue').textContent = fmtUsd(eq.openValue);
    $('#paperRealized').textContent = fmtSignedUsd(eq.realizedPnl);
    $('#paperRealized').className = 'value ' + (eq.realizedPnl >= 0 ? 'up' : 'down');
    $('#paperUnrealized').textContent = fmtSignedUsd(eq.unrealizedPnl);
    $('#paperUnrealized').className = 'value ' + (eq.unrealizedPnl >= 0 ? 'up' : 'down');

    // equity history (this browser only)
    const hist = store.get('equityHistory', []);
    hist.push({ t: Date.now(), v: eq.equity });
    while (hist.length > 500) hist.shift();
    store.set('equityHistory', hist);
    drawEquityCurve($('#paperEquityChart'), hist.map(h => h.v));

    // positions
    const tbody = $('#paperPositionsBody');
    if (!p2.positions.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="9">No open paper positions. Buy YES contracts from the <a href="dashboard.html">Live Dashboard</a> (“Paper buy” button).</td></tr>';
    } else {
      tbody.innerHTML = p2.positions.map(pos => {
        const mark = (marks && marks[pos.ticker]) ?? pos.lastMark ?? pos.avgPrice;
        const value = pos.qty * mark;
        const pnl = (mark - pos.avgPrice) * pos.qty;
        return `<tr>
          <td class="mono small">${escapeHtml(pos.ticker)}${pos.sim || /^SIM-/.test(pos.ticker) ? ' <span class="badge sim">SIM</span>' : ''}</td>
          <td><span class="badge topic-${escapeHtml(pos.topic || 'culture')}">${escapeHtml((TOPIC_BY_ID[pos.topic] || {}).short || pos.topic || '—')}</span></td>
        <td class="num">${fmtContracts(pos.qty)}</td>
        <td class="num">$${pos.avgPrice.toFixed(2)}</td>
        <td class="num">$${mark.toFixed(2)}</td>
        <td class="num">${fmtUsd(value)}</td>
        <td class="num ${pnl >= 0 ? 'up' : 'down'}">${fmtSignedUsd(pnl)}</td>
        <td class="num ${pnl >= 0 ? 'up' : 'down'}">${pos.avgPrice > 0 ? ((pnl / (pos.avgPrice * pos.qty)) * 100).toFixed(1) + '%' : '—'}</td>
        <td><button class="btn small danger" data-close="${escapeHtml(pos.id)}" data-mark="${mark}">Close all</button></td>
        </tr>`;
      }).join('');
      tbody.querySelectorAll('[data-close]').forEach(btn => btn.addEventListener('click', () => {
        const res = PaperPortfolio.sell({ positionId: btn.dataset.close, qty: Infinity, price: parseFloat(btn.dataset.mark) });
        toast(res.ok ? `Position closed · realized P&L ${fmtSignedUsd(res.pnl)}` : res.error, 3500);
        refreshPaper();
      }));
    }

    // trades history
    const ttbody = $('#paperTradesBody');
    const trades = [...p2.trades].sort((a, b) => b.at - a.at).slice(0, 100);
    ttbody.innerHTML = trades.length ? trades.map(t => `<tr>
      <td class="small">${fmtDateTime(t.at)}</td>
      <td><span class="badge ${t.side === 'buy' ? 'info' : 'ok'}">${escapeHtml(t.side.toUpperCase())}</span></td>
      <td class="mono small">${escapeHtml(t.ticker)}</td>
      <td><span class="badge topic-${escapeHtml(t.topic || 'culture')}">${escapeHtml((TOPIC_BY_ID[t.topic] || {}).short || t.topic || '—')}</span></td>
      <td class="num">${fmtContracts(t.qty)}</td>
      <td class="num">$${t.price.toFixed(2)}</td>
      <td class="num">${fmtUsd(t.fee)}</td>
      <td class="num ${(t.pnl ?? 0) >= 0 ? 'up' : 'down'}">${t.pnl != null ? fmtSignedUsd(t.pnl) : '—'}</td>
    </tr>`).join('') : '<tr class="empty-row"><td colspan="8">No paper trades yet.</td></tr>';

    // per-topic realized P&L
    const byTopic = {};
    for (const t of p2.trades) if (t.pnl != null) byTopic[t.topic || 'unknown'] = (byTopic[t.topic || 'unknown'] || 0) + t.pnl;
    $('#paperTopicBody').innerHTML = Object.keys(byTopic).length
      ? Object.entries(byTopic).sort((a, b) => b[1] - a[1]).map(([topic, pnl]) => `<tr><td><span class="badge topic-${escapeHtml(topic)}">${escapeHtml((TOPIC_BY_ID[topic] || {}).name || topic)}</span></td><td class="num ${pnl >= 0 ? 'up' : 'down'}">${fmtSignedUsd(pnl)}</td></tr>`).join('')
      : '<tr class="empty-row"><td colspan="2">No closed trades yet.</td></tr>';
  }

  function drawEquityCurve(canvas, values) {
    const ctx = canvas && canvas.getContext ? canvas.getContext('2d') : null;
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width) return;
    canvas.width = rect.width * dpr; canvas.height = rect.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const W = rect.width, H = rect.height, pad = 44;
    ctx.clearRect(0, 0, W, H);
    if (values.length < 2) {
      ctx.fillStyle = '#5d688f'; ctx.font = '13px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText('Equity curve builds each time you visit/refresh this page (this browser only).', W / 2, H / 2);
      return;
    }
    const min = Math.min(...values), max = Math.max(...values), span = Math.max(1, max - min);
    ctx.strokeStyle = '#00dd94'; ctx.lineWidth = 2; ctx.beginPath();
    values.forEach((v, i) => {
      const x = pad + (i / (values.length - 1)) * (W - 2 * pad);
      const y = 10 + (1 - (v - min) / span) * (H - 34);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = '#8b96b8'; ctx.font = '11px ui-monospace, monospace';
    ctx.fillText('$' + max.toFixed(0), 4, 12);
    ctx.fillText('$' + min.toFixed(0), 4, H - 18);
  }

  async function refreshPaper() {
    $('#paperMarksNote').textContent = 'Refreshing marks from the demo API…';
    const marks = await fetchMarks();
    $('#paperMarksNote').textContent = marks ? 'Marks updated from the live demo API (' + Object.keys(marks).length + ' contracts).' : 'Demo API unreachable — using last known marks (browser-local).';
    renderPaper(marks);
  }

  /* ---------- DEMO ACCOUNT ---------- */
  const g = (obj, path) => path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);
  const firstOf = (obj, paths) => { for (const p of paths) { const v = g(obj, p); if (v != null) return v; } return null; };

  async function connectDemo() {
    const btn = $('#demoConnectBtn');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Connecting…';
    $('#demoError').style.display = 'none';
    try {
      const [bal, pos, fills, orders] = await Promise.all([Kalshi.getBalance(), Kalshi.getPositions(), Kalshi.getFills(25), Kalshi.getOrders('resting')]);
      if (!bal.ok) throw new Error('Balance request failed (HTTP ' + (bal.status || 'network') + '): ' + JSON.stringify(bal.data || bal.error).slice(0, 300));
      const cents = firstOf(bal.data, ['balance', 'balance_cents']);
      const dollars = firstOf(bal.data, ['balance_dollars']);
      $('#demoBalance').textContent = dollars != null ? '$' + Number(dollars).toFixed(2) : (cents != null ? fmtUsd(cents / 100) : '—');
      const upnl = firstOf(bal.data, ['portfolio_value', 'portfolio_value_dollars']);
      $('#demoPortfolioValue').textContent = upnl != null ? (Number(upnl) > 1000 ? fmtUsd(upnl / 100) : fmtUsd(upnl)) : '—';

      // positions
      const mpos = firstOf(pos.data, ['market_positions']) || [];
      $('#demoPositionsBody').innerHTML = mpos.length ? mpos.slice(0, 50).map(mp => `<tr>
        <td class="mono small">${escapeHtml(mp.ticker || '—')}</td>
        <td class="num">${escapeHtml(String(firstOf(mp, ['position_fp', 'position']) ?? '—'))}</td>
        <td class="num">${fmtUsd(fpOrCents(firstOf(mp, ['market_exposure_fp']), firstOf(mp, ['market_exposure'])))}</td>
        <td class="num">${fmtSignedUsd(fpOrCents(firstOf(mp, ['realized_pnl_fp']), firstOf(mp, ['realized_pnl'])))}</td>
        <td class="num">${fmtUsd(fpOrCents(firstOf(mp, ['fees_paid_fp']), firstOf(mp, ['fees_paid'])))}</td>
      </tr>`).join('') : '<tr class="empty-row"><td colspan="5">No open demo positions.</td></tr>';

      // fills
      const fl = firstOf(fills.data, ['fills']) || [];
      $('#demoFillsBody').innerHTML = fl.length ? fl.slice(0, 25).map(f => `<tr>
        <td class="small">${escapeHtml((f.created_time || f.ts || '').toString().replace('T', ' ').slice(0, 19))}</td>
        <td class="mono small">${escapeHtml(f.ticker || '—')}</td>
        <td>${escapeHtml(f.side || f.action || '—')}</td>
        <td class="num">${escapeHtml(String(firstOf(f, ['count_fp', 'count']) ?? '—'))}</td>
        <td class="num">${fmtUsd(fpOrCents(firstOf(f, ['price_dollars']), firstOf(f, ['price'])))}</td>
        <td>${f.is_taker === false ? 'maker' : 'taker'}</td>
      </tr>`).join('') : '<tr class="empty-row"><td colspan="6">No recent fills (or fills endpoint shape differs — see raw response below).</td></tr>';

      // resting orders
      const od = firstOf(orders.data, ['orders']) || [];
      $('#demoOrdersBody').innerHTML = od.length ? od.slice(0, 25).map(o => `<tr>
        <td class="mono small">${escapeHtml(o.ticker || '—')}</td>
        <td>${escapeHtml(o.side || '—')}</td>
        <td class="num">${escapeHtml(String(firstOf(o, ['remaining_count_fp', 'count_fp', 'remaining_count', 'count']) ?? '—'))}</td>
        <td class="num">${fmtUsd(fpOrCents(firstOf(o, ['yes_price_dollars', 'price_dollars']), firstOf(o, ['yes_price', 'price'])))}</td>
        <td class="small">${escapeHtml(o.status || '—')}</td>
      </tr>`).join('') : '<tr class="empty-row"><td colspan="5">No resting orders.</td></tr>';

      $('#demoRaw').textContent = JSON.stringify({ balance: bal.data, positions: pos.data, fills: fills.data, orders: orders.data }, null, 2).slice(0, 6000);
      $('#demoStatus').innerHTML = '<span class="badge ok">CONNECTED</span> Demo account data loaded at ' + fmtTime(Date.now());
    } catch (err) {
      console.error(err);
      $('#demoError').style.display = 'block';
      $('#demoErrorText').textContent = String(err.message || err);
      $('#demoStatus').innerHTML = '<span class="badge err">FAILED</span>';
    } finally {
      btn.disabled = false; btn.textContent = '↻ Connect & refresh';
    }
  }
  const num2 = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
  /* fixed-point dollar field preferred (already dollars); legacy integer field is cents */
  const fpOrCents = (fp, legacy) => (fp != null ? num2(fp) : num2(legacy) / 100);

  /* ---------- SETTINGS ---------- */
  function loadSettings() {
    const s = store.get('settings', {});
    $('#setKeyId').value = s.apiKeyId || '';
    $('#setPem').value = s.privateKeyPem || '';
    $('#setWsProxy').value = s.wsProxyUrl || '';
    $('#setEnableOrders').checked = !!s.enableOrders;
  }
  function saveSettings() {
    const s = {
      apiKeyId: $('#setKeyId').value.trim(),
      privateKeyPem: $('#setPem').value,
      wsProxyUrl: $('#setWsProxy').value.trim(),
      enableOrders: $('#setEnableOrders').checked,
    };
    if (s.enableOrders && !window.confirm('Enable DEMO order execution? Orders will be placed on your Kalshi demo account (mock funds) when you click “Demo buy YES” on the dashboard.')) {
      s.enableOrders = false; $('#setEnableOrders').checked = false;
    }
    store.set('settings', s);
    toast('Settings saved locally in this browser.');
  }

  document.addEventListener('DOMContentLoaded', () => {
    $$('.pf-tab').forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));
    $('#refreshPaperBtn').addEventListener('click', refreshPaper);
    $('#resetPaperBtn').addEventListener('click', () => { if (window.confirm('Reset the paper portfolio to $10,000 and clear all paper trades?')) { PaperPortfolio.reset(); store.remove('equityHistory'); refreshPaper(); } });
    $('#demoConnectBtn').addEventListener('click', connectDemo);
    $('#saveSettingsBtn').addEventListener('click', saveSettings);
    $('#clearSettingsBtn').addEventListener('click', () => { store.remove('settings'); loadSettings(); toast('Settings cleared from this browser.'); });
    loadSettings();
    refreshPaper();
    switchTab('paper');
  });
})();
