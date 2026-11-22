/* events.js — track live events across the 5 topics until they resolve (YES/NO).
   Resolution comes from the Kalshi API market `result` field for settled markets.
   Nothing is invented: unverifiable values render as "—" and are flagged. */
'use strict';

(function () {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const state = {
    status: 'open',      // open | settled | all
    topic: 'all',
    query: '',
    simulated: false,
    rows: [],
  };

  function classifyRow(ev, m) {
    const topic = m._topic || classifyMarket({ ...m, category: m.category || (ev && ev.category), series_ticker: m.series_ticker || (ev && ev.series_ticker) });
    if (!topic) return null;
    const yesBid = Kalshi.priceOf(m, 'bid');
    const yesAsk = Kalshi.priceOf(m, 'ask');
    const last = Kalshi.priceOf(m, 'last') ?? (yesBid != null && yesAsk != null ? (yesBid + yesAsk) / 2 : null);
    const result = (m.result || '').toLowerCase() || (String(m.status || '').toLowerCase() === 'settled' ? '' : '');
    return {
      topic,
      eventTicker: m.event_ticker || (ev && ev.event_ticker) || '—',
      seriesTicker: m.series_ticker || (ev && ev.series_ticker) || '—',
      title: (ev && ev.title) || m.title || m.ticker,
      contract: m.yes_sub_title || m.title || m.ticker,
      ticker: m.ticker,
      closeTime: m.close_time || m.expiration_time || (ev && ev.close_time) || null,
      status: String(m.status || (ev && ev.status) || 'unknown').toLowerCase(),
      result: result === 'yes' || result === 'no' ? result : '',
      vol: Kalshi.volumeOf(m),
      oi: Kalshi.openInterestOf(m),
      last,
      sim: !!m._sim,
      url: 'https://kalshi.com/markets/' + String((m.series_ticker || (ev && ev.series_ticker) || '')).toLowerCase(),
    };
  }

  async function load() {
    $('#eventsStatus').innerHTML = '<span class="spinner"></span> Loading from Kalshi demo API…';
    state.simulated = false;
    try {
      const statuses = state.status === 'all' ? ['open', 'settled'] : [state.status];
      let flat = [];
      for (const s of statuses) {
        const res = await Kalshi.getEvents({ status: s, limit: state.status === 'settled' ? 100 : 200 });
        if (!res.ok) {
          const err = new Error('HTTP ' + (res.status || 'network/CORS') + (res.error ? ': ' + res.error : ''));
          err.status = res.status || 0;
          throw err;
        }
        flat = flat.concat(await Kalshi.flattenEvents(res));
      }
      state.rows = flat.map(({ event, market }) => classifyRow(event, market)).filter(Boolean);
      $('#eventsError').style.display = 'none';
      $('#simNote').style.display = 'none';
      render();
      $('#eventsStatus').textContent = `Loaded ${state.rows.length} contracts across tracked topics · ${fmtDateTime(Date.now())}`;
    } catch (err) {
      console.error(err);
      $('#eventsStatus').textContent = 'Demo API unreachable from this browser.';
      $('#eventsError').style.display = 'block';
      $('#eventsErrorText').textContent = String(err.message || err) + ' — check network/CORS, or load the simulated sample (clearly labeled; no fake resolutions are shown).';
    }
  }

  function loadSimulated() {
    state.simulated = true;
    state.rows = SimulatedFeed.makeSnapshot(20261122).map(({ event, market }) => classifyRow(event, market)).filter(Boolean);
    if (state.status === 'settled') state.rows = []; // never invent resolutions
    $('#eventsError').style.display = 'none';
    $('#simNote').style.display = 'block';
    render();
    $('#eventsStatus').textContent = state.status === 'settled'
      ? 'Simulated mode: settlements are not synthesized. Switch to Open/All.'
      : `SIMULATED sample — ${state.rows.length} fictional contracts · not real Kalshi data`;
  }

  function filtered() {
    return state.rows.filter(r =>
      (state.topic === 'all' || r.topic === state.topic) &&
      (!state.query || (r.title + ' ' + r.ticker + ' ' + r.contract).toLowerCase().includes(state.query))
    );
  }

  const RESULT_BADGE = {
    yes: '<span class="badge ok">YES ✓</span>',
    no: '<span class="badge err" style="background:#3a1414;color:#ff9b9b;border-color:#7a2c2c">NO ✗</span>',
    '': '<span class="muted">—</span>',
  };

  function render() {
    const rows = filtered();
    $('#eventCount').textContent = String(rows.length);
    const wrap = $('#eventsWrap');
    if (!rows.length) {
      wrap.innerHTML = `<div class="card"><div class="muted" style="text-align:center;padding:24px">No ${escapeHtml(state.status)} events match the current filters. ${state.simulated && state.status === 'settled' ? 'Simulated settlements are intentionally not generated.' : ''}</div></div>`;
      return;
    }
    let html = '';
    for (const t of TOPICS) {
      const topicRows = rows.filter(r => r.topic === t.id).sort((a, b) => (b.vol || 0) - (a.vol || 0));
      if (!topicRows.length) continue;
      html += `
        <div class="card" style="margin-bottom:16px">
          <h2><span class="badge topic-${t.id}">${escapeHtml(t.short)}</span> ${escapeHtml(t.name)} · ${topicRows.length} contracts</h2>
          <div class="table-wrap"><table>
            <thead><tr><th>Event / Contract</th><th>Ticker</th><th>Close</th><th class="num">Volume</th><th class="num">Open interest</th><th class="num">Last</th><th>Status</th><th>Resolution</th><th>Links</th></tr></thead>
            <tbody>
              ${topicRows.map(r => `
                <tr>
                  <td style="max-width:360px" title="${escapeHtml(r.title)}"><div>${escapeHtml(truncate(r.title, 90))}</div><div class="muted small">${escapeHtml(truncate(r.contract, 90))}</div>${r.sim ? '<span class="badge sim">SIM</span>' : ''}</td>
                  <td class="mono" style="font-size:12px">${escapeHtml(r.ticker)}</td>
                  <td class="small">${r.closeTime ? escapeHtml(fmtDateTime(r.closeTime)) : '—'}</td>
                  <td class="num">${fmtContracts(r.vol)}</td>
                  <td class="num">${fmtContracts(r.oi)}</td>
                  <td class="num">${r.last != null ? '$' + r.last.toFixed(2) : '—'}</td>
                  <td class="small">${escapeHtml(r.status)}</td>
                  <td>${RESULT_BADGE[r.result] || RESULT_BADGE['']}</td>
                  <td class="small"><a href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer">Kalshi ↗</a><br><a href="https://www.google.com/search?tbm=nws&q=${encodeURIComponent(r.title)}" target="_blank" rel="noopener noreferrer">News ↗</a></td>
                </tr>`).join('')}
            </tbody>
          </table></div>
        </div>`;
    }
    wrap.innerHTML = html;
  }

  function truncate(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; }

  document.addEventListener('DOMContentLoaded', () => {
    $$('.status-btn').forEach(btn => btn.addEventListener('click', () => {
      state.status = btn.dataset.status;
      $$('.status-btn').forEach(b => b.classList.toggle('active', b === btn));
      if (state.simulated) loadSimulated(); else load();
    }));
    $$('.topic-btn').forEach(btn => btn.addEventListener('click', () => {
      state.topic = btn.dataset.topic;
      $$('.topic-btn').forEach(b => b.classList.toggle('active', b === btn));
      render();
    }));
    $('#eventSearch').addEventListener('input', (e) => { state.query = e.target.value.trim().toLowerCase(); render(); });
    $('#eventsRetryBtn').addEventListener('click', load);
    $('#eventsSimBtn').addEventListener('click', loadSimulated);
    $('#exportCsvBtn').addEventListener('click', () => {
      const rows = filtered();
      const header = 'topic,event_ticker,ticker,title,contract,close_time,status,result,volume,open_interest,last_price,simulated\n';
      const body = rows.map(r => [r.topic, r.eventTicker, r.ticker, csv(r.title), csv(r.contract), r.closeTime || '', r.status, r.result || '', r.vol, r.oi, r.last != null ? r.last.toFixed(4) : '', r.sim ? 1 : 0].join(',')).join('\n');
      const url = URL.createObjectURL(new Blob([header + body], { type: 'text/csv' }));
      const a = document.createElement('a');
      a.href = url; a.download = 'tradebot1-events.csv'; a.click(); URL.revokeObjectURL(url);
    });
    load();
  });

  function csv(s) { s = String(s || '').replace(/"/g, '""'); return /[",\n]/.test(s) ? '"' + s + '"' : s; }
})();
