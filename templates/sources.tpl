<section>
  <h1>Sources</h1>
  <p class="muted" style="max-width:85ch">
    Four kinds of claim appear on this site and they are kept apart. <strong>Official documentation</strong>
    is Kalshi's own docs. <strong>Live API observations</strong> are responses read from the demo API on the
    date shown, with the exact request. <strong>Primary data publishers</strong> are third parties that
    Kalshi's own series records name as settlement sources. <strong>Project rules</strong> are choices
    made for this dashboard, and they are never presented as exchange facts.
  </p>
  <div class="banner" id="data-banner" data-state="snapshot" role="status" aria-live="polite">
    <span class="led" aria-hidden="true"></span><strong>Loading…</strong>
  </div>
</section>

<section>
  <h2>Official Kalshi documentation</h2>
  <div class="table-wrap"><table class="compact" id="docs-table">
    <thead><tr><th>ID</th><th>Page</th><th>What it establishes</th><th>Link</th></tr></thead>
    <tbody><tr><td colspan="4" class="empty">Loading…</td></tr></tbody>
  </table></div>
</section>

<section>
  <h2>Live API observations</h2>
  <p class="small" style="max-width:85ch">
    Each row is one request made on the date shown, and what came back. These are point-in-time
    reads: the demo catalogue changes, so a link may return something different today. That is the
    honest reading of a live source.
  </p>
  <div class="table-wrap"><table class="compact" id="api-table">
    <thead><tr><th>ID</th><th>Request</th><th>Observed</th><th>What came back</th><th>Link</th></tr></thead>
    <tbody><tr><td colspan="5" class="empty">Loading…</td></tr></tbody>
  </table></div>
</section>

<section>
  <h2>Primary data publishers named by the exchange</h2>
  <div class="table-wrap"><table class="compact" id="pub-table">
    <thead><tr><th>ID</th><th>Publisher</th><th>Why it is here</th><th>Link</th></tr></thead>
    <tbody><tr><td colspan="4" class="empty">Loading…</td></tr></tbody>
  </table></div>
</section>

<section>
  <h2>Project rules</h2>
  <p class="small" style="max-width:85ch">
    These are not Kalshi facts. They are the rules this dashboard invented to do what was asked, and
    each one says where it lives in the code so you can read or change it.
  </p>
  <div class="table-wrap"><table class="compact" id="rules-table">
    <thead><tr><th>ID</th><th>Rule</th><th>Where</th><th>What it says</th></tr></thead>
    <tbody><tr><td colspan="4" class="empty">Loading…</td></tr></tbody>
  </table></div>
</section>

<section>
  <h2>Endpoints this dashboard uses</h2>
  <div class="table-wrap"><table class="compact">
    <thead><tr><th>Endpoint</th><th>Used for</th><th>Auth</th><th>Source</th></tr></thead>
    <tbody>
      <tr><td class="mono">GET /exchange/status</td><td>Confirming the exchange is up before collecting</td><td>none</td><td class="src"><a href="https://docs.kalshi.com/api-reference/exchange/get-exchange-status" target="_blank" rel="noopener noreferrer nofollow">docs</a></td></tr>
      <tr><td class="mono">GET /series</td><td>Discovering the five topics by category and tag</td><td>none</td><td class="src"><a href="https://docs.kalshi.com/api-reference/market/get-series-list" target="_blank" rel="noopener noreferrer nofollow">docs</a></td></tr>
      <tr><td class="mono">GET /markets</td><td>Open markets per series, and historical status</td><td>none</td><td class="src"><a href="https://docs.kalshi.com/api-reference/market/get-markets" target="_blank" rel="noopener noreferrer nofollow">docs</a></td></tr>
      <tr><td class="mono">GET /markets/{ticker}</td><td>Re-reading a tracked market to catch its final result</td><td>none</td><td class="src"><a href="https://docs.kalshi.com/api-reference/market/get-market" target="_blank" rel="noopener noreferrer nofollow">docs</a></td></tr>
      <tr><td class="mono">GET /markets/{ticker}/orderbook</td><td>Depth, spread, and the liquidity ladder</td><td>none</td><td class="src"><a href="https://docs.kalshi.com/api-reference/market/get-market-orderbook" target="_blank" rel="noopener noreferrer nofollow">docs</a></td></tr>
      <tr><td class="mono">GET /portfolio/balance</td><td>Demo account balance snapshot</td><td>signed</td><td class="src"><a href="https://docs.kalshi.com/api-reference/portfolio/get-balance" target="_blank" rel="noopener noreferrer nofollow">docs</a></td></tr>
      <tr><td class="mono">GET /portfolio/positions</td><td>Demo account positions</td><td>signed</td><td class="src"><a href="https://docs.kalshi.com/api-reference/portfolio/get-positions" target="_blank" rel="noopener noreferrer nofollow">docs</a></td></tr>
      <tr><td class="mono">GET /portfolio/fills</td><td>Demo account fills</td><td>signed</td><td class="src"><a href="https://docs.kalshi.com/api-reference/portfolio/get-fills" target="_blank" rel="noopener noreferrer nofollow">docs</a></td></tr>
      <tr><td class="mono">GET /portfolio/settlements</td><td>Demo account settlements</td><td>signed</td><td class="src"><a href="https://docs.kalshi.com/api-reference/portfolio/get-settlements" target="_blank" rel="noopener noreferrer nofollow">docs</a></td></tr>
    </tbody>
  </table></div>
</section>

<script type="module" src="[[ASSET]]assets/sources-page.js"></script>
