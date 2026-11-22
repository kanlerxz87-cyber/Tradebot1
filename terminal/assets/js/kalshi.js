/* kalshi.js — Kalshi Trade API v2 (demo) client.
   Public market-data endpoints need no authentication and are called directly
   from the browser. Portfolio endpoints require a signed request; signing uses
   WebCrypto with the user's demo key (stored in localStorage only — never committed).

   Notes:
   - Sign string is `${timestampMs}${METHOD}${/trade-api/v2 + path}` (no query string).
   - Browser WebSocket handshakes cannot carry custom headers, so live streaming
     requires a proxy; the dashboard defaults to REST polling. See flagged.html.
   - Prices/counts are read defensively: fixed-point dollar strings (current)
     or legacy integer cents (older payloads). */
'use strict';

const Kalshi = (() => {
  const DEMO = SITE.demoRest;
  const DEMO_ALT = SITE.demoRestAlt;
  const SIGN_PREFIX = '/trade-api/v2';

  const num = (v) => {
    if (v == null) return null;
    const n = typeof v === 'number' ? v : parseFloat(v);
    return Number.isFinite(n) ? n : null;
  };

  /* ---------- field normalization (fixed-point dollars or legacy cents) ---------- */
  const priceOf = (m, side) => {
    if (!m) return null;
    if (side === 'bid') return num(m.yes_bid_dollars) ?? (num(m.yes_bid) != null ? m.yes_bid / 100 : null);
    if (side === 'ask') return num(m.yes_ask_dollars) ?? (num(m.yes_ask) != null ? m.yes_ask / 100 : null);
    if (side === 'last') return num(m.last_price_dollars) ?? (num(m.last_price) != null ? m.last_price / 100 : null) ?? num(m.previous_price_dollars);
    if (side === 'prev') return num(m.previous_price_dollars) ?? (num(m.previous_price) != null ? m.previous_price / 100 : null);
    return null;
  };
  const noBidOf = (m) => num(m && m.no_bid_dollars) ?? (m && num(m.no_bid) != null ? m.no_bid / 100 : null);
  const noAskOf = (m) => num(m && m.no_ask_dollars) ?? (m && num(m.no_ask) != null ? m.no_ask / 100 : null);
  const volumeOf = (m) => num(m && m.volume_fp) ?? num(m && m.volume) ?? 0;
  const volume24hOf = (m) => num(m && m.volume_24h_fp) ?? num(m && m.volume_24h) ?? null;
  const openInterestOf = (m) => num(m && m.open_interest_fp) ?? num(m && m.open_interest) ?? 0;
  const estNotionalOf = (m) => volumeOf(m) * (priceOf(m, 'last') ?? priceOf(m, 'bid') ?? 0.5);

  function normalizeBook(raw) {
    // Returns {yes: [[priceDollars, contracts], ...desc], no: [...]}
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

  /* ---------- HTTP helpers ---------- */
  function qs(params) {
    if (!params) return '';
    const s = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v != null && v !== '') s.set(k, v);
    const str = s.toString();
    return str ? '?' + str : '';
  }

  async function get(path, params, opts = {}) {
    const query = qs(params);
    let res = await fetchJson(DEMO + path + query, opts, 10000);
    if (res.status === 0 && !opts.headers) {
      // host fallback (legacy alias host)
      res = await fetchJson(DEMO_ALT + path + query, opts, 10000);
    }
    return res;
  }

  /* ---------- signing ---------- */
  /* Kalshi-generated RSA keys are PKCS#1 ("BEGIN RSA PRIVATE KEY"), which WebCrypto
     cannot import directly. Wrap them in a PKCS#8 PrivateKeyInfo (RFC 5208) on the fly:
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
    const isPkcs1 = /BEGIN RSA PRIVATE KEY/.test(String(pem));
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
    const signedPath = SIGN_PREFIX + path.split('?')[0];
    const msg = new TextEncoder().encode(ts + method.toUpperCase() + signedPath);
    const pkcs8 = pemToArrayBuffer(pem);
    if (!pkcs8) throw new Error('Could not parse the private key PEM. Expected a PEM block (e.g. -----BEGIN PRIVATE KEY-----).');

    // Try Ed25519 first (Kalshi default for new keys since 2026-10-01), then RSA-PSS.
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

  async function authHeaders(method, path) {
    const { keyId, timestamp, signature } = await signPayload(method, path);
    return {
      'KALSHI-ACCESS-KEY': keyId,
      'KALSHI-ACCESS-TIMESTAMP': timestamp,
      'KALSHI-ACCESS-SIGNATURE': signature,
    };
  }

  /* ---------- public market data ---------- */
  async function getEvents({ status = 'open', limit = 200 } = {}) {
    // with_nested_markets embeds markets; fall back gracefully if unsupported.
    let res = await get('/events', { status, limit, with_nested_markets: 'true' });
    if (!res.ok) res = await get('/events', { status, limit });
    return res;
  }

  async function getMarketsForEvent(eventTicker) {
    return get('/markets', { event_ticker: eventTicker, limit: 200 });
  }

  async function flattenEvents(res) {
    const events = (res.data && (res.data.events || res.data.Events)) || [];
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

  /* ---------- demo account (signed) ---------- */
  const getBalance = () => signedRequest('GET', '/portfolio/balance');
  const getPositions = () => signedRequest('GET', '/portfolio/positions');
  const getFills = (limit = 50) => signedRequest('GET', '/portfolio/fills' + (limit ? `?limit=${limit}` : ''));
  const getOrders = (status = 'resting') => signedRequest('GET', '/portfolio/orders?status=' + encodeURIComponent(status));

  /* V2 order surface: POST /portfolio/events/orders (bid/ask, fixed-point dollar price).
     Untested against the live demo from this session — see flagged.html #4. */
  const createOrderV2 = ({ ticker, side, count, price, clientOrderId }) => signedRequest('POST', '/portfolio/events/orders', {
    ticker,
    side: side === 'no' ? 'ask' : 'bid',
    count: String(count),
    price: Number(price).toFixed(4),
    time_in_force: 'good_till_canceled',
    self_trade_prevention_type: 'taker_at_cross',
    client_order_id: clientOrderId || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()),
  });

  return {
    DEMO, DEMO_ALT,
    num, priceOf, noBidOf, noAskOf, volumeOf, volume24hOf, openInterestOf, estNotionalOf,
    normalizeBook, getEvents, flattenEvents, getMarketsForEvent, getOrderbook, getExchangeStatus,
    getBalance, getPositions, getFills, getOrders, createOrderV2, authHeaders, SIGN_PREFIX,
  };
})();
