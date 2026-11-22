<section>
  <h1>Markets</h1>
  <p class="muted" style="max-width:85ch">
    Every market this dashboard tracks, grouped by topic, with the exchange's own status and
    result. Events stay inside their topic and markets stay grouped under their event, which is
    how the brief asked for it to be organised.
  </p>
  <div class="banner" id="data-banner" data-state="snapshot" role="status" aria-live="polite">
    <span class="led" aria-hidden="true"></span><strong>Loading…</strong>
  </div>
</section>

<section class="toolbar">
  <div class="seg" id="state-filter" role="group" aria-label="Filter by state">
    <button data-state="all" aria-pressed="true">All</button>
    <button data-state="open" aria-pressed="false">Open</button>
    <button data-state="resolved" aria-pressed="false">Resolved</button>
    <button data-state="awaiting" aria-pressed="false">Awaiting result</button>
  </div>
  <input type="search" id="q" placeholder="Filter by title or ticker…" aria-label="Filter markets" style="min-width:240px">
</section>

<section id="groups" class="stack"></section>

<section>
  <h2>Status meanings</h2>
  <div class="table-wrap"><table class="compact">
    <thead><tr><th>Exchange status</th><th>What it means</th><th>Source</th></tr></thead>
    <tbody>
      <tr><td class="mono">active</td><td>Open for trading.</td><td class="src"><a href="https://docs.kalshi.com/getting_started/market_lifecycle" target="_blank" rel="noopener noreferrer nofollow">market lifecycle</a></td></tr>
      <tr><td class="mono">inactive</td><td>Trading paused by the exchange; the market has not closed.</td><td class="src"><a href="https://docs.kalshi.com/getting_started/market_lifecycle" target="_blank" rel="noopener noreferrer nofollow">market lifecycle</a></td></tr>
      <tr><td class="mono">closed</td><td>Past close time, awaiting determination.</td><td class="src"><a href="https://docs.kalshi.com/getting_started/market_lifecycle" target="_blank" rel="noopener noreferrer nofollow">market lifecycle</a></td></tr>
      <tr><td class="mono">determined</td><td>Result known, settlement timer running; can still be disputed.</td><td class="src"><a href="https://docs.kalshi.com/getting_started/market_lifecycle" target="_blank" rel="noopener noreferrer nofollow">market lifecycle</a></td></tr>
      <tr><td class="mono">finalized</td><td>Settlement complete and positions paid out. Terminal.</td><td class="src"><a href="https://docs.kalshi.com/getting_started/market_lifecycle" target="_blank" rel="noopener noreferrer nofollow">market lifecycle</a></td></tr>
    </tbody>
  </table></div>
</section>

<script type="module" src="[[ASSET]]assets/markets-page.js"></script>
