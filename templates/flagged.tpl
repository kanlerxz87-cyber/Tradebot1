<section>
  <div class="pill-row" style="margin-bottom:8px">
    <span class="badge warn">published</span>
    <span class="badge">nothing here blocks the site</span>
  </div>
  <h1>Flagged for review</h1>
  <p class="muted" style="max-width:85ch">
    Every limitation, unverified value and irregularity found while building this dashboard. None of
    these are hidden elsewhere on the site; each one is also referenced in place. If you disagree with
    a flag, the source link next to it is where to check.
  </p>
  <div class="banner" id="data-banner" data-state="snapshot" role="status" aria-live="polite">
    <span class="led" aria-hidden="true"></span><strong>Loading…</strong>
  </div>
</section>

<section class="toolbar">
  <div class="seg" id="sev-filter" role="group" aria-label="Filter by severity">
    <button data-sev="all" aria-pressed="true">All</button>
    <button data-sev="high" aria-pressed="false">High</button>
    <button data-sev="medium" aria-pressed="false">Medium</button>
    <button data-sev="low" aria-pressed="false">Low</button>
    <button data-sev="info" aria-pressed="false">Info</button>
  </div>
</section>

<section id="flags" class="stack"></section>

<section>
  <h2>What "unverified" means on this site</h2>
  <div class="table-wrap"><table data-nosource="true">
    <thead><tr><th>Situation</th><th>What the site does</th></tr></thead>
    <tbody>
      <tr><td>A field the API did not return</td><td>Renders an em dash and is listed here if it matters</td></tr>
      <tr><td>A price with no two-sided book</td><td>No mid-price is computed; no move is reported</td></tr>
      <tr><td>A market with no stored observation</td><td>No chart line; the chart says how many points exist</td></tr>
      <tr><td>A topic with no open market</td><td>An empty state that names the reason and the flag</td></tr>
      <tr><td>A cause for a price move</td><td>Never stated; only the exchange's own settlement sources are linked</td></tr>
    </tbody>
  </table></div>
</section>

<script type="module" src="[[ASSET]]assets/flagged-page.js"></script>
