<section>
  <p class="small"><a href="[[ASSET]]index.html">Board</a> / topic</p>
  <h1>[[TITLE]]</h1>
  <p class="muted" id="cat-blurb" style="max-width:85ch"></p>
  <div class="banner" id="data-banner" data-state="snapshot" role="status" aria-live="polite">
    <span class="led" aria-hidden="true"></span><strong>Loading…</strong>
  </div>
</section>

<section class="grid cols-4" aria-label="Topic figures">
  <div class="card tight"><div class="stat"><span class="k">Series found</span><span class="v" id="cat-series">—</span><span class="s">via the official filters</span></div></div>
  <div class="card tight"><div class="stat"><span class="k">Open markets</span><span class="v" id="cat-markets">—</span><span class="s">with a live price</span></div></div>
  <div class="card tight"><div class="stat"><span class="k">Recorded swings</span><span class="v" id="cat-alerts">—</span><span class="s">≥ $0.10 in either direction</span></div></div>
  <div class="card tight"><div class="stat"><span class="k">Resolved yes / no</span><span class="v" id="cat-resolved">—</span><span class="s">finalized only</span></div></div>
</section>

<section>
  <h2>How this topic is found</h2>
  <p class="small" style="max-width:85ch">
    These are the exact requests the collector makes. No keyword matching is used to classify a
    market: a market lands in a topic because Kalshi's own series record says so.
  </p>
  <div class="table-wrap"><table class="compact" id="discovery-table">
    <thead><tr><th>Filter</th><th>Request</th><th>What came back</th><th>Source</th></tr></thead>
    <tbody></tbody>
  </table></div>
</section>

<section>
  <h2>Events and markets</h2>
  <p class="small">Events are grouped; every market under an event stays with it.</p>
  <div id="cat-groups" class="stack"><div class="card empty">Loading…</div></div>
</section>

<section>
  <h2>Resolved events</h2>
  <p class="small" style="max-width:85ch">
    A row appears here only when the exchange has marked the market <code>finalized</code> and
    published a <code>yes</code> or <code>no</code> result. Anything earlier is "awaiting".
  </p>
  <div class="table-wrap"><table class="compact" id="cat-resolutions">
    <thead><tr><th>Market</th><th>Status</th><th>Result</th><th>Checked</th><th>Settled</th><th>Source</th></tr></thead>
    <tbody><tr><td colspan="6" class="empty">No finalized market in this topic yet.</td></tr></tbody>
  </table></div>
</section>

<section>
  <h2>Where results will be reported</h2>
  <p class="small" style="max-width:85ch">The settlement sources Kalshi names for this topic's series. This is where an outcome is published, not a claim about why a price moved.</p>
  <div class="table-wrap"><table class="compact" id="sources-table">
    <thead><tr><th>Source</th><th>Series that name it</th><th>Link</th></tr></thead>
    <tbody><tr><td colspan="3" class="empty">No settlement sources recorded for this topic.</td></tr></tbody>
  </table></div>
</section>

<section>
  <h2>Recorded swings in this topic</h2>
  <div class="table-wrap"><table class="compact" id="cat-alert-table">
    <thead><tr><th>Observed</th><th>Market</th><th class="num">From</th><th class="num">To</th><th class="num">Change</th><th class="num">Score</th><th>Source</th></tr></thead>
    <tbody><tr><td colspan="7" class="empty">No swing recorded in this topic yet.</td></tr></tbody>
  </table></div>
</section>

<script type="module" src="[[ASSET]]assets/topic-page.js"></script>
