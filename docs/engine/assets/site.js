
// Dependency-free interactive engine client: table sorting, live Demo API polling with host failover,
// SVG contract price chart (Seconds / Minutes / Hours), orderbook depth bars, dual >= $0.10 swing chats,
// and automated paper strategy simulator using published Kalshi fee formulas.
(function () {
  var SERIES_MULT = {
    KXAAAGASM: 1.0, KXBTCY: 0.0, KXETHY: 0.0, KXBTCD: 1.0, KXPGATOUR: 1.0, KXNEXTNATOSECGEN: 1.0,
    KXFEDDECISION: 1.5, KXCPI: 1.5, KXGDP: 1.5
  };

  function escHtml(s) {
    if (s === null || s === undefined) return '--';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function kalshiFee(contracts, price, maker, seriesTicker) {
    var rate = maker ? 0.0175 : 0.07;
    var m = (seriesTicker && SERIES_MULT[seriesTicker] !== undefined) ? SERIES_MULT[seriesTicker] : (maker ? 0.0 : 1.0);
    var raw = m * rate * contracts * price * (1.0 - price);
    return Math.ceil(raw * 100 - 1e-12) / 100;
  }

  function matchTopic(ev, mkt) {
    var ticker = String((mkt && mkt.ticker) || '');
    var series = String((ev && ev.series_ticker) || ticker.split('-')[0] || '').toUpperCase();
    if (series.indexOf('KXMVE') === 0 || ticker.indexOf('KXMVE') === 0) return null;
    var cat = String((ev && ev.category) || '').toLowerCase();
    var title = String(((mkt && mkt.title) || '') + ' ' + ((ev && ev.title) || '')).toLowerCase();
    if (series.indexOf('KXAAAGAS') === 0 || title.indexOf('gas price') >= 0 || title.indexOf('gasoline') >= 0) return 'gas';
    if (cat === 'elections' || series.indexOf('NATO') >= 0 || title.indexOf('election') >= 0 || title.indexOf('senate') >= 0 || title.indexOf('president') >= 0) return 'elections';
    if (cat === 'entertainment' || cat === 'mentions' || title.indexOf('grammy') >= 0 || title.indexOf('oscar') >= 0 || title.indexOf('netflix') >= 0 || title.indexOf('album') >= 0) return 'culture';
    if (cat === 'crypto' || series.indexOf('KXBTC') === 0 || series.indexOf('KXETH') === 0 || series.indexOf('KXSOL') === 0 || title.indexOf('bitcoin') >= 0 || title.indexOf('ethereum') >= 0) return 'crypto';
    if (series.indexOf('KXPGA') === 0 || series.indexOf('KXLIV') === 0 || series.indexOf('KXLPGA') === 0 || series.indexOf('KXDPWORLD') === 0 || title.indexOf('pga tour') >= 0 || title.indexOf('masters') >= 0 || title.indexOf('golf') >= 0) return 'golf';
    return null;
  }

  function attachTableSort() {
    document.querySelectorAll('table').forEach(function (table) {
      var headers = table.querySelectorAll('thead th');
      headers.forEach(function (th, index) {
        if (th.dataset.nosort !== undefined) return;
        th.style.cursor = 'pointer';
        th.title = 'Click to sort';
        var ascending = false;
        th.addEventListener('click', function () {
          var body = table.tBodies[0];
          if (!body) return;
          var rows = Array.prototype.slice.call(body.rows);
          ascending = !ascending;
          rows.sort(function (a, b) {
            var av = (a.cells[index] || {}).textContent || '';
            var bv = (b.cells[index] || {}).textContent || '';
            var an = parseFloat(av.replace(/[^0-9.\-]/g, ''));
            var bn = parseFloat(bv.replace(/[^0-9.\-]/g, ''));
            if (!isNaN(an) && !isNaN(bn) && an !== bn) return ascending ? an - bn : bn - an;
            return ascending ? av.localeCompare(bv) : bv.localeCompare(av);
          });
          rows.forEach(function (r) { body.appendChild(r); });
        });
      });
    });
  }

  function loadJson(relPath) {
    return fetch(relPath, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function initLivePage(dash) {
    var svg = document.getElementById('price-svg');
    var selMarket = document.getElementById('chart-market-select');
    var obBox = document.getElementById('orderbook-bars');
    var jumpBox = document.getElementById('jump-pins');
    var badge = document.getElementById('live-conn-badge');
    var btnPoll = document.getElementById('btn-poll-now');
    var selInterval = document.getElementById('sel-poll-interval');
    var selHost = document.getElementById('sel-rest-host');
    var mktLink = document.getElementById('chart-market-link');
    var boards = document.getElementById('live-topic-boards');
    if (!svg || !selMarket) return;

    var state = {
      win: 'hours',
      ticks: Object.assign({}, dash.tick_series || {}),
      orderbooks: Object.assign({}, dash.orderbooks || {}),
      marketsByTicker: {},
      alerts: (dash.alerts || []).slice(),
      selective: (dash.selective_alerts || []).slice(),
      lastMid: {},
      timer: null
    };

    (dash.topics || []).forEach(function (t) {
      (t.markets || []).forEach(function (m) {
        state.marketsByTicker[m.ticker] = m;
        var lp = parseFloat(m.last_price);
        if (!isNaN(lp)) state.lastMid[m.ticker] = lp;
      });
    });

    function renderChats() {
      var allBox = document.getElementById('chat-all');
      var roiBox = document.getElementById('chat-roi');
      var allCnt = document.getElementById('chat-all-count');
      var roiCnt = document.getElementById('chat-roi-count');
      if (allCnt) allCnt.textContent = String(state.alerts.length);
      if (roiCnt) roiCnt.textContent = String(state.selective.length);
      function rowsHtml(list) {
        if (!list.length) return '<div class="muted">No >= $0.10 swings observed yet.</div>';
        return list.slice(0, 30).map(function (a) {
          var cls = a.direction === 'up' ? 'up' : 'down';
          var url = a.page_url || 'https://docs.kalshi.com/getting_started/orderbook_responses';
          var fC = isNaN(parseFloat(a.from_price)) ? '--' : Math.round(parseFloat(a.from_price) * 100) + 'c';
          var tC = isNaN(parseFloat(a.to_price)) ? '--' : Math.round(parseFloat(a.to_price) * 100) + 'c';
          return '<div class="chatmsg"><div class="meta"><span class="mono">' + escHtml(a.time_utc || '--') + '</span>' +
            '<span class="tag">' + escHtml(a.topic) + '</span></div>' +
            '<div><strong class="' + cls + '">' + escHtml(a.delta) + '</strong> <span class="mono">' + escHtml(a.ticker) + '</span> (' + fC + ' -> ' + tC + ')</div>' +
            '<div class="muted">' + escHtml(a.title) + ' · <a href="' + escHtml(url) + '" target="_blank" rel="noopener">official market</a></div></div>';
        }).join('');
      }
      if (allBox) allBox.innerHTML = rowsHtml(state.alerts);
      if (roiBox) roiBox.innerHTML = rowsHtml(state.selective);
    }

    function renderOrderbook(ticker) {
      var ob = state.orderbooks[ticker];
      var m = state.marketsByTicker[ticker];
      if (!ob && m) {
        var yb = parseFloat(m.yes_bid);
        var ya = parseFloat(m.yes_ask);
        ob = {
          source_url: m.page_url || 'https://docs.kalshi.com/getting_started/orderbook_responses',
          yes_bids: !isNaN(yb) && yb > 0 ? [{ price: yb.toFixed(4), contracts: m.open_interest_fp || '100' }] : [],
          no_bids: !isNaN(ya) && ya < 1 ? [{ price: (1 - ya).toFixed(4), implied_yes_ask: ya.toFixed(4), contracts: m.open_interest_fp || '100' }] : []
        };
      }
      if (!ob || ((!ob.yes_bids || !ob.yes_bids.length) && (!ob.no_bids || !ob.no_bids.length))) {
        obBox.innerHTML = '<div class="muted">No resting bids returned for <span class="mono">' + escHtml(ticker) + '</span> (empty book; values left as <code>--</code>).</div>';
        return;
      }
      var levels = [];
      (ob.yes_bids || []).slice(-5).reverse().forEach(function (lv) {
        levels.push({ kind: 'yes', label: 'YES bid $' + parseFloat(lv.price).toFixed(2), qty: parseFloat(lv.contracts) || 0 });
      });
      (ob.no_bids || []).slice(-5).reverse().forEach(function (lv) {
        var ask = lv.implied_yes_ask !== undefined ? parseFloat(lv.implied_yes_ask) : (1 - parseFloat(lv.price));
        levels.push({ kind: 'no', label: 'NO bid $' + parseFloat(lv.price).toFixed(2) + ' (YES ask $' + ask.toFixed(2) + ')', qty: parseFloat(lv.contracts) || 0 });
      });
      var maxQ = 1;
      levels.forEach(function (l) { if (l.qty > maxQ) maxQ = l.qty; });
      obBox.innerHTML = levels.map(function (l) {
        var pct = Math.max(3, Math.round((l.qty / maxQ) * 100));
        return '<div class="ob-row"><span class="mono">' + escHtml(l.label.split(' ')[0] + ' ' + l.label.split(' ')[2]) + '</span>' +
          '<div class="ob-track"><div class="ob-fill ' + l.kind + '" style="width:' + pct + '%"></div></div>' +
          '<span class="mono" style="text-align:right">' + Math.round(l.qty).toLocaleString() + ' ctr</span></div>';
      }).join('') + '<div class="muted" style="margin-top:6px"><a href="' + escHtml(ob.source_url) + '" target="_blank" rel="noopener">Orderbook endpoint source ↗</a></div>';
    }

    function renderChart() {
      var ticker = selMarket.value;
      var m = state.marketsByTicker[ticker] || {};
      if (mktLink) {
        mktLink.href = m.page_url || ('https://external-api.demo.kalshi.co/trade-api/v2/markets/' + encodeURIComponent(ticker));
      }
      var raw = (state.ticks[ticker] || []).slice();
      if (!raw.length && m.last_price) {
        var nowS = Date.now() / 1000;
        raw = [
          { ts: nowS - 60, last_price: m.last_price, yes_bid: m.yes_bid, yes_ask: m.yes_ask },
          { ts: nowS, last_price: m.last_price, yes_bid: m.yes_bid, yes_ask: m.yes_ask }
        ];
      }
      if (!raw.length) {
        svg.innerHTML = '<text x="20" y="140" fill="#5f6b7d" font-size="13">No verified price ticks for ' + escHtml(ticker) + ' (--).</text>';
        renderOrderbook(ticker);
        return;
      }
      var maxTs = raw[raw.length - 1].ts || (Date.now() / 1000);
      var spanS = state.win === 'seconds' ? 60 : (state.win === 'minutes' ? 1800 : 21600);
      var filtered = raw.filter(function (pt) { return (maxTs - (pt.ts || maxTs)) <= spanS; });
      if (filtered.length < 2) filtered = raw.slice(-Math.min(raw.length, 6));

      var W = 640, H = 280, padL = 48, padR = 18, padT = 20, padB = 34;
      var plotW = W - padL - padR, plotH = H - padT - padB;
      var t0 = filtered[0].ts || 0;
      var t1 = filtered[filtered.length - 1].ts || (t0 + 1);
      if (t1 <= t0) t1 = t0 + 1;

      function xOf(t) { return padL + ((t - t0) / (t1 - t0)) * plotW; }
      function yOf(p) { return padT + (1.0 - Math.max(0, Math.min(1, p))) * plotH; }

      var grid = '';
      [0, 0.25, 0.5, 0.75, 1.0].forEach(function (yv) {
        var yy = yOf(yv).toFixed(1);
        grid += '<line x1="' + padL + '" y1="' + yy + '" x2="' + (W - padR) + '" y2="' + yy + '" stroke="#eef1f6"/>' +
          '<text x="6" y="' + (parseFloat(yy) + 4) + '" fill="#5f6b7d" font-size="11">$' + yv.toFixed(2) + '</text>';
      });

      var pts = [];
      var jumps = [];
      for (var i = 0; i < filtered.length; i++) {
        var pv = parseFloat(filtered[i].last_price);
        if (isNaN(pv)) continue;
        var xx = xOf(filtered[i].ts || t0);
        var yy = yOf(pv);
        pts.push(xx.toFixed(1) + ',' + yy.toFixed(1));
        if (i > 0) {
          var prev = parseFloat(filtered[i - 1].last_price);
          if (!isNaN(prev) && Math.abs(pv - prev) >= 0.10 - 1e-9) {
            jumps.push({ x: xx, y: yy, delta: pv - prev, from: prev, to: pv, ts: filtered[i].ts });
          }
        }
      }

      var poly = pts.length ? '<polyline fill="none" stroke="#0b63ce" stroke-width="2.5" points="' + pts.join(' ') + '"/>' : '';
      var dots = pts.map(function (pair) {
        var sp = pair.split(',');
        return '<circle cx="' + sp[0] + '" cy="' + sp[1] + '" r="3.5" fill="#0b63ce"/>';
      }).join('');
      var jumpSvg = jumps.map(function (j) {
        var col = j.delta > 0 ? '#0a7b45' : '#b3261e';
        var lbl = (j.delta > 0 ? '+' : '') + Math.round(j.delta * 100) + 'c';
        return '<circle cx="' + j.x.toFixed(1) + '" cy="' + j.y.toFixed(1) + '" r="6.5" fill="' + col + '" stroke="#fff" stroke-width="1.5"/>' +
          '<text x="' + (j.x - 14).toFixed(1) + '" y="' + Math.max(14, j.y - 10).toFixed(1) + '" fill="' + col + '" font-size="11" font-weight="700">' + lbl + '</text>';
      }).join('');

      var xLabel = 'Window: ' + state.win.toUpperCase() + ' (' + filtered.length + ' samples)';
      svg.innerHTML = grid + poly + dots + jumpSvg +
        '<text x="' + padL + '" y="' + (H - 8) + '" fill="#5f6b7d" font-size="11">' + escHtml(xLabel) + '</text>' +
        '<text x="' + (W - padR - 145) + '" y="' + (H - 8) + '" fill="#5f6b7d" font-size="11">' + escHtml(ticker) + '</text>';

      if (jumpBox) {
        var mUrl = m.page_url || ('https://external-api.demo.kalshi.co/trade-api/v2/markets/' + encodeURIComponent(ticker));
        var sList = m.settlement_sources || [];
        var sHtml = (sList.length && sList[0].url) ? (' · <a href="' + escHtml(sList[0].url) + '" target="_blank" rel="noopener">' + escHtml(sList[0].name || 'Settlement source') + '</a>') : '';
        if (jumps.length) {
          jumpBox.innerHTML = '<strong>Sharp >= $0.10 jumps on chart:</strong> ' + jumps.map(function (j) {
            var sg = j.delta > 0 ? '+' : '';
            return '<span class="tag ' + (j.delta > 0 ? 'ok' : 'bad') + '">' + sg + (j.delta).toFixed(2) + ' ($' + j.from.toFixed(2) + ' -> $' + j.to.toFixed(2) + ')</span> ' +
              '<a href="' + escHtml(mUrl) + '" target="_blank" rel="noopener">Kalshi event</a>' + sHtml;
          }).join(' · ');
        } else {
          jumpBox.innerHTML = 'No >= $0.10 jump inside current zoom window for <span class="mono">' + escHtml(ticker) + '</span> · <a href="' + escHtml(mUrl) + '" target="_blank" rel="noopener">Official Kalshi page</a>' + sHtml;
        }
      }
      renderOrderbook(ticker);
    }

    document.querySelectorAll('[data-win]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        document.querySelectorAll('[data-win]').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        state.win = btn.getAttribute('data-win') || 'hours';
        renderChart();
      });
    });
    selMarket.addEventListener('change', renderChart);

    function pollDemoApi() {
      var primary = selHost ? selHost.value : 'https://external-api.demo.kalshi.co/trade-api/v2';
      var fallback = primary.indexOf('external-api') >= 0 ? 'https://demo-api.kalshi.co/trade-api/v2' : 'https://external-api.demo.kalshi.co/trade-api/v2';
      if (badge) { badge.className = 'tag warn'; badge.textContent = 'Polling Demo API…'; }

      function tryHost(base) {
        return fetch(base + '/events?limit=50&status=open&with_nested_markets=true', { mode: 'cors', cache: 'no-store' })
          .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
          .then(function (payload) { return { base: base, payload: payload }; });
      }

      tryHost(primary).catch(function () { return tryHost(fallback); }).then(function (res) {
        var events = (res.payload && res.payload.events) || [];
        var grouped = { gas: [], elections: [], culture: [], crypto: [], golf: [] };
        var nowS = Date.now() / 1000;
        var nowIso = new Date().toISOString().slice(0, 19) + 'Z';
        var addedOptions = 0;

        events.forEach(function (ev) {
          (ev.markets || []).forEach(function (mk) {
            var tp = matchTopic(ev, mk);
            if (!tp) return;
            var yb = parseFloat(mk.yes_bid_dollars);
            var ya = parseFloat(mk.yes_ask_dollars);
            var lp = parseFloat(mk.last_price_dollars);
            var mid = (!isNaN(yb) && !isNaN(ya) && yb > 0 && ya < 1 && ya >= yb) ? ((yb + ya) / 2) : (!isNaN(lp) ? lp : NaN);
            var vol = parseFloat(mk.volume_fp || '0') || 0;
            var rec = {
              ticker: mk.ticker,
              title: String(mk.title || ev.title || mk.ticker).replace(/\*\*/g, ''),
              topic: tp,
              yes_bid: mk.yes_bid_dollars,
              yes_ask: mk.yes_ask_dollars,
              last_price: !isNaN(mid) ? mid.toFixed(4) : mk.last_price_dollars,
              volume_fp: String(vol),
              open_interest_fp: mk.open_interest_fp || '0',
              page_url: res.base + '/markets/' + encodeURIComponent(mk.ticker),
              settlement_sources: ev.settlement_sources || []
            };
            grouped[tp].push(rec);
            if (!state.marketsByTicker[mk.ticker] && addedOptions < 40) {
              var opt = document.createElement('option');
              opt.value = mk.ticker;
              opt.textContent = tp + ': ' + mk.ticker + ' — ' + rec.title.slice(0, 64);
              selMarket.appendChild(opt);
              addedOptions++;
            }
            state.marketsByTicker[mk.ticker] = rec;
            if (!isNaN(mid)) {
              if (!state.ticks[mk.ticker]) state.ticks[mk.ticker] = [];
              state.ticks[mk.ticker].push({ ts: nowS, last_price: mid.toFixed(4), yes_bid: mk.yes_bid_dollars, yes_ask: mk.yes_ask_dollars });
              if (state.lastMid[mk.ticker] !== undefined && Math.abs(mid - state.lastMid[mk.ticker]) >= 0.10 - 1e-9) {
                var d = mid - state.lastMid[mk.ticker];
                var alertObj = {
                  time_utc: nowIso,
                  ticker: mk.ticker,
                  title: rec.title,
                  topic: tp,
                  direction: d > 0 ? 'up' : 'down',
                  from_price: state.lastMid[mk.ticker].toFixed(4),
                  to_price: mid.toFixed(4),
                  delta: (d > 0 ? '+' : '') + d.toFixed(4),
                  selective: (vol >= 100 && (!isNaN(yb) && !isNaN(ya) && (ya - yb) <= 0.15)),
                  page_url: rec.page_url
                };
                state.alerts.unshift(alertObj);
                if (alertObj.selective) state.selective.unshift(alertObj);
              }
              state.lastMid[mk.ticker] = mid;
            }
          });
        });

        // Also fetch live orderbook for currently selected ticker
        var activeTicker = selMarket.value;
        if (activeTicker) {
          fetch(res.base + '/markets/' + encodeURIComponent(activeTicker) + '/orderbook', { mode: 'cors', cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (obDoc) {
              if (obDoc && obDoc.orderbook_fp) {
                var fp = obDoc.orderbook_fp;
                state.orderbooks[activeTicker] = {
                  source_url: res.base + '/markets/' + encodeURIComponent(activeTicker) + '/orderbook',
                  yes_bids: (fp.yes_dollars || []).map(function (lv) { return { price: lv[0], contracts: lv[1] }; }),
                  no_bids: (fp.no_dollars || []).map(function (lv) { return { price: lv[0], contracts: lv[1], implied_yes_ask: (1 - parseFloat(lv[0])).toFixed(4) }; })
                };
                renderOrderbook(activeTicker);
              }
            }).catch(function () {});
        }

        if (badge) {
          badge.className = 'tag ok';
          badge.textContent = 'LIVE Demo API (' + res.base.replace('https://', '') + ' · ' + nowIso + ')';
        }

        if (boards) {
          var topicKeys = ['gas', 'elections', 'culture', 'crypto', 'golf'];
          boards.innerHTML = topicKeys.map(function (tk) {
            var arr = grouped[tk].sort(function (a, b) { return parseFloat(b.volume_fp) - parseFloat(a.volume_fp); }).slice(0, 6);
            if (!arr.length) {
              return '<div class="card"><h3>' + tk.toUpperCase() + ' (0 open in current 50-event page)</h3><div class="muted">Unconfirmed / none open in sample — left blank rather than inferred.</div></div>';
            }
            var trs = arr.map(function (m) {
              return '<tr><td class="mono">' + escHtml(m.ticker) + '</td><td>' + escHtml(m.title) + '</td>' +
                '<td class="num">' + escHtml(m.last_price || '--') + '</td><td class="num">' + escHtml(m.volume_fp) + '</td>' +
                '<td><a href="' + escHtml(m.page_url) + '" target="_blank" rel="noopener">API market</a></td></tr>';
            }).join('');
            return '<div class="card"><h3>' + tk.toUpperCase() + ' (Top by Volume)</h3><div class="tblwrap"><table><thead><tr><th>Ticker</th><th>Contract</th><th class="num">Price ($)</th><th class="num">Volume</th><th>Source</th></tr></thead><tbody>' + trs + '</tbody></table></div></div>';
          }).join('');
        }

        renderChats();
        renderChart();
      }).catch(function (err) {
        if (badge) {
          badge.className = 'tag warn';
          badge.textContent = 'Offline / Replay fallback (' + (err && err.message ? err.message : 'no network') + ')';
        }
        renderChats();
        renderChart();
      });
    }

    if (btnPoll) btnPoll.addEventListener('click', pollDemoApi);
    if (selInterval) {
      selInterval.addEventListener('change', function () {
        if (state.timer) clearInterval(state.timer);
        var ms = parseInt(selInterval.value, 10) || 0;
        if (ms > 0) state.timer = setInterval(pollDemoApi, ms);
      });
      state.timer = setInterval(pollDemoApi, 30000);
    }
    renderChats();
    renderChart();
    pollDemoApi();
  }

  function initSimLab(dash) {
    var root = document.getElementById('sim-lab-root');
    if (!root) return;
    var btnRun = document.getElementById('btn-run-sim');
    var btnReset = document.getElementById('btn-reset-sim');
    var selCat = document.getElementById('sim-category');
    var selTopic = document.getElementById('sim-topic');
    var inpQty = document.getElementById('sim-qty');
    var summary = document.getElementById('sim-summary');
    var tbody = document.getElementById('sim-ledger-body');
    var ledger = [];
    var cash = 10000.0;

    function renderLedger() {
      if (!ledger.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="muted">No interactive paper trades run in this browser session yet.</td></tr>';
        summary.textContent = 'Paper bankroll: $' + cash.toFixed(2) + ' (0 session fills).';
        return;
      }
      var totalFees = ledger.reduce(function (s, x) { return s + x.fee; }, 0);
      summary.innerHTML = '<strong>Paper bankroll remaining:</strong> $' + cash.toFixed(2) +
        ' · <strong>Fills executed:</strong> ' + ledger.length +
        ' · <strong>Published Kalshi fees charged:</strong> $' + totalFees.toFixed(2) +
        ' (Order V2 unified YES scale applied on NO buys).';
      tbody.innerHTML = ledger.map(function (t) {
        return '<tr><td class="mono">' + escHtml(t.time) + '</td><td class="mono">' + escHtml(t.ticker) + '</td>' +
          '<td><span class="tag">' + escHtml(t.topic) + '</span></td><td><code>' + escHtml(t.category) + '</code></td>' +
          '<td>' + escHtml(t.v2Desc) + '</td><td class="num">' + t.qty + '</td>' +
          '<td class="num">$' + t.price.toFixed(4) + '</td><td class="num">$' + t.fee.toFixed(2) + '</td>' +
          '<td><a href="' + escHtml(t.url) + '" target="_blank" rel="noopener">Kalshi source</a></td></tr>';
      }).join('');
    }

    if (btnRun) {
      btnRun.addEventListener('click', function () {
        var cat = selCat ? selCat.value : 'momentum';
        var tf = selTopic ? selTopic.value : 'all';
        var qty = Math.max(1, Math.min(500, parseInt((inpQty && inpQty.value) || '25', 10) || 25));
        var candidates = [];
        (dash.topics || []).forEach(function (t) {
          if (tf !== 'all' && t.key !== tf) return;
          (t.markets || []).forEach(function (m) { candidates.push(m); });
        });
        var nowIso = new Date().toISOString().slice(11, 19) + 'Z';
        candidates.forEach(function (m) {
          var ya = parseFloat(m.yes_ask);
          var yb = parseFloat(m.yes_bid);
          var lp = parseFloat(m.last_price);
          var execYes = !isNaN(ya) && ya > 0 && ya < 1 ? ya : (!isNaN(lp) && lp > 0 && lp < 1 ? lp : NaN);
          if (isNaN(execYes)) return;
          var side = 'YES';
          var price = execYes;
          var maker = false;
          if (cat === 'tail' && execYes > 0.35) return;
          if (cat === 'carry') {
            maker = true;
            if (execYes < 0.50 && (1 - (!isNaN(yb) && yb > 0 ? yb : execYes)) >= 0.65) {
              side = 'NO';
              price = 1.0 - (!isNaN(yb) && yb > 0 ? yb : execYes);
            }
          } else if (cat === 'mean_reversion') {
            side = 'NO';
            price = 1.0 - (!isNaN(yb) && yb > 0 ? yb : execYes);
          }
          if (price <= 0 || price >= 1) return;
          var fee = kalshiFee(qty, price, maker, m.series_ticker);
          var cost = qty * price + fee;
          if (cost > cash) return;
          cash -= cost;
          var v2Desc = side === 'YES'
            ? ('BUY YES (side=bid @ $' + price.toFixed(4) + ')')
            : ('BUY NO (side=ask @ YES $' + (1.0 - price).toFixed(4) + ')');
          ledger.unshift({
            time: nowIso,
            ticker: m.ticker,
            topic: m.topic,
            category: cat,
            v2Desc: v2Desc,
            qty: qty,
            price: price,
            fee: fee,
            url: m.page_url || 'https://kalshi.com/docs/kalshi-fee-schedule.pdf'
          });
        });
        renderLedger();
      });
    }
    if (btnReset) {
      btnReset.addEventListener('click', function () {
        ledger = [];
        cash = 10000.0;
        renderLedger();
      });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    attachTableSort();
    if (document.getElementById('interactive-chart-root') || document.getElementById('sim-lab-root')) {
      loadJson('data/dashboard.json').then(function (dash) {
        initLivePage(dash);
        initSimLab(dash);
      }).catch(function () {});
    }
  });
})();
