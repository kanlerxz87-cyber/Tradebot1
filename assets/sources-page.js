import { loadLocal, renderBanner, esc, dash, sourceLink } from './common.js';

function tbody(id, rows, cols) {
  const body = document.querySelector(`#${id} tbody`);
  if (!body) return;
  if (!rows.length) { body.innerHTML = `<tr><td colspan="${cols}" class="empty">None recorded.</td></tr>`; return; }
  body.innerHTML = rows.join('');
}

async function init() {
  let data;
  try {
    data = await loadLocal('data/sources.json');
  } catch (err) {
    renderBanner(document.getElementById('data-banner'), { state: 'error', headline: 'Source registry failed to load', detail: err.message });
    return;
  }
  renderBanner(document.getElementById('data-banner'), {
    state: 'snapshot',
    headline: `${(data.officialDocs ?? []).length + (data.officialApiObservations ?? []).length} verified sources`,
    detail: `Read and checked on ${data.meta?.verifiedAt ?? dash}. Each row links to the page or the exact request.`,
  });

  tbody('docs-table', (data.officialDocs ?? []).map((r) => `<tr>
    <td class="mono dim">${esc(r.id)}</td>
    <td>${esc(r.title)}</td>
    <td class="small">${esc(r.states)}</td>
    <td class="src">${sourceLink(r.url, 'open')}</td>
  </tr>`), 4);

  tbody('api-table', (data.officialApiObservations ?? []).map((r) => `<tr>
    <td class="mono dim">${esc(r.id)}</td>
    <td>${esc(r.title)}<span class="sub mono">${esc(r.url.replace('https://external-api.demo.kalshi.co/trade-api/v2', ''))}</span></td>
    <td class="mono small nowrap">${esc(r.observed ?? dash)}</td>
    <td class="small">${esc(r.states)}</td>
    <td class="src">${sourceLink(r.url, 'live')}</td>
  </tr>`), 5);

  tbody('pub-table', (data.primaryDataPublishers ?? []).map((r) => `<tr>
    <td class="mono dim">${esc(r.id)}</td>
    <td>${esc(r.title)}</td>
    <td class="small">${esc(r.why)}</td>
    <td class="src">${sourceLink(r.url, 'open')}</td>
  </tr>`), 4);

  tbody('rules-table', (data.projectRules ?? []).map((r) => `<tr>
    <td class="mono dim">${esc(r.id)}</td>
    <td>${esc(r.title)}</td>
    <td class="mono small">${esc(r.where)}</td>
    <td class="small">${esc(r.rule)}</td>
  </tr>`), 4);
}

init();
