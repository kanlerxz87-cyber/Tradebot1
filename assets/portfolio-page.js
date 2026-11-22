// portfolio.html — reads data/live/portfolio.json, which the collector writes.

import { loadLocal, renderBanner, money, cents, int, pct, esc, dash, stamp, timeAgo, signedMoney, sourceLink, TOPIC_LABELS } from './common.js';

const STRATEGY_NAMES = {
  momentum: 'Momentum (buy the move)',
  fade: 'Fade (sell the spike)',
  dipbuy: 'Dip buyer',
  longshot: 'Longshot collector',
  favorite: 'Favorite carry',
};

let data = { positions: [], summary: {}, startingCash: 1000 };
let filter = 'all';

function setText(id, v) { const n = document.getElementById(id); if (n) n.textContent = v; }
function setClass(id, cls) { const n = document.getElementById(id); if (n) n.className = `v ${cls}`; }

function summarise(list) {
  const settled = list.filter((p) => p.status === 'settled');
  const open = list.filter((p) => p.status === 'open');
  const realized = settled.reduce((s, p) => s + (p.realizedPnl ?? 0), 0);
  const fees = list.reduce((s, p) => s + (p.entryFee ?? 0) + (p.exitFee ?? 0), 0);
  const wins = settled.filter((p) => p.won).length;
  return { n: list.length, settled: settled.length, open: open.length, realized, fees, wins, winRate: settled.length ? wins / settled.length : null };
}

function renderHeadline() {
  const s = data.summary ?? {};
  const start = data.startingCash ?? 1000;
  const equity = s.equity ?? null;
  setText('p-equity', equity == null ? dash : money(equity, 2));
  setClass('p-equity', equity == null ? '' : equity >= start ? 'up' : 'down');
  setText('p-realized', s.realizedPnl == null ? dash : signedMoney(s.realizedPnl));
  setClass('p-realized', (s.realizedPnl ?? 0) >= 0 ? 'up' : 'down');
  setText('p-unrealized', s.unrealizedPnl == null ? dash : signedMoney(s.unrealizedPnl));
  setText('p-fees', s.feesPaid == null ? dash : money(s.feesPaid, 2));
  setText('p-winrate', s.winRate == null ? dash : pct(s.winRate, 1));
  setText('p-winrate-sub', s.settledPositions ? `${s.wins ?? 0} of ${s.settledPositions} settled` : 'no settled trades yet');
  setText('p-positions', `${data.positions.length} positions`);
  setText('p-equity-sub', `starting cash ${money(start, 0)} + realized + unrealized`);
}

function renderEquityCurve() {
  const canvas = document.getElementById('equity-chart');
  const settled = data.positions
    .filter((p) => p.status === 'settled' && p.settledAt && Number.isFinite(p.realizedPnl))
    .sort((a, b) => String(a.settledAt).localeCompare(String(b.settledAt)));
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 700;
  const h = canvas.clientHeight || 300;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  if (settled.length < 2) {
    ctx.fillStyle = '#6f8299';
    ctx.font = '12px -apple-system, Segoe UI, Roboto, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(settled.length ? 'One settled trade: a curve needs two.' : 'No settled positions yet, so there is nothing to plot.', w / 2, h / 2);
    return;
  }

  let cum = 0;
  const pts = settled.map((p) => { cum += p.realizedPnl; return { t: new Date(p.settledAt).getTime(), v: cum }; });
  const pad = { l: 52, r: 14, t: 16, b: 26 };
  const plotW = w - pad.l - pad.r; const plotH = h - pad.t - pad.b;
  const vMin = Math.min(0, ...pts.map((p) => p.v));
  const vMax = Math.max(0, ...pts.map((p) => p.v));
  const span = vMax - vMin || 1;
  const t0 = pts[0].t; const t1 = pts[pts.length - 1].t || t0 + 1;
  const X = (t) => pad.l + ((t - t0) / Math.max(1, t1 - t0)) * plotW;
  const Y = (v) => pad.t + plotH - ((v - vMin) / span) * plotH;

  ctx.font = '11px ui-monospace, Menlo, monospace';
  ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  for (let i = 0; i <= 4; i += 1) {
    const v = vMin + (span * i) / 4;
    const y = Y(v);
    ctx.strokeStyle = 'rgba(140,165,190,0.16)';
    ctx.beginPath(); ctx.moveTo(pad.l, y + 0.5); ctx.lineTo(pad.l + plotW, y + 0.5); ctx.stroke();
    ctx.fillStyle = '#6f8299';
    ctx.fillText(`${v >= 0 ? '' : '−'}$${Math.abs(v).toFixed(2)}`, pad.l - 8, y);
  }
  // zero line
  ctx.strokeStyle = 'rgba(167,184,203,0.5)';
  ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(pad.l, Y(0) + 0.5); ctx.lineTo(pad.l + plotW, Y(0) + 0.5); ctx.stroke();
  ctx.setLineDash([]);

  ctx.beginPath();
  ctx.moveTo(X(pts[0].t), Y(0));
  for (const p of pts) ctx.lineTo(X(p.t), Y(p.v));
  ctx.strokeStyle = '#22c98a'; ctx.lineWidth = 2; ctx.stroke();
  ctx.lineTo(X(pts[pts.length - 1].t), Y(0));
  ctx.closePath();
  ctx.fillStyle = 'rgba(34,201,138,0.12)';
  ctx.fill();
}

