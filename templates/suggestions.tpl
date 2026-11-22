<section>
  <h1>Suggestions to make this more live and more useful</h1>
  <p class="muted" style="max-width:85ch">
    The brief asked for suggestions on making the site more live, more interactive and easier to act
    on. Each item below says what it would change, what it costs, and what stands in the way today —
    including the ones this build already did.
  </p>
</section>

<section>
  <h2>Already done in this build</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Change</th><th>What it buys a trader</th><th>Where</th><th>Source of the constraint</th></tr></thead>
    <tbody>
      <tr><td>Two feeds side by side, all swings and filtered</td><td>You can watch the whole market and the shortlist at once without switching tabs</td><td><a href="[[ASSET]]dashboard.html">Alerts</a></td><td class="src"><a href="[[ASSET]]methodology.html">scoring</a></td></tr>
      <tr><td>Time windows from 60 seconds to 24 hours on one control</td><td>The same chart answers "what just happened" and "what is the trend"</td><td><a href="[[ASSET]]market.html">Market</a></td><td class="src"><a href="https://docs.kalshi.com/api-reference/market/get-market-candlesticks" target="_blank" rel="noopener noreferrer nofollow">candles</a></td></tr>
      <tr><td>Derived ask ladder with contract counts per price</td><td>You can see whether a move is tradeable size or a one-contract print</td><td><a href="[[ASSET]]market.html">Market</a></td><td class="src"><a href="https://docs.kalshi.com/getting_started/orderbook_responses" target="_blank" rel="noopener noreferrer nofollow">mechanics</a></td></tr>
      <tr><td>Every row carries its observation time, not the page-load time</td><td>You can tell a stale row from a live one at a glance</td><td>All tables</td><td class="src"><a href="[[ASSET]]flagged.html#F-11">F-11</a></td></tr>
      <tr><td>Empty states that say what is empty and why</td><td>An empty gas page reads as "no open markets", not "the site is broken"</td><td>Topic pages</td><td class="src"><a href="[[ASSET]]flagged.html#F-03">F-03</a></td></tr>
    </tbody>
  </table></div>
</section>

<section>
  <h2>Next, in the order I would do them</h2>
  <div class="table-wrap"><table data-nosource="true">
    <thead><tr><th>#</th><th>Suggestion</th><th>What it buys</th><th>Effort</th><th>Blocked by</th></tr></thead>
    <tbody>
      <tr><td>1</td><td>Run an authenticated WebSocket collector in Actions and commit the tick stream</td><td>Tick-level alerts instead of poll-level; catches spikes that revert between polls</td><td>Medium</td><td>Needs demo API key secrets; public WS still needs a signed handshake</td></tr>
      <tr><td>2</td><td>Add candles alongside the poll line, using the documented candlestick endpoint</td><td>Shows traded range (open/high/low/close) rather than only sampled quotes, including periods with no poll</td><td>Low</td><td>Needs a series ticker per market; candles lag a few seconds</td></tr>
      <tr><td>3</td><td>A per-market page that groups every alert and every simulated trade for that ticker on one timeline</td><td>One scroll answers "what has happened in this market and what did our rules do about it"</td><td>Low</td><td>None</td></tr>
      <tr><td>4</td><td>Backtest the five strategies over stored history before showing any of them as promising</td><td>Replaces "here are some rules" with "here is what the rules did over N observations"</td><td>Medium</td><td>Needs enough stored history; the collector must run for a while first</td></tr>
      <tr><td>5</td><td>Show the fee and break-even price on every row</td><td>A 2-cent edge is not an edge once the taker fee is counted; make that visible before you trade</td><td>Low</td><td>None</td></tr>
      <tr><td>6</td><td>Track a rolling "time to resolution" column and sort by it</td><td>Directs attention to markets that will actually settle soon, not 2099 contracts</td><td>Low</td><td>Depends on the exchange's close_time field</td></tr>
      <tr><td>7</td><td>Add a settlement watcher that announces a finalized yes/no in the chat feed</td><td>Closes the loop: you see the market you were watching resolve, in the same stream</td><td>Low</td><td>Already implemented in the collector; needs a resolved market to occur</td></tr>
      <tr><td>8</td><td>Replace the heuristic score with a calibrated model, or remove the second feed</td><td>Stops a heuristic from looking like a signal</td><td>High</td><td>Needs labelled outcomes; none exist yet</td></tr>
    </tbody>
  </table></div>
</section>

<section>
  <h2>Interface ideas that cost almost nothing</h2>
  <div class="grid cols-2">
    <div class="card">
      <h3>Keyboard-first alert triage</h3>
      <p class="small">J/K to move down the feed, Enter to open the market, S to star it. Traders keep hands on the keyboard; a dozen alerts during a move is where a mouse costs you.</p>
    </div>
    <div class="card">
      <h3>Pin a market to the top bar</h3>
      <p class="small">A sticky strip with the last price of three pinned markets, visible on every page. Cheap to build, and it turns five separate pages into one workspace.</p>
    </div>
    <div class="card">
      <h3>Show the alert's own context inline</h3>
      <p class="small">For each alert: the spread at the time, the contracts resting, and the fee for one contract at that price. That is the difference between "it moved" and "you could have traded it".</p>
    </div>
    <div class="card">
      <h3>Make empty states actionable</h3>
      <p class="small">When a topic has no open market, offer the nearest series that does, with a one-click jump. An empty page should suggest where to look next.</p>
    </div>
    <div class="card">
      <h3>Sound off by default, one alert sound available</h3>
      <p class="small">An audible cue for a qualifying swing, muted unless the reader turns it on. Never autoplay: a dashboard that beeps uninvited gets closed.</p>
    </div>
    <div class="card">
      <h3>Offline-first, with a visible read-only mode</h3>
      <p class="small">Cache the last successful API read and label it clearly when the network drops, instead of showing an error where the data should be.</p>
    </div>
  </div>
</section>

<section class="notice warn">
  <p><strong>What I would not add.</strong> A green "buy" badge, a confidence percentage, or a
  leaderboard of "best trades". Each of those turns an observation into advice, and this dashboard
  does not have the evidence to give advice. The brief's phrase "high ROI" is the exact pressure
  that produces those features; flag F-10 explains why this build refuses it and what it does
  instead.</p>
</section>
