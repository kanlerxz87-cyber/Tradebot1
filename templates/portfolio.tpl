<section>
  <div class="pill-row" style="margin-bottom:8px">
    <span class="badge warn">simulation</span>
    <span class="badge">one contract per entry</span>
    <span class="badge">taker fees charged</span>
  </div>
  <h1>Simulated portfolio</h1>
  <p class="muted" style="max-width:85ch">
    Five strategies trading one contract at a time against demo market data, with the published
    taker fee charged on every entry. Positions settle only when the exchange finalizes a
    <code>yes</code> or <code>no</code> result. This is a test harness, not performance a real
    account would have earned.
  </p>
  <div class="banner" id="data-banner" data-state="snapshot" role="status" aria-live="polite">
    <span class="led" aria-hidden="true"></span><strong>Loading…</strong>
  </div>
</section>

<section class="grid cols-5" aria-label="Portfolio figures">
  <div class="card tight"><div class="stat"><span class="k">Equity</span><span class="v" id="p-equity">—</span><span class="s" id="p-equity-sub">starting cash + realized + unrealized</span></div></div>
  <div class="card tight"><div class="stat"><span class="k">Realized P&amp;L</span><span class="v" id="p-realized">—</span><span class="s">settled positions only</span></div></div>
  <div class="card tight"><div class="stat"><span class="k">Unrealized</span><span class="v" id="p-unrealized">—</span><span class="s">marked at the exit side of the book</span></div></div>
  <div class="card tight"><div class="stat"><span class="k">Fees paid</span><span class="v" id="p-fees">—</span><span class="s">published taker fee</span></div></div>
  <div class="card tight"><div class="stat"><span class="k">Win rate</span><span class="v" id="p-winrate">—</span><span class="s" id="p-winrate-sub">no settled trades yet</span></div></div>
</section>

<section>
  <h2>Equity curve</h2>
  <p class="small">Cumulative realized P&amp;L in dollars, plotted at the time each position settled. With no settled positions there is no curve, and none is drawn.</p>
  <div class="chart-shell"><canvas class="chart" id="equity-chart" role="img" aria-label="Realized profit and loss over time"></canvas></div>
</section>

<section>
  <div class="toolbar" style="margin-bottom:10px">
    <h2 style="margin:0">By strategy</h2>
    <span class="badge" id="p-positions">—</span>
  </div>
  <div class="table-wrap"><table class="compact" id="strategy-table">
    <thead><tr><th>Strategy</th><th class="num">Trades</th><th class="num">Open</th><th class="num">Settled</th><th class="num">Wins</th><th class="num">Win rate</th><th class="num">Realized P&amp;L</th><th class="num">Fees</th><th>Rule source</th></tr></thead>
    <tbody><tr><td colspan="9" class="empty">Loading…</td></tr></tbody>
  </table></div>
</section>

<section>
  <div class="toolbar" style="margin-bottom:10px">
    <h2 style="margin:0">By topic</h2>
  </div>
  <div class="table-wrap"><table class="compact" id="topic-table">
    <thead><tr><th>Topic</th><th class="num">Trades</th><th class="num">Settled</th><th class="num">Wins</th><th class="num">Realized P&amp;L</th><th class="num">Fees</th></tr></thead>
    <tbody><tr><td colspan="6" class="empty">Loading…</td></tr></tbody>
  </table></div>
</section>

<section>
  <div class="toolbar" style="margin-bottom:10px">
    <h2 style="margin:0">Positions</h2>
    <div class="seg" id="pos-filter" role="group" aria-label="Filter positions">
      <button data-f="all" aria-pressed="true">All</button>
      <button data-f="open" aria-pressed="false">Open</button>
      <button data-f="settled" aria-pressed="false">Settled</button>
    </div>
  </div>
  <div class="table-wrap"><table class="compact" id="positions-table">
    <thead><tr>
      <th>Opened</th><th>Market</th><th>Strategy</th><th>Side</th><th class="num">Price</th><th class="num">Contracts</th>
      <th class="num">Cost</th><th class="num">Fee</th><th>Status</th><th class="num">P&amp;L</th><th>Source</th>
    </tr></thead>
    <tbody><tr><td colspan="11" class="empty">Loading…</td></tr></tbody>
  </table></div>
</section>

<section class="notice">
  <p><strong>The demo account's real balance is not here.</strong> This page is the simulator. The
  authenticated demo-account snapshot, captured by GitHub Actions from repository secrets, is on
  <a href="[[ASSET]]demo-account.html">the demo account page</a>. The two are deliberately kept
  apart: the simulator's $1,000 is a project choice, not Kalshi cash (flag
  <a href="[[ASSET]]flagged.html#F-13">F-13</a>).</p>
</section>

<script type="module" src="[[ASSET]]assets/portfolio-page.js"></script>
