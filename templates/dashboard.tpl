<section>
  <div class="pill-row" style="margin-bottom:8px">
    <span class="badge ok">swing threshold $0.10</span>
    <span class="badge">two feeds</span>
    <span class="badge">auto-refresh 30s</span>
  </div>
  <h1>Live alerts</h1>
  <p class="muted" style="max-width:80ch">
    Two scrolling feeds over the same observations. On the left, <strong>every</strong> recorded price
    swing of at least $0.10. On the right, the subset this dashboard's research score likes,
    ranked highest first. Both read the committed record that the scheduled collector writes,
    so the log keeps running when no browser is open.
  </p>
  <div class="banner" id="data-banner" data-state="snapshot" role="status" aria-live="polite">
    <span class="led" aria-hidden="true"></span><strong>Loading…</strong>
  </div>
</section>

<section class="notice">
  <p><strong>What is in the feeds right now.</strong> {{FEED_STATE}} An alert needs the
  <em>same</em> market observed at two different times, at least $0.10 apart, so a quiet feed
  is a measurement, not an omission.</p>
  <p class="small">Why no example row: a made-up row would be the one thing this project
  refuses to publish. See <a href="flagged.html#F-11">F-11</a> for how poll-to-poll detection
  can miss or split a move, and <a href="flagged.html#F-01">F-01</a> for why the authoring
  sandbox could not produce a second observation itself.</p>
</section>

<section class="grid cols-2">
  <div class="chat" aria-label="All swing alerts">
    <div class="chat-head">
      <h3>All swings ≥ $0.10</h3>
      <span class="badge" id="feed-a-count">0</span>
      <span class="count" id="feed-a-window"></span>
    </div>
    <div class="chat-body" id="feed-all" role="log" aria-live="polite" aria-relevant="additions"></div>
  </div>

  <div class="chat" aria-label="Model-filtered swing alerts">
    <div class="chat-head">
      <h3>Model-filtered <span class="badge info">heuristic</span></h3>
      <span class="badge" id="feed-b-count">0</span>
      <span class="count" id="feed-b-window"></span>
    </div>
    <div class="chat-body" id="feed-filtered" role="log" aria-live="polite" aria-relevant="additions"></div>
  </div>
</section>

<section class="notice warn">
  <p><strong>The right-hand feed is not a return forecast.</strong> It is ranked by a 0–100 score
  built from the size of the move, the contracts resting where you would have to trade, the
  spread, 24-hour volume and how fresh the observation is. There is no backtest behind it. The
  brief called this feed "high ROI"; calling a heuristic ROI would be false, so it is labelled a
  heuristic everywhere. The scoring rule is published in full on the
  <a href="[[ASSET]]methodology.html">Methodology</a> page and flagged as
  <a href="[[ASSET]]flagged.html#F-10">F-10</a>.</p>
</section>

<section>
  <h2>Why a swing happened</h2>
  <p class="small" style="max-width:85ch">
    No feed here claims a cause. Kalshi's API returns prices and volumes, never a reason. What each
    alert row gives you instead: the market and its order book, so you can see the book the move
    happened in, and the settlement sources Kalshi itself names for that contract, which is where
    the outcome will be reported. That is a starting point for research, not an attribution.
    See <a href="[[ASSET]]flagged.html#F-12">F-12</a>.
  </p>
  <div class="table-wrap">
    <table class="compact">
      <thead><tr><th>Source the exchange names</th><th>Used by</th><th>Link</th></tr></thead>
      <tbody>
        <tr><td>US Energy Information Administration — weekly retail diesel</td><td>Gas series (DIESEL, DIESELM)</td><td class="src"><a href="https://www.eia.gov/dnav/pet/PET_PRI_SPT_S1_D.htm" target="_blank" rel="noopener noreferrer nofollow">eia.gov</a></td></tr>
        <tr><td>CF Benchmarks</td><td>Crypto price series</td><td class="src"><a href="https://www.cfbenchmarks.com/" target="_blank" rel="noopener noreferrer nofollow">cfbenchmarks.com</a></td></tr>
        <tr><td>PGA Tour</td><td>Golf series</td><td class="src"><a href="https://www.pgatour.com/" target="_blank" rel="noopener noreferrer nofollow">pgatour.com</a></td></tr>
        <tr><td>ESPN golf</td><td>Golf series</td><td class="src"><a href="https://www.espn.com/golf/" target="_blank" rel="noopener noreferrer nofollow">espn.com/golf</a></td></tr>
        <tr><td>LIV Golf</td><td>KXLIVCOMPETE</td><td class="src"><a href="https://www.livgolf.com/" target="_blank" rel="noopener noreferrer nofollow">livgolf.com</a></td></tr>
      </tbody>
    </table>
  </div>
  <p class="small dim">Each row above is the settlement source Kalshi's own series record names; the list per series is on its topic page and in the raw API response.</p>
</section>

<section>
  <h2>Observation log</h2>
  <p class="small">The raw record behind both feeds, newest first. One row per observation cycle per market.</p>
  <div class="toolbar" style="margin-bottom:10px">
    <div class="seg" id="topic-filter" role="group" aria-label="Filter by topic">
      <button data-topic="all" aria-pressed="true">All</button>
      <button data-topic="gas" aria-pressed="false">Gas</button>
      <button data-topic="elections" aria-pressed="false">Elections</button>
      <button data-topic="culture" aria-pressed="false">Culture</button>
      <button data-topic="crypto" aria-pressed="false">Crypto</button>
      <button data-topic="golf" aria-pressed="false">Golf</button>
    </div>
    <label class="small dim" style="margin-left:auto">
      <input type="checkbox" id="only-qualifying" checked> only qualifying swings
    </label>
  </div>
  <div class="table-wrap">
    <table class="compact" id="obs-table">
      <thead><tr>
        <th>Observed</th><th>Market</th><th>Topic</th><th class="num">YES bid</th>
        <th class="num">YES ask</th><th class="num">Mid</th><th class="num">Δ vs previous</th><th>Source</th>
      </tr></thead>
      <tbody><tr><td colspan="8" class="empty">Loading…</td></tr></tbody>
    </table>
  </div>
</section>

<script type="module" src="[[ASSET]]assets/alerts-page.js"></script>
