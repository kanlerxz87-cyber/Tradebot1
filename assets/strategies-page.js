import { loadLocal, renderBanner, esc, dash, int, signedMoney, sourceLink } from './common.js';

const NAMES = {
  momentum: 'Momentum (buy the move)',
  fade: 'Fade (sell the spike)',
  dipbuy: 'Dip buyer',
  longshot: 'Longshot collector',
  favorite: 'Favorite carry',
};

async function init() {
  let data;
  try {
    data = await loadLocal('data/live/portfolio.json');
  } catch (err) {
    renderBanner(document.getElementById('data-banner'), { state: 'error', headline: 'Simulator record failed to load', detail: err.message });
    return;
  }
  renderBanner(document.getElementById('data-banner'), {
    state: 'snapshot',
    headline: `Simulator record · ${data.positions?.length ?? 0} positions`,
    detail: 'Read from data/live/portfolio.json, written by the scheduled collector.',
    at: data.updatedAt,
  });

  const tbody = document.querySelector('#results tbody');
  const byId = new Map(Object.keys(NAMES).map((id) => [id, []]));
  for (const p of data.positions ?? []) {
    if (!byId.has(p.strategyId)) byId.set(p.strategyId, []);
    byId.get(p.strategyId).push(p);
  }
  const rows = [...byId.entries()];
  if (!rows.some(([, list]) => list.length)) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">No strategy rule has fired yet. The collector opens a simulated position the first time a rule's condition holds.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(([id, list]) => {
    const settled = list.filter((p) => p.status === 'settled');
    const wins = settled.filter((p) => p.won).length;
    const realized = settled.reduce((s, p) => s + (p.realizedPnl ?? 0), 0);
    return `<tr>
      <td><a href="#${esc(id)}">${esc(NAMES[id] ?? id)}</a></td>
      <td class="num">${esc(int(list.length))}</td>
      <td class="num">${esc(int(settled.length))}</td>
      <td class="num">${esc(int(wins))}</td>
      <td class="num ${realized >= 0 ? 'up' : 'down'}">${esc(settled.length ? signedMoney(realized) : dash)}</td>
      <td class="src">${sourceLink(`https://github.com/kanlerxz87-cyber/Tradebot1/blob/main/data/live/portfolio.json`, 'record')}</td>
    </tr>`;
  }).join('');
}

init();
