/* Live refresh for the root landing page.
   - The page is fully server-rendered by tools/build_landing.py, so it is readable with JS off.
   - With JS on, this re-reads the published desk snapshot every 60 seconds and re-renders the same
     markup, so the numbers move without a reload.
   - Nothing is fabricated: a failed fetch keeps the last good render and says so.
   - It only reads files the collector already publishes; it contains no market logic of its own.
*/
(function () {
  "use strict";

  var PREFIX = "docs/desk/data/";
  var THRESHOLD = 0.10;
  var TOPIC_LABEL = { gas: "Gas prices", elections: "Elections", culture: "Culture", crypto: "Crypto", golf: "Golf" };
  var TOPIC_ORDER = ["gas", "elections", "culture", "crypto", "golf"];

  var state = { snapshot: null, alerts: [], resolved: [], paper: null, lastError: "" };

  /* ------------------------------------------------------------- helpers */
  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function num(value, digits) {
    if (value === null || value === undefined || typeof value === "boolean" || isNaN(Number(value))) return "—";
    return Number(value).toLocaleString("en-US", { maximumFractionDigits: digits || 0 });
  }
  function usd(value, digits) {
    if (value === null || value === undefined || typeof value === "boolean" || isNaN(Number(value))) return "—";
    return "$" + Number(value).toLocaleString("en-US", { minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0 });
  }
  function cents(value) {
    if (value === null || value === undefined || typeof value === "boolean" || isNaN(Number(value))) return "—";
    return Math.round(Number(value) * 100) + "¢";
  }
  function signed(value, digits) {
    if (value === null || value === undefined || typeof value === "boolean" || isNaN(Number(value))) return "—";
    var n = Number(value);
    return (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: digits === undefined ? 2 : digits, maximumFractionDigits: digits === undefined ? 2 : digits });
  }
  function clamp(text, limit) {
    // Kalshi titles carry markdown emphasis ("**gas prices**"); stripping the markers is presentation only.
    var s = (text === null || text === undefined ? "" : String(text)).replace(/\*\*/g, "");
    return s.length > limit ? s.slice(0, limit - 1) + "…" : s;
  }
  function ageText(snapshot) {
    var stamp = snapshot && snapshot.generated_at;
    if (!stamp) return "no snapshot yet";
    var then = Date.parse(stamp);
    if (isNaN(then)) return "unknown age";
    var seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
    if (seconds < 90) return seconds + "s ago";
    if (seconds < 5400) return Math.round(seconds / 60) + "m ago";
    if (seconds < 172800) return Math.round(seconds / 3600) + "h ago";
    return Math.round(seconds / 86400) + "d ago";
  }
  function isStale(snapshot) {
    var stamp = snapshot && snapshot.generated_at;
    if (!stamp) return true;
    var then = Date.parse(stamp);
    if (isNaN(then)) return true;
    return (Date.now() - then) / 1000 > 1800;
  }
  function $(sel) { return document.querySelector(sel); }
  function setHTML(sel, html) {
    var host = $(sel);
    if (host) host.innerHTML = html;
  }

  function allEvents(snapshot) {
    var out = [];
    var topics = (snapshot && snapshot.topics) || {};
    Object.keys(topics).forEach(function (key) {
      ((topics[key] || {}).events || []).forEach(function (event) { out.push(event); });
    });
    return out;
  }
  function byNotional(events) {
    return events.slice().sort(function (a, b) { return (b.notional_24h_est || 0) - (a.notional_24h_est || 0); });
  }

  function fetchJson(path) {
    return fetch(PREFIX + path + "?v=" + Date.now(), { cache: "no-store" }).then(function (res) {
      if (!res.ok) throw new Error(path + " → HTTP " + res.status);
      return res.json();
    });
  }

  /* ------------------------------------------------------------ fragments */
  function statusHTML() {
    var snapshot = state.snapshot;
    var fresh = !isStale(snapshot);
    var alerts = (snapshot && snapshot.alerts) || [];
    return '<div class="status-line">' +
      '<span class="pulse ' + (fresh ? "on" : "off") + '" aria-hidden="true"></span>' +
      "<span><b>" + (snapshot ? "Published snapshot" : "No snapshot") + "</b> · " + esc(ageText(snapshot)) +
      " · " + num(snapshot && snapshot.market_count) + " markets · " + num(alerts.length) + " new alerts</span>" +
      '<span class="chip ' + (fresh ? "ok" : "warn") + '">' + (fresh ? "fresh" : "over 30 min old") + "</span>" +
      "</div>";
  }

  function kpiHTML() {
    var snapshot = state.snapshot || {};
    var topics = snapshot.topics || {};
    var notional = 0, openInterest = 0;
    Object.keys(topics).forEach(function (key) {
      notional += (topics[key].notional_24h_est || 0);
      openInterest += (topics[key].open_interest || 0);
    });
    var perf = (snapshot.performance || {}).headline || {};
    var headline = (state.paper || {}).headline || {};
    var equity = headline.equity !== undefined ? headline.equity : perf.equity;
    var pnl = headline.total_pnl !== undefined ? headline.total_pnl : perf.total_pnl;
    var picks = (snapshot.picks || []).length;

    var tiles = [
      ["Tracked markets", num(snapshot.market_count), num(snapshot.event_count) + " open events scanned", ""],
      ["Est. 24h notional · 5 topics", usd(notional), "last price × 24h volume, derived", ""],
      ["Open interest", num(openInterest), "sum of open_interest_fp", ""],
      ["Swing alerts archived", num(state.alerts.length), "threshold ≥ " + usd(THRESHOLD, 2), ""],
      ["High-ROI picks this cycle", num(picks), "model heuristic-v1, not a forecast", ""],
      ["Paper equity", usd(equity, 2), signed(pnl) + " vs " + usd(headline.bankroll_start !== undefined ? headline.bankroll_start : perf.bankroll_start, 2) + " start", (pnl || 0) >= 0 ? "up" : "down"]
    ];
    var cells = tiles.map(function (tile) {
      return '<div class="card"><span class="label">' + esc(tile[0]) + '</span>' +
        '<span class="value ' + tile[3] + '">' + tile[1] + "</span>" +
        '<span class="foot">' + tile[2] + "</span></div>";
    }).join("");

    var demo = snapshot.demo || {};
    var demoLine = demo.connected ? "" :
      '<div class="banner warn" style="margin:2px 0 0"><b>Demo account not connected.</b>' +
      '<span class="grow">Positions, balances and fills below are simulated in an internal ledger. ' +
      "A Kalshi demo API key can only be created by the account holder, so nothing was invented in its place.</span></div>";
    return '<div class="kpi">' + cells + "</div>" + demoLine;
  }

  function topicCardsHTML() {
    var topics = (state.snapshot || {}).topics || {};
    return TOPIC_ORDER.map(function (id) {
      var block = topics[id] || {};
      var events = byNotional(block.events || []);
      var rows = events.slice(0, 3).map(function (event) {
        return "<li>" + '<span class="amt">' + usd(event.notional_24h_est) + "</span> " + esc(clamp(event.title, 62)) + "</li>";
      });
      if (!rows.length) rows.push("<li>No open events in the current snapshot.</li>");
      return '<a class="topic" href="docs/desk/topics/' + ({ gas: "gas-prices", elections: "elections", culture: "culture", crypto: "crypto", golf: "golf" }[id]) + '.html">' +
        '<h3><span class="chip ' + id + '">' + esc(TOPIC_LABEL[id]) + "</span></h3>" +
        '<div class="tstats"><span><b>' + num(block.markets_count) + "</b> markets</span>" +
        "<span><b>" + num(events.length) + "</b> events</span>" +
        "<span><b>" + usd(block.notional_24h_est) + "</b> est. 24h</span></div>" +
        "<ol>" + rows.join("") + "</ol>" +
        '<span class="go">Open the ' + esc(TOPIC_LABEL[id].toLowerCase()) + " desk →</span>" +
        "</a>";
    }).join("\n");
  }

  function leaderboardHTML() {
    var events = byNotional(allEvents(state.snapshot)).slice(0, 10);
    if (!events.length) return '<div class="chat-empty">No open events in the current snapshot.</div>';
    var head = "<table><thead><tr><th>Event</th><th>Topic</th><th class=\"num\">Markets</th>" +
      '<th class="num">Est. 24h $</th><th class="num">Open interest</th><th>Closes</th><th>Source</th></tr></thead><tbody>';
    var rows = events.map(function (event) {
      var topic = event.topic || "";
      return "<tr>" +
        '<td><span class="title">' + esc(clamp(event.title, 84)) + "</span>" +
        '<span class="meta mono">' + esc(event.event_ticker) + "</span></td>" +
        '<td><span class="chip ' + esc(topic) + '">' + esc(TOPIC_LABEL[topic] || topic) + "</span></td>" +
        '<td class="num">' + num(event.markets_count) + "</td>" +
        '<td class="num">' + usd(event.notional_24h_est) + "</td>" +
        '<td class="num">' + num(event.open_interest) + "</td>" +
        '<td class="meta">' + esc(String(event.close_time || "—").slice(0, 16).replace("T", " ")) + "</td>" +
        '<td class="src"><a href="' + esc(event.series_page_url || "#") + '" target="_blank" rel="noopener">Kalshi</a></td>' +
        "</tr>";
    }).join("");
    return head + rows + "</tbody></table>";
  }

  function chatHTML(modelOnly) {
    var alerts = state.alerts;
    if (modelOnly) {
      alerts = alerts.filter(function (a) { return a.model && a.model.eligible === true; });
    }
    if (!alerts.length) {
      return modelOnly
        ? '<div class="chat-empty">No alert has passed the model filter yet.<br>It requires score ≥ 0.45, estimated ROI ≥ 6%, spread ≤ $0.06 and 24h volume ≥ 100 contracts.</div>'
        : '<div class="chat-empty">No ≥ $0.10 swings recorded yet.<br>The chat fills as scheduled cycles detect moves — nothing is pre-seeded.</div>';
    }
    return alerts.slice(-40).map(function (alert) {
      var up = alert.direction === "up";
      var model = alert.model || {};
      var score = typeof model.score === "number" ? '<span class="chip ok">score ' + model.score.toFixed(2) + "</span>" : "";
      var when = String(alert.iso || "").slice(11, 19) || "—";
      return '<div class="msg">' +
        '<div class="ts">' + esc(when) + "<br>UTC</div>" +
        "<div>" +
        '<div class="head">' +
        '<span class="chip ' + esc(alert.topic) + '">' + esc(TOPIC_LABEL[alert.topic] || alert.topic) + "</span>" +
        '<span class="dir ' + (up ? "up" : "down") + '">' + (up ? "▲" : "▼") + " " + signed(alert.delta) + "</span>" +
        '<span class="meta">' + cents(alert.from_price) + " → " + cents(alert.to_price) + "</span>" +
        score +
        "</div>" +
        '<div class="title">' + esc(clamp(alert.title, 104)) + "</div>" +
        '<div class="links"><span class="mono">' + esc(alert.ticker) + "</span>" +
        '<a href="' + esc(alert.api_url || "#") + '" target="_blank" rel="noopener">market API</a>' +
        '<a href="' + esc(alert.series_page_url || "#") + '" target="_blank" rel="noopener">Kalshi page</a>' +
        "</div></div></div>";
    }).join("\n");
  }

  function paperHTML() {
    var snapshot = state.snapshot || {};
    var headline = (state.paper || {}).headline || {};
    var perf = (snapshot.performance || {}).headline || {};
    var summary = (snapshot.performance || {}).summary || {};
    var equity = headline.equity !== undefined ? headline.equity : perf.equity;
    var pnl = headline.total_pnl !== undefined ? headline.total_pnl : perf.total_pnl;
    var roi = headline.roi_pct !== undefined ? headline.roi_pct : perf.roi_pct;
    var positions = (state.paper || {}).open_positions || (snapshot.paper || {}).open_positions || [];
    var cash = headline.cash !== undefined ? headline.cash : perf.cash;
    var verified = headline.fee_verified !== undefined ? headline.fee_verified : perf.fee_verified;

    var head = '<div class="kpi" style="grid-template-columns:repeat(auto-fit,minmax(120px,1fr))">' +
      '<div class="card"><span class="label">Equity</span><span class="value">' + usd(equity, 2) + "</span>" +
      '<span class="foot">start ' + usd(headline.bankroll_start !== undefined ? headline.bankroll_start : perf.bankroll_start, 2) + "</span></div>" +
      '<div class="card"><span class="label">Total P&amp;L</span><span class="value ' + ((pnl || 0) >= 0 ? "up" : "down") + '">' + signed(pnl) + "</span>" +
      '<span class="foot">' + signed(roi) + "%</span></div>" +
      '<div class="card"><span class="label">Open positions</span><span class="value">' + num(positions.length) + "</span>" +
      '<span class="foot">cash ' + usd(cash, 2) + "</span></div>" +
      '<div class="card"><span class="label">Closed trades</span><span class="value">' + num(summary.trades) + "</span>" +
      '<span class="foot">win rate ' + num(summary.win_rate_pct, 1) + "%</span></div>" +
      "</div>";

    var table;
    if (positions.length) {
      var rows = positions.slice(0, 6).map(function (pos) {
        return "<tr>" +
          '<td><span class="title">' + esc(clamp(pos.title, 58)) + "</span>" +
          '<span class="meta mono">' + esc(pos.ticker) + "</span></td>" +
          '<td><span class="chip ' + esc(pos.topic) + '">' + esc(TOPIC_LABEL[pos.topic] || pos.topic) + "</span></td>" +
          '<td class="num">' + num(pos.contracts) + "</td>" +
          '<td class="num">' + cents(pos.entry_price) + "</td>" +
          '<td class="meta">' + esc(clamp(pos.strategy_name || pos.strategy, 30)) + "</td>" +
          '<td class="src"><a href="' + esc(pos.api_url || pos.series_page_url || "#") + '" target="_blank" rel="noopener">API</a></td>' +
          "</tr>";
      }).join("");
      table = '<div class="table-wrap" style="max-height:250px;margin-top:10px"><table>' +
        '<thead><tr><th>Open position</th><th>Topic</th><th class="num">Contracts</th><th class="num">Entry</th><th>Strategy</th><th>Source</th></tr></thead><tbody>' +
        rows + "</tbody></table></div>";
    } else {
      table = '<div class="chat-empty">No open positions. The book opens positions when a strategy entry rule fires.</div>';
    }

    var feeNote = verified
      ? "Fees charged with the published formula."
      : "Fees modelled at 7% × contracts × price × (1 − price), rounded up to the cent — <b>unverified</b> against Kalshi's current fee schedule.";

    return "<h3>Simulated book</h3>" + head + table +
      '<div class="note" style="margin-top:10px">' + feeNote + ' <a href="docs/desk/flagged.html">See the flagged list</a>.</div>';
  }

  function resolvedHTML() {
    var items = state.resolved;
    if (!items.length) {
      return "<h3>Resolution tracker</h3>" +
        '<div class="chat-empty">No settled markets recorded yet. Every followed event is polled until Kalshi marks it finalized, then recorded as YES or NO from the exchange\'s own <code>result</code> field.</div>' +
        '<div class="note" style="margin-top:8px">Lifecycle reference: <a href="https://docs.kalshi.com/getting_started/market_lifecycle" target="_blank" rel="noopener">docs.kalshi.com/getting_started/market_lifecycle</a></div>';
    }
    var yes = items.filter(function (r) { return String(r.resolution).toUpperCase() === "YES"; }).length;
    var rows = items.slice(0, 10).map(function (item) {
      var outcome = String(item.resolution || "—").toUpperCase();
      var cls = outcome === "YES" ? "ok" : (outcome === "NO" ? "bad" : "warn");
      return "<tr>" +
        '<td><span class="title">' + esc(clamp(item.title, 66)) + "</span>" +
        '<span class="meta mono">' + esc(item.ticker) + "</span></td>" +
        '<td><span class="chip ' + cls + '">' + esc(outcome) + "</span></td>" +
        '<td class="meta">' + esc(String(item.close_time || item.settled_ts || "—").slice(0, 16).replace("T", " ")) + "</td>" +
        '<td class="src"><a href="' + esc(item.api_url || item.source || "#") + '" target="_blank" rel="noopener">verify</a></td>' +
        "</tr>";
    }).join("");
    return "<h3>Resolution tracker</h3>" +
      '<div class="tstats" style="display:flex;gap:12px;font-size:11px;color:var(--muted);margin-bottom:8px">' +
      "<span><b>" + items.length + "</b> settled</span><span><b>" + yes + "</b> YES</span><span><b>" + (items.length - yes) + "</b> NO</span></div>" +
      '<div class="table-wrap" style="max-height:250px"><table>' +
      "<thead><tr><th>Market</th><th>Outcome</th><th>Closed</th><th>Source</th></tr></thead><tbody>" +
      rows + "</tbody></table></div>";
  }

  function errorsHTML() {
    var errors = (state.snapshot || {}).errors || [];
    if (!errors.length) {
      var box = $("#collectionWarnings");
      if (box) box.innerHTML = "";
      return;
    }
    var host = $("#collectionWarnings");
    if (!host) return;
    host.innerHTML = '<div class="banner warn" style="margin-top:12px"><b>' + errors.length +
      " collection warning(s) in the published snapshot.</b>" +
      '<span class="grow"><ul style="margin:4px 0 0;padding-left:16px">' +
      errors.slice(0, 10).map(function (e) { return "<li>" + esc(clamp(String(e), 190)) + "</li>"; }).join("") +
      "</ul>These are printed, not suppressed. A failed request never becomes an invented value.</span></div>";
  }

  /* --------------------------------------------------------------- render */
  function renderAll() {
    setHTML("#topStatus", statusHTML());
    setHTML("#kpiHost", kpiHTML());
    setHTML("#topicCards", topicCardsHTML());
    setHTML("#leaderboard", leaderboardHTML());
    setHTML("#chatAll", chatHTML(false));
    setHTML("#chatModel", chatHTML(true));
    setHTML("#paperPanel", paperHTML());
    setHTML("#resolvedPanel", resolvedHTML());
    errorsHTML();
  }

  function note(message, warn) {
    var host = $("#liveNote");
    if (!host) return;
    host.innerHTML = message
      ? '<div class="banner ' + (warn ? "warn" : "") + '" style="margin-top:10px">' + message + "</div>"
      : "";
  }

  function refresh() {
    return Promise.all([
      fetchJson("latest.json"),
      fetchJson("alerts.json"),
      fetchJson("resolved.json"),
      fetchJson("paper.json")
    ]).then(function (results) {
      var latest = results[0];
      var alerts = (results[1] && results[1].items) || [];
      var resolved = (results[2] && results[2].items) || [];
      var paper = results[3];

      if (state.snapshot && latest.generated_ts && latest.generated_ts < state.snapshot.generated_ts) {
        note("Live refresh returned an older snapshot than the one on screen — keeping the newer data.", false);
        return;
      }
      state.snapshot = latest;
      state.alerts = alerts;
      state.resolved = resolved;
      state.paper = paper;
      state.lastError = "";
      renderAll();
      note("", false);
    }).catch(function (err) {
      state.lastError = String(err && err.message ? err.message : err);
      note("<b>Live refresh unavailable.</b> The tables above are the last published snapshot and stay valid. " +
        esc(state.lastError), true);
    });
  }

  function init() {
    // Seed the client state from the DOM-rendered values so a slow first fetch never blanks the page.
    refresh();
    setInterval(refresh, 60000);
    var refreshButton = $("#refreshNow");
    if (refreshButton) {
      refreshButton.addEventListener("click", function () {
        refreshButton.disabled = true;
        refresh().then(function () { refreshButton.disabled = false; });
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
