<section>
  <p class="small"><a href="[[ASSET]]index.html">Board</a> / <a href="[[ASSET]]markets.html">Markets</a> / <span id="crumb">market</span></p>
  <h1 id="m-title">Market</h1>
  <div class="pill-row" style="margin-bottom:10px">
    <span class="badge" id="m-topic">—</span>
    <span class="badge mono" id="m-ticker">—</span>
    <span class="badge" id="m-status">—</span>
    <span class="badge" id="m-result">—</span>
  </div>
  <p class="muted" id="m-rules" style="max-width:85ch"></p>
  <div class="banner" id="data-banner" data-state="snapshot" role="status" aria-live="polite">
    <span class="led" aria-hidden="true"></span><strong>Loading…</strong>
  </div>
</section>

<section class="grid cols-4" aria-label="Market figures">
  <div class="card tight"><div class="stat"><span class="k">YES bid</span><span class="v" id="m-bid">—</span><span class="s">best bid on the book</span></div></div>
  <div class="card tight"><div class="stat"><span class="k">YES ask (derived)</span><span class="v" id="m-ask">—</span><span class="s">1 − best NO bid</span></div></div>
  <div class="card tight"><div class="stat"><span class="k">Spread</span><span class="v" id="m-spread">—</span><span class="s">ask − bid</span></div></div>
  <div class="card tight"><div class="stat"><span class="k">24h volume</span><span class="v" id="m-volume">—</span><span class="s">contracts, exchange field</span></div></div>
</section>

<section>
  <div class="toolbar" style="margin-bottom:10px">
    <h2 style="margin:0">Price</h2>
    <div class="seg" id="window-toggle" role="group" aria-label="Chart window">
      <button data-win="60s" aria-pressed="false">60s</button>
      <button data-win="5m" aria-pressed="false">5m</button>
      <button data-win="15m" aria-pressed="false">15m</button>
      <button data-win="1h" aria-pressed="true">1h</button>
      <button data-win="6h" aria-pressed="false">6h</button>
      <button data-win="24h" aria-pressed="false">24h</button>
    </div>
    <label class="small dim" style="margin-left:auto"><input type="checkbox" id="show-alerts" checked> mark recorded swings</label>
  </div>
  <div class="chart-shell">
    <canvas class="chart" id="chart" aria-label="YES contract price over time. X axis is time, Y axis is price in cents." role="img"></canvas>
    <div class="chart-legend">
      <span><i style="background:#22c98a"></i>YES mid-price (bid+ask)/2</span>
      <span><i style="background:#2fbf71"></i>dashed: recorded upward swing</span>
      <span><i style="background:#ef5b5b"></i>dashed: recorded downward swing</span>
      <span class="dim">Gaps are gaps: nothing is drawn where no observation exists.</span>
    </div>
  </div>
  <p class="small dim" id="chart-note"></p>
</section>

<section>
  <h2>Liquidity: how many contracts at each price</h2>
  <p class="small" style="max-width:85ch">
    Kalshi returns <strong>bids only</strong>. A YES bid at a price is a NO ask at one dollar minus
    that price, so the ask columns below are <em>derived</em> and labelled as such. Quantity is in
    contracts at each price level, exactly as the exchange reports it.
    <a href="https://docs.kalshi.com/getting_started/orderbook_responses" target="_blank" rel="noopener noreferrer nofollow">Kalshi: order-book responses ↗</a>
  </p>
  <div class="ladder">
    <div class="card tight">
      <h3 class="up" style="margin-bottom:8px">Bids on YES</h3>
      <table class="compact"><thead><tr><th>Price</th><th class="num">Contracts</th><th class="num">$ notional</th><th>Depth</th><th>Source</th></tr></thead>
      <tbody id="ladder-yes"><tr><td colspan="5" class="empty">No bids.</td></tr></tbody></table>
    </div>
    <div class="card tight">
      <h3 class="down" style="margin-bottom:8px">Asks on YES <span class="badge">derived</span></h3>
      <table class="compact"><thead><tr><th>Price</th><th class="num">Contracts</th><th class="num">$ notional</th><th>Depth</th><th>Source</th></tr></thead>
      <tbody id="ladder-ask"><tr><td colspan="5" class="empty">No NO bids, so no YES asks.</td></tr></tbody></table>
    </div>
  </div>
  <div class="grid cols-3" style="margin-top:14px">
    <div class="card tight"><div class="stat"><span class="k">Contracts bid for YES</span><span class="v" id="depth-bid">—</span><span class="s">sum across all levels</span></div></div>
    <div class="card tight"><div class="stat"><span class="k">Contracts offered on YES</span><span class="v" id="depth-ask">—</span><span class="s">derived from NO bids</span></div></div>
    <div class="card tight"><div class="stat"><span class="k">Open interest</span><span class="v" id="m-oi">—</span><span class="s">exchange field</span></div></div>
  </div>
</section>

<section>
  <h2>Paper trade this market</h2>
  <p class="small" style="max-width:85ch">
    A local simulation only. It never touches your Kalshi account, sends no order, and is not
    stored anywhere but this browser. The fee charged is Kalshi's published taker fee for the
    price and size you enter.
  </p>
  <div class="card">
    <div class="toolbar">
      <label>Side
        <select id="pt-side"><option value="yes">Buy YES</option><option value="no">Buy NO</option></select>
      </label>
      <label>Contracts <input type="text" id="pt-count" value="10" size="5" inputmode="numeric"></label>
      <label>Limit price <input type="text" id="pt-price" value="" size="7" inputmode="decimal"></label>
      <button class="seg" style="padding:0" type="button" id="pt-run"><span style="padding:6px 12px;font-weight:600">Simulate fill</span></button>
    </div>
    <div id="pt-out" style="margin-top:12px"></div>
  </div>
</section>

<section>
  <h2>Resolution</h2>
  <p class="small" style="max-width:85ch">
    A market is resolved only when the exchange marks it <code>finalized</code> and sets
    <code>result</code> to <code>yes</code> or <code>no</code>. <code>determined</code> is not final:
    the docs say a result can still be disputed.
    <a href="https://docs.kalshi.com/getting_started/market_lifecycle" target="_blank" rel="noopener noreferrer nofollow">Kalshi: market lifecycle ↗</a>
  </p>
  <div class="table-wrap"><table class="compact" id="res-table">
    <thead><tr><th>Status</th><th>Result</th><th>Checked</th><th>Settlement time</th><th>Source</th></tr></thead>
    <tbody><tr><td colspan="5" class="empty">No resolution record for this market yet.</td></tr></tbody>
  </table></div>
</section>

<section>
  <h2>Contract details</h2>
  <div class="table-wrap"><table class="compact" id="m-details">
    <thead><tr><th>Field</th><th>Value</th><th>Where it comes from</th></tr></thead>
    <tbody></tbody>
  </table></div>
</section>

<script type="module" src="[[ASSET]]assets/market-page.js"></script>
