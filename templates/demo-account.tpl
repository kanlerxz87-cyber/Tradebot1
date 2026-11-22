<section>
  <div class="pill-row" style="margin-bottom:8px">
    <span class="badge" id="conn-badge">checking…</span>
    <span class="badge">authenticated snapshot</span>
    <span class="badge">GitHub Actions only</span>
  </div>
  <h1>Kalshi demo account</h1>
  <p class="muted" style="max-width:85ch">
    The real balance, positions, fills and settlements of the demo account, read with signed
    requests from a GitHub Actions job and committed to the repository. A static site cannot sign a
    Kalshi request, so this page can only show what that job last captured, with the time it ran.
  </p>
  <div class="banner" id="data-banner" data-state="snapshot" role="status" aria-live="polite">
    <span class="led" aria-hidden="true"></span><strong>Loading…</strong>
  </div>
</section>

<section id="not-connected" hidden>
  <div class="notice warn">
    <h2 style="margin-top:0">Not connected</h2>
    <p id="nc-reason">No authenticated read has been made.</p>
    <p><strong>What that means:</strong> nothing on this page is a balance. The simulator on the
    <a href="[[ASSET]]portfolio.html">portfolio page</a> is separate and is also not Kalshi cash.</p>
    <h3>To connect it</h3>
    <ol id="nc-steps" style="margin:0; padding-left:20px"></ol>
    <p class="small" style="margin-top:10px" id="nc-docs"></p>
  </div>
</section>

<section id="connected" hidden class="stack">
  <div class="grid cols-4">
    <div class="card tight"><div class="stat"><span class="k">Balance</span><span class="v" id="acct-balance">—</span><span class="s" id="acct-balance-sub"></span></div></div>
    <div class="card tight"><div class="stat"><span class="k">Portfolio value</span><span class="v" id="acct-pv">—</span><span class="s">from GET /portfolio/balance</span></div></div>
    <div class="card tight"><div class="stat"><span class="k">Positions</span><span class="v" id="acct-pos">—</span><span class="s">non-zero holdings</span></div></div>
    <div class="card tight"><div class="stat"><span class="k">Fills captured</span><span class="v" id="acct-fills">—</span><span class="s">most recent page</span></div></div>
  </div>

  <div>
    <h2>Positions</h2>
    <div class="table-wrap"><table class="compact" id="acct-pos-table">
      <thead><tr><th>Ticker</th><th class="num">Contracts</th><th class="num">Exposure</th><th class="num">Realized P&amp;L</th><th class="num">Fees</th><th>Source</th></tr></thead>
      <tbody></tbody>
    </table></div>
  </div>

  <div>
    <h2>Fills</h2>
    <div class="table-wrap"><table class="compact" id="acct-fill-table">
      <thead><tr><th>Time</th><th>Ticker</th><th>Side</th><th class="num">Price</th><th class="num">Contracts</th><th>Source</th></tr></thead>
      <tbody></tbody>
    </table></div>
  </div>

  <div>
    <h2>Settlements</h2>
    <div class="table-wrap"><table class="compact" id="acct-settle-table">
      <thead><tr><th>Time</th><th>Ticker</th><th>Result</th><th class="num">Revenue</th><th>Source</th></tr></thead>
      <tbody></tbody>
    </table></div>
  </div>
</section>

<section>
  <h2>Why this is not done in the browser</h2>
  <div class="table-wrap"><table class="compact">
    <thead><tr><th>Requirement</th><th>Why a Pages site cannot meet it</th><th>Source</th></tr></thead>
    <tbody>
      <tr><td>A private key to sign each request</td><td>GitHub Pages serves the JavaScript to everyone; any key in it is public.</td><td class="src"><a href="https://docs.kalshi.com/getting_started/api_keys" target="_blank" rel="noopener noreferrer nofollow">API keys</a></td></tr>
      <tr><td>Signature over timestamp + method + path</td><td>The signature must be produced with the private key, server-side.</td><td class="src"><a href="https://docs.kalshi.com/getting_started/api_keys" target="_blank" rel="noopener noreferrer nofollow">signing</a></td></tr>
      <tr><td>Timestamp within 30 seconds</td><td>Needs a synchronised clock at signing time, which a cached page does not have.</td><td class="src"><a href="https://docs.kalshi.com/getting_started/api_keys" target="_blank" rel="noopener noreferrer nofollow">signing</a></td></tr>
      <tr><td>Demo credentials only</td><td>Credentials are not shared between demo and production; the job refuses any non-demo root before it reads a key.</td><td class="src"><a href="https://docs.kalshi.com/getting_started/api_environments" target="_blank" rel="noopener noreferrer nofollow">environments</a></td></tr>
    </tbody>
  </table></div>
</section>

<section>
  <h2>About executing trades</h2>
  <p class="small" style="max-width:85ch">
    Live order placement needs the same signing, plus the V2 order endpoint. The signing job exists
    in this repository (<code>tools/demo-account.mjs</code>), and order placement is deliberately
    <strong>not</strong> wired up: nothing in this repository sends an order, ever. The simulated
    strategies are a local test harness. If order execution is added later, it belongs in the same
    Actions job with a hard demo-only guard, and the docs name
    <code>POST /portfolio/events/orders</code> as the endpoint.
  </p>
  <div class="table-wrap"><table class="compact">
    <thead><tr><th>Order field</th><th>Value</th><th>Source</th></tr></thead>
    <tbody>
      <tr><td><code>side</code></td><td>bid or ask, on a single book</td><td class="src"><a href="https://docs.kalshi.com/api-reference/orders/create-order-v2" target="_blank" rel="noopener noreferrer nofollow">Create Order V2</a></td></tr>
      <tr><td><code>price</code></td><td>fixed-point dollar string</td><td class="src"><a href="https://docs.kalshi.com/api-reference/orders/create-order-v2" target="_blank" rel="noopener noreferrer nofollow">Create Order V2</a></td></tr>
      <tr><td><code>count</code></td><td>fixed-point contract string, 0.01 minimum</td><td class="src"><a href="https://docs.kalshi.com/getting_started/fixed_point_migration" target="_blank" rel="noopener noreferrer nofollow">fixed point</a></td></tr>
      <tr><td><code>time_in_force</code></td><td>fill_or_kill, good_till_canceled, immediate_or_cancel</td><td class="src"><a href="https://docs.kalshi.com/api-reference/orders/create-order-v2" target="_blank" rel="noopener noreferrer nofollow">Create Order V2</a></td></tr>
      <tr><td>Legacy endpoint</td><td><code>/portfolio/orders</code> writes now return 410 Gone</td><td class="src"><a href="https://docs.kalshi.com/api-reference/orders/create-order-v2" target="_blank" rel="noopener noreferrer nofollow">Create Order V2</a></td></tr>
    </tbody>
  </table></div>
</section>

<script type="module" src="[[ASSET]]assets/demo-account.js"></script>
