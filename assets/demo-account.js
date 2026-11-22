import { loadLocal, renderBanner, money, cents, int, esc, dash, stamp, sourceLink } from './common.js';

function setText(id, v) { const n = document.getElementById(id); if (n) n.textContent = v; }

/** Fill time, whichever field the response used. A missing time is a dash. */
function fillTime(f) {
  if (f?.created_time) return stamp(f.created_time);
  if (f?.ts != null && Number.isFinite(Number(f.ts))) return stamp(new Date(Number(f.ts) * 1000).toISOString());
  return dash;
}

function levelQty(v) {
  // Positions use position_fp as a fixed-point string; sign is YES(+) / NO(−).
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

async function init() {
  let acct;
  try {
    acct = await loadLocal('data/account.json');
  } catch (err) {
    renderBanner(document.getElementById('data-banner'), { state: 'error', headline: 'Snapshot failed to load', detail: err.message });
    return;
  }

  const badge = document.getElementById('conn-badge');
  if (!acct.connected) {
    badge.textContent = 'not connected';
    badge.className = 'badge warn';
    document.getElementById('not-connected').hidden = false;
    setText('nc-reason', acct.reason ?? 'No authenticated demo-account read has been made.');
    const steps = document.getElementById('nc-steps');
    steps.innerHTML = (acct.howToConnect ?? []).map((s) => {
      // Render a bare URL in a step as a link; otherwise plain text.
      const m = s.match(/https?:\/\/\S+/);
      if (!m) return `<li>${esc(s)}</li>`;
      const url = m[0].replace(/[),.]+$/, '');
      return `<li>${esc(s.slice(0, m.index))}<a href="${esc(url)}" target="_blank" rel="noopener noreferrer nofollow">${esc(url)}</a>${esc(s.slice(m.index + url.length))}</li>`;
    }).join('');
    setText('nc-docs', '');
    document.getElementById('nc-docs').innerHTML = acct.docs
      ? `Kalshi documentation: <a href="${esc(acct.docs)}" target="_blank" rel="noopener noreferrer nofollow">API keys</a> · <a href="${esc(acct.demoDocs ?? 'https://docs.kalshi.com/getting_started/demo_env')}" target="_blank" rel="noopener noreferrer nofollow">demo environment</a>.`
      : '';
    renderBanner(document.getElementById('data-banner'), {
      state: 'error',
      headline: 'No authenticated read yet',
      detail: 'The demo-account job has not been able to sign a request. Nothing on this page is a balance.',
      at: acct.checkedAt,
    });
    return;
  }

  badge.textContent = 'connected';
  badge.className = 'badge ok';
  document.getElementById('connected').hidden = false;

  const b = acct.balance ?? {};
  const bal = b.balance_dollars ?? (b.balance != null ? (b.balance / 100).toFixed(2) : null);
  const pv = b.portfolio_value_dollars ?? (b.portfolio_value != null ? (b.portfolio_value / 100).toFixed(2) : null);
  setText('acct-balance', bal == null ? dash : money(bal, 2));
  setText('acct-balance-sub', `captured ${stamp(acct.checkedAt)}`);
  setText('acct-pv', pv == null ? dash : money(pv, 2));

  const positions = acct.positions?.market_positions ?? [];
  setText('acct-pos', int(positions.length));
  const posBody = document.querySelector('#acct-pos-table tbody');
  posBody.innerHTML = positions.length ? positions.map((p) => {
    const qty = levelQty(p.position_fp ?? p.position);
    return `<tr>
      <td class="mono">${esc(p.ticker ?? dash)}</td>
      <td class="num">${esc(qty == null ? dash : int(Math.abs(qty)))}${qty != null && qty < 0 ? ' <span class="badge no">NO</span>' : qty != null ? ' <span class="badge yes">YES</span>' : ''}</td>
      <td class="num">${esc(p.market_exposure_dollars != null ? money(p.market_exposure_dollars) : dash)}</td>
      <td class="num">${esc(p.realized_pnl_dollars != null ? money(p.realized_pnl_dollars) : dash)}</td>
      <td class="num">${esc(p.fees_paid_dollars != null ? money(p.fees_paid_dollars) : dash)}</td>
      <td class="src">${sourceLink(acct.sources?.positions, 'positions')}</td>
    </tr>`;
  }).join('') : `<tr><td colspan="6" class="empty">No non-zero position in the captured page.</td></tr>`;

  const fills = acct.fills?.fills ?? [];
  setText('acct-fills', int(fills.length));
  document.querySelector('#acct-fill-table tbody').innerHTML = fills.length ? fills.slice(0, 60).map((f) => `<tr>
      <td class="mono nowrap">${esc(fillTime(f))}</td>
      <td class="mono">${esc(f.ticker ?? f.market_ticker ?? dash)}</td>
      <td>${esc(f.outcome_side ?? f.side ?? dash)}</td>
      <td class="num">${esc(f.yes_price_dollars != null ? cents(f.yes_price_dollars) : (f.yes_price != null ? cents(f.yes_price / 100) : dash))}</td>
      <td class="num">${esc(f.count_fp != null ? int(f.count_fp) : (f.count != null ? int(f.count) : dash))}</td>
      <td class="src">${sourceLink(acct.sources?.fills, 'fills')}</td>
    </tr>`).join('') : `<tr><td colspan="6" class="empty">No fill in the captured page.</td></tr>`;

  const settlements = acct.settlements?.settlements ?? [];
  document.querySelector('#acct-settle-table tbody').innerHTML = settlements.length ? settlements.slice(0, 60).map((s) => `<tr>
      <td class="mono nowrap">${esc(s.settled_time ?? dash)}</td>
      <td class="mono">${esc(s.ticker ?? dash)}</td>
      <td>${esc(s.market_result ?? dash)}</td>
      <td class="num">${esc(s.revenue_dollars != null ? money(s.revenue_dollars) : dash)}</td>
      <td class="src">${sourceLink(acct.sources?.settlements, 'settlements')}</td>
    </tr>`).join('') : `<tr><td colspan="5" class="empty">No settlement in the captured page.</td></tr>`;

  const errors = acct.errors ?? [];
  renderBanner(document.getElementById('data-banner'), {
    state: errors.length ? 'snapshot' : 'live',
    headline: errors.length ? 'Connected, with some reads failing' : 'Connected to the demo account',
    detail: errors.length
      ? `${errors.length} of the authenticated reads failed on the last run; the failing calls are listed in data/account.json.`
      : 'Signed reads completed in the last snapshot job.',
    at: acct.checkedAt,
  });
}

init();
