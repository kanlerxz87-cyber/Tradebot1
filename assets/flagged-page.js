import { loadLocal, renderBanner, esc, dash, sourceLink } from './common.js';

let flags = [];
let sev = 'all';

const SEV_BADGE = { high: 'down', medium: 'warn', low: 'info', info: '' };

function render() {
  const host = document.getElementById('flags');
  const list = flags.filter((f) => (sev === 'all' ? true : f.severity === sev));
  if (!list.length) {
    host.innerHTML = '<div class="card empty">No flag at this severity.</div>';
    return;
  }
  host.innerHTML = list.map((f) => `<details class="flags" id="${esc(f.id)}"${f.severity === 'high' ? ' open' : ''}>
    <summary>
      <span class="mono dim">${esc(f.id)}</span>
      <span class="badge ${SEV_BADGE[f.severity] ?? ''}">${esc(f.severity)}</span>
      <strong>${esc(f.title)}</strong>
    </summary>
    <div class="body">
      <p>${esc(f.detail)}</p>
      ${f.impact ? `<p class="small"><strong>What it means for you:</strong> ${esc(f.impact)}</p>` : ''}
      ${f.howToCheck ? `<p class="small"><strong>How to check it yourself:</strong> ${esc(f.howToCheck)}</p>` : ''}
      <div class="table-wrap"><table class="compact">
        <thead><tr><th>Source</th><th>Link</th></tr></thead>
        <tbody>${(f.sources ?? []).map((s) => `<tr><td>${esc(s.label)}</td><td class="src">${sourceLink(s.url, 'open')}</td></tr>`).join('') || `<tr><td colspan="2" class="empty">No source recorded for this flag.</td></tr>`}</tbody>
      </table></div>
    </div>
  </details>`).join('');
  // Re-open the one named in the URL fragment, so deep links from elsewhere land
  // on the right flag.
  const hash = location.hash.slice(1);
  if (hash) {
    const t = document.getElementById(hash);
    if (t) t.setAttribute('open', '');
  }
}

async function init() {
  try {
    const data = await loadLocal('data/flags.json');
    flags = data.flags ?? [];
  } catch (err) {
    renderBanner(document.getElementById('data-banner'), { state: 'error', headline: 'Flag registry failed to load', detail: err.message });
    return;
  }
  const counts = flags.reduce((acc, f) => { acc[f.severity] = (acc[f.severity] ?? 0) + 1; return acc; }, {});
  renderBanner(document.getElementById('data-banner'), {
    state: 'snapshot',
    headline: `${flags.length} flags published`,
    detail: `${counts.high ?? 0} high · ${counts.medium ?? 0} medium · ${counts.low ?? 0} low · ${counts.info ?? 0} info. All are open for challenge.`,
  });
  render();
}

document.getElementById('sev-filter')?.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-sev]');
  if (!btn) return;
  sev = btn.dataset.sev;
  for (const b of document.querySelectorAll('#sev-filter button')) b.setAttribute('aria-pressed', String(b === btn));
  render();
});

init();
