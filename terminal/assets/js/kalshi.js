/* kalshi.js — Kalshi Trade API v2 (demo) client.
 *
 * Public market data needs no authentication and is read directly by the visitor's
 * browser from https://external-api.demo.kalshi.co/trade-api/v2 (the venue's
 * documented demo root). Portfolio endpoints need a signed request; signing happens
 * in this browser with the visitor's own demo key, which is kept in localStorage and
 * never sent anywhere except the demo hosts.
 *
 * Official facts this file depends on (each fetched and read on 2026-11-27):
 *   environments + signing   https://docs.kalshi.com/getting_started/api_environments
 *   markets / fields         https://docs.kalshi.com/api-reference/market/get-markets
 *   events / fields          https://docs.kalshi.com/api-reference/events/get-events
 *   candlesticks             https://docs.kalshi.com/api-reference/market/get-market-candlesticks
 *   order body               https://docs.kalshi.com/getting_started/quick_start_create_order
 *   fee rounding             https://docs.kalshi.com/getting_started/fee_rounding
 *
 * Sandbox limitation, recorded rather than worked around: the session that wrote this
 * file has no network route to the demo hosts, so every request here is exercised in
 * the visitor's browser and in unit tests with recorded payload shapes — never assumed
 * to have succeeded. When a call fails the UI says so and shows nothing invented.
 */
'use strict';

