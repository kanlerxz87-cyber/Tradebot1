<section>
  <h1>Strategies and how they are tested</h1>
  <p class="muted" style="max-width:85ch">
    Five rules, each stated exactly as the code implements it so a reader can reproduce or refute
    any simulated trade by hand. Every one trades one contract at a time, pays Kalshi's published
    taker fee, and settles only on a finalized binary result.
  </p>
  <div class="banner" id="data-banner" data-state="snapshot" role="status" aria-live="polite">
    <span class="led" aria-hidden="true"></span><strong>Loading…</strong>
  </div>
</section>

<section class="stack">
  <article class="card" id="momentum">
    <div class="toolbar" style="margin-bottom:6px"><h2 style="margin:0">1 · Momentum (buy the move)</h2><span class="badge info">buy YES</span></div>
    <p><strong>Thesis.</strong> A verified move of at least $0.10 continues for the rest of the observed window more often than not.</p>
    <p><strong>The rule, exactly.</strong> When the last observed mid-price is at least $0.10 above the previous observation, buy YES at the best derived YES ask, provided the ask is at most $0.90 and no position is already open in that market.</p>
    <div class="table-wrap"><table class="compact">
      <thead><tr><th>Input</th><th>What it means</th><th>Source</th></tr></thead>
      <tbody>
        <tr><td>mid-price</td><td>(YES bid + YES ask) / 2 from consecutive polls</td><td class="src"><a href="https://docs.kalshi.com/api-reference/market/get-market-orderbook" target="_blank" rel="noopener noreferrer nofollow">orderbook</a></td></tr>
        <tr><td>YES ask</td><td>Derived as 1 − best NO bid, because Kalshi returns bids only</td><td class="src"><a href="https://docs.kalshi.com/getting_started/orderbook_responses" target="_blank" rel="noopener noreferrer nofollow">mechanics</a></td></tr>
        <tr><td>fee</td><td>round up(0.07 × C × P × (1−P)), rounded to the whole cent</td><td class="src"><a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf" target="_blank" rel="noopener noreferrer nofollow">fee schedule</a></td></tr>
      </tbody>
    </table></div>
  </article>

  <article class="card" id="fade">
    <div class="toolbar" style="margin-bottom:6px"><h2 style="margin:0">2 · Fade (sell the spike)</h2><span class="badge info">buy NO</span></div>
    <p><strong>Thesis.</strong> A large move away from the middle is more likely to retrace than to extend.</p>
    <p><strong>The rule, exactly.</strong> When the last observed mid is at least $0.10 above the previous observation and the new mid is above $0.60, buy NO at the best derived NO ask, provided that ask is at most $0.90.</p>
    <p class="small dim">Buying NO at q is the same contract as selling YES at 1−q; the NO ask comes from the YES bids on the book.</p>
  </article>

  <article class="card" id="dipbuy">
    <div class="toolbar" style="margin-bottom:6px"><h2 style="margin:0">3 · Dip buyer</h2><span class="badge info">buy YES</span></div>
    <p><strong>Thesis.</strong> A fall of at least $0.10 in a market still above $0.30 is an overreaction.</p>
    <p><strong>The rule, exactly.</strong> When the last observed mid is at least $0.10 below the previous observation and still above $0.30, buy YES at the best YES ask, provided the ask is at most $0.90.</p>
  </article>

  <article class="card" id="longshot">
    <div class="toolbar" style="margin-bottom:6px"><h2 style="margin:0">4 · Longshot collector</h2><span class="badge info">buy YES</span></div>
    <p><strong>Thesis.</strong> Very cheap contracts are systematically underpriced relative to their true probability. This one is deliberately included as a thesis the data can refute.</p>
    <p><strong>The rule, exactly.</strong> When the best YES ask is at most $0.05 and at least 100 contracts rest at that price, buy YES at the ask.</p>
  </article>

  <article class="card" id="favorite">
    <div class="toolbar" style="margin-bottom:6px"><h2 style="margin:0">5 · Favorite carry</h2><span class="badge info">buy YES</span></div>
    <p><strong>Thesis.</strong> Markets already priced above 85 cents are more often right than wrong, and the edge is the carry.</p>
    <p><strong>The rule, exactly.</strong> When the best YES ask is between $0.85 and $0.95 inclusive and the spread is at most $0.02, buy YES at the ask.</p>
  </article>
</section>

<section>
  <h2>Accounting rules, stated once</h2>
  <div class="table-wrap"><table class="compact">
    <thead><tr><th>Rule</th><th>Value</th><th>Source or note</th></tr></thead>
    <tbody>
      <tr><td>Starting cash</td><td class="mono">$1,000.00</td><td class="src">Project choice (<a href="[[ASSET]]flagged.html#F-13">F-13</a>), not Kalshi cash</td></tr>
      <tr><td>Size</td><td class="mono">1 contract per entry</td><td class="src">Deliberate floor so a strategy's edge is visible without position sizing — <a href="https://github.com/kanlerxz87-cyber/Tradebot1/blob/main/tools/strategies.mjs" target="_blank" rel="noopener noreferrer nofollow">tools/strategies.mjs</a></td></tr>
      <tr><td>Entry price</td><td class="mono">best ask on the side bought</td><td class="src"><a href="https://docs.kalshi.com/getting_started/orderbook_responses" target="_blank" rel="noopener noreferrer nofollow">derived ask</a></td></tr>
      <tr><td>Fee</td><td class="mono">published taker fee × the series multiplier</td><td class="src"><a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf" target="_blank" rel="noopener noreferrer nofollow">fee schedule</a></td></tr>
      <tr><td>Mark to market</td><td class="mono">exit at the bid of the side held</td><td class="src">No assumed last price; an empty book means no mark — <a href="https://github.com/kanlerxz87-cyber/Tradebot1/blob/main/tools/strategies.mjs" target="_blank" rel="noopener noreferrer nofollow">tools/strategies.mjs</a></td></tr>
      <tr><td>Settlement</td><td class="mono">$1 or $0 per contract</td><td class="src"><a href="https://docs.kalshi.com/getting_started/market_lifecycle" target="_blank" rel="noopener noreferrer nofollow">finalized result only</a></td></tr>
      <tr><td>Concurrency</td><td class="mono">one open position per market</td><td class="src"><a href="https://github.com/kanlerxz87-cyber/Tradebot1/blob/main/tools/collector.mjs" target="_blank" rel="noopener noreferrer nofollow">tools/collector.mjs</a></td></tr>
    </tbody>
  </table></div>
</section>

<section>
  <h2>Current results by strategy</h2>
  <p class="small">Read straight from the committed simulator record. An empty table means no rule has fired yet, not a zero return.</p>
  <div class="table-wrap"><table class="compact" id="results">
    <thead><tr><th>Strategy</th><th class="num">Trades</th><th class="num">Settled</th><th class="num">Wins</th><th class="num">Realized P&amp;L</th><th>Record</th></tr></thead>
    <tbody><tr><td colspan="6" class="empty">Loading…</td></tr></tbody>
  </table></div>
</section>

<section class="notice warn">
  <p><strong>What this cannot tell you.</strong> Five strategies on demo data, one contract each, with
  no backtest and no statistical significance. Kalshi warns that demo prices may not reflect real
  markets. Treat the results as a plumbing test for the accounting, which is what they are, and not
  as evidence that any rule makes money.</p>
</section>

<script type="module" src="[[ASSET]]assets/strategies-page.js"></script>
