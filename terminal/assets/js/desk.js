/* desk.js — a single, testable reference implementation of every rule the terminal
   applies to Kalshi data. dashboard.js, events.js and strategies.js call into this
   file instead of repeating the rules inline, so the rules can be exercised against
   recorded responses in terminal/tests/ with no network.

   Nothing in here invents a value. When an input field is missing the output field
   is null and the row says so; when a rule cannot be applied the row is dropped
   rather than filled in.

   Official field names used below (all fetched 2026-11-27):
     GET /markets        https://docs.kalshi.com/api-reference/market/get-markets
     GET /events         https://docs.kalshi.com/api-reference/events/get-events
     GET /markets/{t}/orderbook  https://docs.kalshi.com/getting_started/orderbook_responses
     candlesticks        https://docs.kalshi.com/api-reference/market/get-market-candlesticks
*/
'use strict';

const Desk = (() => {
  /* Quotes older than this are treated as stale. The docs say REST market data is
     cached "for a short time" and the WebSocket is the way to get current state
     (https://docs.kalshi.com/getting_started/quick_start_market_data); 5 minutes is
     a deliberately generous choice for a 4-second poll, and it is stated on the page
     rather than hidden. */
  const STALE_MS = 5 * 60 * 1000;

  /* Topics the brief restricts us to. Anything else is not shown. */
  const FOCUS = ['gas', 'elections', 'culture', 'crypto', 'golf'];

  /* Choose the price used for alerts and charts, and say where it came from.
     Order: last trade → bid/ask midpoint. A bid-only market has no midpoint, so it
     is not priced at all rather than priced at the bid. */
  function priceOf(market) {
    const last = Kalshi.priceOf(market, 'last');
    if (last != null) return { price: last, basis: 'last_trade' };
    const mid = Kalshi.midOf(market);
    if (mid != null) return { price: Number(mid.toFixed(4)), basis: 'quote_mid' };
    return { price: null, basis: 'unpriced' };
  }

  /* Build one row from an event/market pair. Returns null when the market is outside
     the five topics OR has no price at all: a row with no price cannot be alerted on
     and cannot be charted, so showing it only adds noise. */
  function buildRow(event, market, now = Date.now()) {
    const cls = classifyMarket({
      ...market,
      category: market.category || (event && event.category),
      series_ticker: market.series_ticker || (event && event.series_ticker),
      title: market.title || (event && event.title),
    });
    if (!cls.topic || !FOCUS.includes(cls.topic)) return null;

    const { price, basis } = priceOf(market);
    if (price == null) return null;

    const yesBid = Kalshi.priceOf(market, 'bid');
    const yesAsk = Kalshi.priceOf(market, 'ask');
    const prev = Kalshi.previousPriceOf(market);
    const spread = yesBid != null && yesAsk != null ? Number((yesAsk - yesBid).toFixed(4)) : null;

    /* `last_update` / `updated_ts` are not documented on the market object, so the
       observation time is our own poll time. That is the honest timestamp: it says
       when *we* saw the price, not when the exchange last changed it. */
    const observedAt = now;
    return {
      ticker: market.ticker,
      eventTicker: (event && event.event_ticker) || market.event_ticker || null,
      seriesTicker: market.series_ticker || (event && event.series_ticker) || null,
      title: (event && (event.title || event.sub_title)) || market.title || market.ticker,
      contractTitle: market.yes_sub_title || market.title || market.ticker,
      topic: cls.topic,
      topicEvidence: cls.evidence,
      topicConfidence: cls.confidence,
      status: String(market.status || (event && event.status) || 'unknown').toLowerCase(),
      result: normalizeResult(market.result, market.status),
      closeTime: market.close_time || (event && event.close_time) || null,
      yesBid, yesAsk,
      noBid: Kalshi.noBidOf(market),
      noAsk: Kalshi.noAskOf(market),
      price, priceBasis: basis,
      previousPrice: prev,                       // exchange: last traded price one day ago
      dayChange: prev != null ? Number((price - prev).toFixed(4)) : null,
      spread,
      bestBidContracts: Kalshi.bestSizeOf(market, 'bid'),
      bestAskContracts: Kalshi.bestSizeOf(market, 'ask'),
      volume: Kalshi.volumeOf(market),
      volume24h: Kalshi.volume24hOf(market),
      openInterest: Kalshi.openInterestOf(market),
      /* Dollar value traded over the exchange-reported 24h window, using the current
         price. It is an estimate and every surface that prints it says "est." */
      notional24h: (() => {
        const v = Kalshi.volume24hOf(market);
        return v == null ? null : Number((v * price).toFixed(2));
      })(),
      observedAt,
      stale: now - observedAt > STALE_MS,
      sourceUrl: market.ticker ? `${SITE.demoRest}/markets/${encodeURIComponent(market.ticker)}` : null,
      exchangeUrl: seriesTickerToUrl(market.series_ticker || (event && event.series_ticker)),
      rules: market.rules_primary || null,
    };
  }

  /* Official: `result` is yes/no after settlement; a closed market is not a resolved
     one (https://docs.kalshi.com/getting_started/market_settlement). */
  function normalizeResult(result, status) {
    const r = String(result || '').toLowerCase();
    if (r === 'yes' || r === 'no') return r;
    return null;
  }

  function seriesTickerToUrl(seriesTicker) {
    if (!seriesTicker) return null;
    return 'https://kalshi.com/markets/' + String(seriesTicker).toLowerCase();
  }

  /* Aggregate rows into events. `dollarVolume` is the sum of the event's markets'
     exchange-reported *total* traded dollar value, only when every child market has
     the field; otherwise it is null with an explanation. Ranking never substitutes
     an estimate for it — the caller may rank by the estimate and must label it. */
  function groupEvents(rows) {
    const map = new Map();
    for (const r of rows) {
      const key = r.eventTicker || r.ticker;
      if (!map.has(key)) {
        map.set(key, {
          eventTicker: key, title: r.title, topic: r.topic, seriesTicker: r.seriesTicker,
          markets: [], closeTime: r.closeTime, exchangeUrl: r.exchangeUrl,
          dollarVolume: 0, dollarVolumeComplete: true, notional24hEst: 0, openInterest: 0,
        });
      }
      const ev = map.get(key);
      ev.markets.push(r);
      if (r.volume != null && r.price != null) ev.dollarVolume += r.volume * r.price;
      else ev.dollarVolumeComplete = false;
      ev.notional24hEst += r.notional24h || 0;
      ev.openInterest += r.openInterest || 0;
      if (!ev.closeTime && r.closeTime) ev.closeTime = r.closeTime;
    }
    return [...map.values()].map((ev) => ({
      ...ev,
      dollarVolume: ev.dollarVolumeComplete ? Number(ev.dollarVolume.toFixed(2)) : null,
      notional24hEst: Number(ev.notional24hEst.toFixed(2)),
      marketCount: ev.markets.length,
    }));
  }

  /* Rank events for the "highest-dollar live events" table. Uses the derived 24h
     estimate (labelled) and falls back to nothing — an event with no estimate sorts
     last rather than being given a made-up figure. */
  function rankEvents(events) {
    return [...events].sort((a, b) => (b.notional24hEst || 0) - (a.notional24hEst || 0));
  }

  /* Rows whose 1-day change (exchange `previous_price_dollars` → current price) is at
     least `threshold` in either direction. This is the only "biggest movers" figure
     that can be shown on a first page load; the alert chat covers finer moves as they
     are observed. `dayChange` is labelled as a 1-day comparison everywhere. */
  function dayMovers(rows, { threshold = 0.10, limit = 12 } = {}) {
    return rows
      .filter((r) => r.dayChange != null && Math.abs(r.dayChange) >= threshold - 1e-9)
      .sort((a, b) => Math.abs(b.dayChange) - Math.abs(a.dayChange))
      .slice(0, limit);
  }

  /* Order-book summary used by the liquidity panel.
     Returns contracts and dollars available at each level, cumulative totals, and the
     implied ask ladder (a NO bid at p is a YES offer at 1 − p). Every figure is null
     when the book is missing; none is defaulted to zero. */
  function bookSummary(book, depth = 8) {
    if (!book) return null;
    const bids = book.yes.slice(0, depth).map(([p, q]) => ({ price: p, contracts: q, dollars: Number((p * q).toFixed(2)) }));
    const asks = Kalshi.impliedAsks(book, depth).map(([p, q]) => ({ price: p, contracts: q, dollars: Number((p * q).toFixed(2)) }));
    const cum = (levels) => {
      let c = 0, d = 0;
      return levels.map((l) => { c += l.contracts; d += l.dollars; return { ...l, cumContracts: Number(c.toFixed(2)), cumDollars: Number(d.toFixed(2)) }; });
    };
    const bidLadder = cum(bids);
    const askLadder = cum(asks);
    return {
      bidLadder, askLadder,
      bidContracts: bidLadder.length ? bidLadder[bidLadder.length - 1].cumContracts : null,
      bidDollars: bidLadder.length ? bidLadder[bidLadder.length - 1].cumDollars : null,
      askContracts: askLadder.length ? askLadder[askLadder.length - 1].cumContracts : null,
      askDollars: askLadder.length ? askLadder[askLadder.length - 1].cumDollars : null,
      bestBid: bidLadder.length ? bidLadder[0].price : null, // ladder is best-first
      bestAsk: askLadder.length ? askLadder[0].price : null,
      levels: book.yes.length + book.no.length,
    };
  }

  /* Merge candle points (older) with live poll points (newer) for the chart.
     Candles win on a timestamp collision only when they are older data, so a live
     point is never overwritten by a candle that lags it by a few seconds. */
  function mergeSeries(candlePoints, livePoints) {
    const byT = new Map();
    for (const p of candlePoints || []) byT.set(p.t, { ...p, source: 'candle' });
    for (const p of livePoints || []) byT.set(p.t, { ...p, source: 'poll' });
    return [...byT.values()].sort((a, b) => a.t - b.t);
  }

  /* What a trader is looking at, in one sentence. Used on the market panel so the
     numbers are never presented without their caveats. */
  function panelNote(row) {
    if (!row) return '';
    const bits = [];
    bits.push(`Price basis: ${row.priceBasis === 'last_trade' ? 'last trade' : row.priceBasis === 'quote_mid' ? 'bid/ask midpoint (no trade yet)' : 'unavailable'}.`);
    if (row.spread == null) bits.push('No two-sided quote, so the spread is unknown, not zero.');
    if (row.bestAskContracts == null) bits.push('Displayed ask size is not published for this market.');
    if (row.dayChange == null) bits.push('No one-day comparison published for this market yet.');
    bits.push('Quotes are cached by the exchange for a few seconds; this panel is a poll, not a stream.');
    return bits.join(' ');
  }

  return {
    STALE_MS, FOCUS,
    priceOf, buildRow, normalizeResult, seriesTickerToUrl,
    groupEvents, rankEvents, dayMovers, bookSummary, mergeSeries, panelNote,
  };
})();