function renderByStrategy() {
  const byId = new Map();
  for (const p of data.positions) {
    if (!byId.has(p.strategyId)) byId.set(p.strategyId, []);
    byId.get(p.strategyId).push(p);
  }
  const ids = Object.keys(STRATEGY_NAMES).filter((id) => byId.has(id));
  const tbody = document.querySelector('#strategy-table tbody');
  if (!ids.length) { tbody.innerHTML = `<tr><td colspan="9" class="empty">No simulated position yet. The collector opens one when a strategy's rule fires.</td></tr>`; return; }
  tbody.innerHTML = ids.map((id) => {
    const list = byId.get(id);
    const s = summarise(list);
    return `<tr>
      <td><a href="strategies.html#${esc(id)}">${esc(STRATEGY_NAMES[id])}</a></td>
      <td class="num">${esc(int(s.n))}</td>
      <td class="num">${esc(int(s.open))}</td>
      <td class="num">${esc(int(s.settled))}</td>
      <td class="num">${esc(int(s.wins))}</td>
      <td class="num">${esc(s.winRate == null ? dash : pct(s.winRate, 0))}</td>
      <td class="num ${s.realized >= 0 ? 'up' : 'down'}">${esc(signedMoney(s.realized))}</td>
      <td class="num">${esc(money(s.fees, 2))}</td>
      <td class="src">${sourceLink('https://github.com/kanlerxz87-cyber/Tradebot1/blob/main/tools/strategies.mjs', 'rule')}</td>
    </tr>`;
  }).join('');
}

function renderByTopic() {
  const byTopic = new Map();
  for (const p of data.positions) {
    if (!byTopic.has(p.topic)) byTopic.set(p.topic, []);
    byTopic.get(p.topic).push(p);
  }
  const tbody = document.querySelector('#topic-table tbody');
  if (!byTopic.size) { tbody.innerHTML = `<tr><td colspan="6" class="empty">No simulated position yet.</td></tr>`; return; }
  tbody.innerHTML = [...byTopic.entries()].map(([topic, list]) => {
    const s = summarise(list);
    return `<tr>
      <td>${esc(TOPIC_LABELS[topic] ?? topic)}</td>
      <td class="num">${esc(int(s.n))}</td>
      <td class="num">${esc(int(s.settled))}</td>
      <td class="num">${esc(int(s.wins))}</td>
      <td class="num ${s.realized >= 0 ? 'up' : 'down'}">${esc(signedMoney(s.realized))}</td>
      <td class="num">${esc(money(s.fees, 2))}</td>
    </tr>`;
  }).join('');
}

function renderPositions() {
  const list = data.positions
    .filter((p) => (filter === 'all' ? true : p.status === filter))
    .slice()
    .sort((a, b) => String(b.openedAt).localeCompare(String(a.openedAt)));
  const tbody = document.querySelector('#positions-table tbody');
  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="11" class="empty">No position matches this filter.</td></tr>`;
    return;
  }
  tbody.innerHTML = list.map((p) => {
    const pnl = p.status === 'settled' ? p.realizedPnl : p.unrealizedPnl;
    const known = Number.isFinite(pnl);
    return `<tr>
      <td class="mono nowrap">${esc(stamp(p.openedAt))}</td>
      <td><a href="market.html?t=${encodeURIComponent(p.ticker)}">${esc(p.title || p.ticker)}</a><span class="sub mono">${esc(p.ticker)}</span></td>
      <td class="small">${esc(STRATEGY_NAMES[p.strategyId] ?? p.strategyId)}</td>
      <td><span class="badge ${p.side === 'yes' ? 'yes' : 'no'}">${esc(p.side.toUpperCase())}</span></td>
      <td class="num">${esc(cents(p.entryPrice))}</td>
      <td class="num">${esc(int(p.contracts))}</td>
      <td class="num">${esc(money(p.entryCost, 2))}</td>
      <td class="num">${esc(money(p.entryFee, 2))}</td>
      <td><span class="badge ${p.status === 'settled' ? (p.won ? 'ok' : 'warn') : ''}">${esc(p.status)}${p.status === 'settled' && p.result ? ` · ${esc(p.result.toUpperCase())}` : ''}</span></td>
      <td class="num ${!known ? '' : pnl >= 0 ? 'up' : 'down'}">${esc(known ? signedMoney(pnl) : dash)}</td>
      <td class="src">${sourceLink('https://github.com/kanlerxz87-cyber/Tradebot1/blob/main/data/live/portfolio.json', 'record')}</td>
    </tr>`;
  }).join('');
}

async function init() {
  try {
    data = await loadLocal('data/live/portfolio.json');
  } catch (err) {
    renderBanner(document.getElementById('data-banner'), { state: 'error', headline: 'Portfolio record failed to load', detail: err.message });
    return;
  }
  renderBanner(document.getElementById('data-banner'), {
    state: 'snapshot',
    headline: `Simulated record · ${data.positions.length} positions`,
    detail: 'Written by the scheduled collector. No order is ever sent to Kalshi by this simulator.',
    at: data.updatedAt,
  });
  renderHeadline();
  renderEquityCurve();
  renderByStrategy();
  renderByTopic();
  renderPositions();
}

document.getElementById('pos-filter')?.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-f]');
  if (!btn) return;
  filter = btn.dataset.f;
  for (const b of document.querySelectorAll('#pos-filter button')) b.setAttribute('aria-pressed', String(b === btn));
  renderPositions();
});

window.addEventListener('resize', () => renderEquityCurve());
init();