const Kalshi = (() => {
  const DEMO = SITE.demoRest;
  const DEMO_ALT = SITE.demoRestAlt;
  const SIGN_PREFIX = '/trade-api/v2';

  const num = (v) => {
    if (v == null || v === '') return null;
    const n = typeof v === 'number' ? v : parseFloat(v);
    return Number.isFinite(n) ? n : null;
  };

  /* ---------- field normalisation (fixed-point dollars, with legacy cents fallback) ---------- */
  const priceOf = (m, side) => {
    if (!m) return null;
    if (side === 'bid') return num(m.yes_bid_dollars) ?? (num(m.yes_bid) != null ? m.yes_bid / 100 : null);
    if (side === 'ask') return num(m.yes_ask_dollars) ?? (num(m.yes_ask) != null ? m.yes_ask / 100 : null);
    if (side === 'last') return num(m.last_price_dollars) ?? (num(m.last_price) != null ? m.last_price / 100 : null);
    if (side === 'prev') return num(m.previous_price_dollars) ?? (num(m.previous_price) != null ? m.previous_price / 100 : null);
    return null;
  };
  const noBidOf = (m) => num(m && m.no_bid_dollars) ?? (m && num(m.no_bid) != null ? m.no_bid / 100 : null);
  const noAskOf = (m) => num(m && m.no_ask_dollars) ?? (m && num(m.no_ask) != null ? m.no_ask / 100 : null);
  const volumeOf = (m) => num(m && m.volume_fp) ?? num(m && m.volume);
  const volume24hOf = (m) => num(m && m.volume_24h_fp) ?? num(m && m.volume_24h);
  const openInterestOf = (m) => num(m && m.open_interest_fp) ?? num(m && m.open_interest);
  /* Size resting at the best bid/ask, as reported beside the price. Null when the
     field is absent — a missing size is not zero contracts. */
  const bestSizeOf = (m, side) => side === 'bid'
    ? (num(m && m.yes_bid_size_fp) ?? num(m && m.yes_bid_size))
    : (num(m && m.yes_ask_size_fp) ?? num(m && m.yes_ask_size));

  /* Official: "previous_price_dollars — Price for the last traded YES contract on
     this market a day ago". It is a precise, exchange-provided comparison point, so
     the dashboard can show a real 1-day move instead of waiting for its own second
     sample. It says nothing about *when* inside that day the move happened. */
  const previousPriceOf = (m) => num(m && m.previous_price_dollars) ?? (num(m && m.previous_price) != null ? m.previous_price / 100 : null);

  /* Midpoint, only when both sides are real quotes and the book is not degenerate.
     A 0-bid / 1-ask pair is an empty book, not a 50¢ market. */
  function midOf(m) {
    const bid = priceOf(m, 'bid');
    const ask = priceOf(m, 'ask');
    if (bid == null || ask == null) return null;
    if (bid <= 0 && ask >= 1) return null;
    if (ask < bid) return null;
    return (bid + ask) / 2;
  }

  function normalizeBook(raw) {
    // Returns {yes: [[priceDollars, contracts], …desc], no: [...], observedAt}
    const ob = raw && (raw.orderbook_fp || raw.orderbook || raw);
    const normSide = (levels) => {
      if (!Array.isArray(levels)) return [];
      return levels.map(([p, q]) => {
        let price = num(p);
        if (price != null && price > 1.01) price = price / 100; // legacy cents
        const qty = num(q) ?? 0;
        return [price, qty];
      }).filter(([p]) => p != null).sort((a, b) => b[0] - a[0]);
    };
    return {
      yes: normSide(ob && (ob.yes_dollars || ob.yes)),
      no: normSide(ob && (ob.no_dollars || ob.no)),
    };
  }

  /* The order book is bids only. A NO bid at p is a YES offer at 1 − p, which is how
     the ask ladder and the "dollars available" figure are built. */
  function impliedAsks(book, depth = 8) {
    if (!book) return [];
    return book.no.slice(0, depth)
      .map(([p, q]) => [Number((1 - p).toFixed(4)), q])
      .sort((a, b) => a[0] - b[0]);
  }

  /* Dollar notional resting in the top `depth` levels of one side. */
  function sideNotional(levels, depth = 8) {
    return levels.slice(0, depth).reduce((s, [p, q]) => s + p * q, 0);
  }

  /* ---------- candlesticks ---------- */
  /* Official response: { ticker, candlesticks: [ { end_period_ts, price:{open_dollars,
     high_dollars, low_dollars, close_dollars, previous_dollars, mean_dollars,…},
     yes_bid:{...}, yes_ask:{...}, volume_fp, open_interest_fp } ] }
     close_dollars is null when nothing traded in the period. We then use the close of
     the quoted bid/ask midpoint and say so (`basis`), rather than inventing a trade. */
  function candlesToPoints(payload) {
    const candles = payload && (payload.candlesticks || payload.candles) || [];
    const out = [];
    for (const c of candles) {
      const ts = num(c.end_period_ts);
      if (ts == null) continue;
      const trade = num(c.price && c.price.close_dollars);
      if (trade != null) {
        out.push({ t: ts * 1000, p: trade, basis: 'last_trade', volume: num(c.volume_fp) });
        continue;
      }
      const bid = num(c.yes_bid && c.yes_bid.close_dollars);
      const ask = num(c.yes_ask && c.yes_ask.close_dollars);
      if (bid != null && ask != null && !(bid <= 0 && ask >= 1) && ask >= bid) {
        out.push({ t: ts * 1000, p: (bid + ask) / 2, basis: 'quote_mid', volume: num(c.volume_fp) });
        continue;
      }
      const carried = num(c.price && c.price.previous_dollars); // last trade before the period
      if (carried != null) out.push({ t: ts * 1000, p: carried, basis: 'previous_trade', volume: num(c.volume_fp) });
    }
    return out.sort((a, b) => a.t - b.t);
  }

  /* ---------- HTTP helpers ---------- */
  function qs(params) {
    if (!params) return '';
    const s = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v != null && v !== '') s.set(k, String(v));
    const str = s.toString();
    return str ? '?' + str : '';
  }

  async function get(path, params, opts = {}) {
    const query = qs(params);
    let res = await fetchJson(DEMO + path + query, opts, 10000);
    if (res.status === 0 && !opts.headers) {
      res = await fetchJson(DEMO_ALT + path + query, opts, 10000);
      if (res.ok) res.viaFallbackHost = true;
    }
    return res;
  }

  /* ---------- signing ---------- */
  /* Kalshi-generated RSA keys are PKCS#1, which WebCrypto cannot import directly, so
     the key is wrapped in a PKCS#8 PrivateKeyInfo on the fly:
     SEQUENCE { INTEGER 0, AlgorithmIdentifier(rsaEncryption), OCTET STRING(pkcs1Der) } */
  function derLen(n) {
    if (n < 0x80) return [n];
    if (n < 0x100) return [0x81, n];
    return [0x82, (n >> 8) & 0xff, n & 0xff];
  }
  function wrapPkcs1ToPkcs8(pkcs1) {
    const algId = [0x30, 0x0d, 0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01, 0x05, 0x00];
    const version = [0x02, 0x01, 0x00];
    const octet = [0x04, ...derLen(pkcs1.length), ...new Uint8Array(pkcs1)];
    const content = [...version, ...algId, ...octet];
    return new Uint8Array([0x30, ...derLen(content.length), ...content]).buffer;
  }

  function pemToArrayBuffer(pem) {
    const isPkcs1 = /RSA PRIVATE KEY/.test(String(pem));
    const b64 = String(pem)
      .replace(/-----BEGIN [^-]+-----/g, '')
      .replace(/-----END [^-]+-----/g, '')
      .replace(/\s+/g, '');
    if (!b64) return null;
    try {
      const bin = atob(b64);
      const buf = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      if (isPkcs1) return wrapPkcs1ToPkcs8(buf.buffer);
      return buf.buffer;
    } catch { return null; }
  }
  const b64Encode = (buffer) => {
    const bytes = new Uint8Array(buffer);
    let str = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      str += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(str);
  };

  async function signPayload(method, path) {
    const settings = store.get('settings', {});
    const keyId = (settings.apiKeyId || '').trim();
    const pem = settings.privateKeyPem || '';
    if (!keyId || !pem.trim()) throw new Error('Demo API key not configured. Add it under Portfolio → Settings. Keys are stored only in this browser.');
    const ts = String(Date.now());
    const signedPath = SIGN_PREFIX + String(path).split('?')[0];
    const msg = new TextEncoder().encode(ts + method.toUpperCase() + signedPath);
    const pkcs8 = pemToArrayBuffer(pem);
    if (!pkcs8) throw new Error('Could not parse the private key PEM.');

    // Try Ed25519 first (Kalshi's default for new keys since 2026-10-01), then RSA-PSS.
    const attempts = [
      { importAlgo: { name: 'Ed25519' }, signAlgo: { name: 'Ed25519' } },
      { importAlgo: { name: 'RSA-PSS', hash: 'SHA-256' }, signAlgo: { name: 'RSA-PSS', saltLength: 32 } },
    ];
    let lastErr = null;
    for (const a of attempts) {
      try {
        const key = await crypto.subtle.importKey('pkcs8', pkcs8, a.importAlgo, false, ['sign']);
        const sig = await crypto.subtle.sign(a.signAlgo, key, msg);
        return { keyId, timestamp: ts, signature: b64Encode(sig) };
      } catch (e) { lastErr = e; }
    }
    throw new Error('Signing failed (tried Ed25519 and RSA-PSS): ' + (lastErr && lastErr.message ? lastErr.message : 'unknown error'));
  }

  async function signedRequest(method, path, body) {
    const { keyId, timestamp, signature } = await signPayload(method, path);
    const headers = {
      'KALSHI-ACCESS-KEY': keyId,
      'KALSHI-ACCESS-TIMESTAMP': timestamp,
      'KALSHI-ACCESS-SIGNATURE': signature,
    };
    if (body != null) headers['Content-Type'] = 'application/json';
    return fetchJson(DEMO + path, { method, headers, body: body != null ? JSON.stringify(body) : undefined }, 12000);
  }

  /* ---------- public market data ---------- */
  /* One status only: the documented enum is unopened|open|closed|settled and the API
     rejects more than one at a time, so the caller asks for one and merges if needed. */
  async function getEvents({ status = 'open', limit = 200, cursor = null, withNested = true } = {}) {
    const base = { status, limit };
    if (cursor) base.cursor = cursor;
    let res = await get('/events', withNested ? { ...base, with_nested_markets: 'true' } : base);
    if (!res.ok && withNested) res = await get('/events', base);
    return res;
  }

  /* Page through /events up to `maxEvents`, following the documented cursor. A cursor
     that comes back unchanged ends the loop (the API ignores an undecodable cursor and
     returns the first page again, so comparing is what stops an infinite loop). */
  async function getEventsPaged({ status = 'open', pageLimit = 200, maxEvents = 600 } = {}) {
    const events = [];
    let cursor = null, pages = 0, lastCursor = null;
    while (events.length < maxEvents && pages < 12) {
      const res = await getEvents({ status, limit: pageLimit, cursor });
      if (!res.ok) return { ok: false, status: res.status, error: res.error, data: { events }, partial: true };
      const batch = (res.data && res.data.events) || [];
      events.push(...batch);
      pages += 1;
      const next = res.data && res.data.cursor;
      if (!next || next === lastCursor || batch.length === 0) break;
      lastCursor = cursor;
      cursor = next;
    }
    return { ok: true, data: { events: events.slice(0, maxEvents) }, pages };
  }

  async function getMarketsForEvent(eventTicker) {
    /* Official: with event_ticker as the only filter every matching market is returned
       in one response and `limit` is not applied. */
    return get('/markets', { event_ticker: eventTicker });
  }

  async function flattenEvents(res) {
    const events = (res && res.data && (res.data.events || res.data.Events)) || [];
    const rows = [];
    for (const ev of events) {
      let markets = ev.markets || [];
      if (!Array.isArray(markets) || markets.length === 0) {
        const mres = await getMarketsForEvent(ev.event_ticker);
        markets = (mres.ok && mres.data && (mres.data.markets || [])) || [];
      }
      for (const m of markets) rows.push({ event: ev, market: m });
    }
    return rows;
  }

  const getOrderbook = (ticker) => get(`/markets/${encodeURIComponent(ticker)}/orderbook`);
  const getExchangeStatus = () => get('/exchange/status');
  const getMarket = (ticker) => get(`/markets/${encodeURIComponent(ticker)}`);

  /* Official: period_interval ∈ {1, 60, 1440} minutes; start_ts/end_ts are seconds;
     at most 5,000 periods per request. */
  async function getCandlesticks({ seriesTicker, ticker, startTs, endTs, periodMinutes }) {
    if (!seriesTicker || !ticker) return { ok: false, status: 0, error: 'series ticker required' };
    return get(`/series/${encodeURIComponent(seriesTicker)}/markets/${encodeURIComponent(ticker)}/candlesticks`, {
      start_ts: Math.floor(startTs), end_ts: Math.floor(endTs), period_interval: periodMinutes,
    });
  }

  /* Backfill a window with the finest legal candle size for it:
       ≤ 3h   1-minute   (5,000-period cap is far away)
       ≤ 30d  60-minute
       else   1440-minute
     `rangeSec` decides; the result carries the interval used so the chart can say it. */
  function candlePlan(rangeSec) {
    if (rangeSec <= 3 * 3600) return 1;
    if (rangeSec <= 30 * 86400) return 60;
    return 1440;
  }

  async function backfill({ seriesTicker, ticker, rangeSec }) {
    const interval = candlePlan(rangeSec);
    const endTs = Math.floor(Date.now() / 1000);
    const startTs = endTs - rangeSec;
    const periods = Math.ceil(rangeSec / (interval * 60));
    if (periods > 5000) return { ok: false, error: `window needs ${periods} periods > 5,000` };
    const res = await getCandlesticks({ seriesTicker, ticker, startTs, endTs, periodMinutes: interval });
    if (!res.ok) return { ok: false, status: res.status, error: res.error };
    return { ok: true, points: candlesToPoints(res.data), interval };
  }

  /* ---------- demo account (signed) ---------- */
  const getBalance = () => signedRequest('GET', '/portfolio/balance');
  const getPositions = () => signedRequest('GET', '/portfolio/positions');
  const getFills = (limit = 50) => signedRequest('GET', '/portfolio/fills' + (limit ? `?limit=${limit}` : ''));
  const getOrders = (status = 'resting') => signedRequest('GET', '/portfolio/orders?status=' + encodeURIComponent(status));

  /* Official request body (quick_start_create_order):
       { ticker, side: "bid"|"ask", count: "1", price: "0.0100",
         time_in_force: "good_till_canceled", self_trade_prevention_type: "taker_at_cross",
         client_order_id: uuid }
     Buying YES is a bid; buying NO is an ask, both priced in YES terms. 201 means
     accepted, not filled — the caller must read remaining_count. */
  function orderBody({ ticker, side, count, price, clientOrderId, timeInForce = 'good_till_canceled' }) {
    return {
      ticker,
      side: side === 'no' ? 'ask' : 'bid',
      count: String(count),
      price: Number(price).toFixed(4),
      time_in_force: timeInForce,
      self_trade_prevention_type: 'taker_at_cross',
      client_order_id: clientOrderId || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(36).slice(2)),
    };
  }
  const createOrderV2 = (args) => signedRequest('POST', '/portfolio/events/orders', orderBody(args));

  return {
    DEMO, DEMO_ALT,
    num, priceOf, noBidOf, noAskOf, volumeOf, volume24hOf, openInterestOf, bestSizeOf,
    previousPriceOf, midOf,
    normalizeBook, impliedAsks, sideNotional, candlesToPoints, candlePlan,
    getEvents, getEventsPaged, flattenEvents, getMarketsForEvent, getOrderbook, getMarket,
    getExchangeStatus, getCandlesticks, backfill,
    getBalance, getPositions, getFills, getOrders, createOrderV2, orderBody, SIGN_PREFIX,
  };
})();
