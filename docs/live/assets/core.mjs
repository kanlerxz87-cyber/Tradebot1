// Pure functions for the Kalshi demo live console.
//
// Every rule here traces to an official source recorded in ./data/sources.json:
//   S4/S5  orderbook shape, bids only, implied ask = 1 - opposite best bid, empty book != 0
//   S6     candlestick fields and period intervals
//   S8/S9  status and result enums
//   S12/S13 fee formula and rounding
//   S16/S17 category/tag routing
//   S21    previous_* fields are a day old and must not be used for swing detection
// There is no network access, no Date.now() default and no randomness in this file, so every
// function is directly testable and reproducible.

/* ------------------------------------------------------------------ numbers */

/** Parse a Kalshi money/count string ("0.5600", "13.00") or number. Empty and junk are null, never 0. */
export function num(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const text = String(value).trim();
  if (text === '') return null;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

/** A price of exactly 0.0000 from the API means "no such quote", not a free contract. */
function price(value) {
  const parsed = num(value);
  return parsed === null || parsed <= 0 ? null : parsed;
}

/** Contract size/count: 0.00 is a genuinely empty level, so zero is kept. */
function size(value) {
  const parsed = num(value);
  return parsed === null || parsed < 0 ? null : parsed;
}

export const fmtCents = (dollars) =>
  dollars === null || dollars === undefined ? '—' : `${Math.round(dollars * 100)}¢`;

export const fmtDollars = (dollars) =>
  dollars === null || dollars === undefined
    ? '—'
    : `$${dollars.toFixed(2)}`;

export const fmtSigned = (delta) => {
  if (delta === null || delta === undefined) return '—';
  const cents = Math.round(delta * 100);
  return `${cents > 0 ? '+' : cents < 0 ? '−' : '±'}${Math.abs(cents)}¢`;
};

export const fmtQty = (qty) =>
  qty === null || qty === undefined ? '—' : Math.abs(qty) >= 1000 ? Math.round(qty).toLocaleString('en-US') : qty.toFixed(2);

const round6 = (value) => Math.ceil(value * 1e6 - 1e-9) / 1e6;

/* -------------------------------------------------------------------- fees */

/**
 * Kalshi trading fee, S12/S13.
 * taker: round up(M x 0.07 x C x P x (1-P)); maker: the same with 0.0175.
 * The schedule states "round up ... to a centicent" = $0.000001, and S13 confirms the fee is a
 * six-decimal amount. Rounding to the member's balance precision ($0.01 non-direct, $0.0001
 * direct) is applied by the exchange's rounding accumulator per order, which is a separate step
 * this console does not reproduce; the flag page says so.
 */
export function fee(priceDollars, contracts, { maker = false, multiplier = 1 } = {}) {
  const p = num(priceDollars);
  const c = num(contracts);
  if (p === null || c === null || p <= 0 || p >= 1 || c <= 0) return 0;
  const rate = maker ? 0.0175 : 0.07;
  return round6(multiplier * rate * c * p * (1 - p));
}

/**
 * The fee as the published General Trading Fees Table shows it: rounded up to the cent.
 * S13 says the exchange itself charges at six decimals and then rounds the *balance* to the
 * member's precision ($0.01 non-direct), so this reproduces the table, not the accumulator.
 */
export function feeCents(priceDollars, contracts, options = {}) {
  const raw = fee(priceDollars, contracts, options);
  return Math.ceil(raw * 100 - 1e-9) / 100;
}

/** Both published columns for one price. */
export function feeScheduleRow(priceDollars) {
  const p = num(priceDollars);
  if (p === null) return null;
  return { oneContract: feeCents(p, 1), hundredContracts: feeCents(p, 100) };
}

/* -------------------------------------------------------------------- quotes */

/**
 * Normalise one market object from GET /markets or GET /events?with_nested_markets=true.
 * `cfg` maps field names so a different API version can be used without touching logic:
 * yesBid yes_ask_dollars no_bid_dollars no_ask_dollars last_price_dollars
 * yesBidSize yes_bid_size_fp yesAskSize yes_ask_size_fp.
 */
export function quoteOf(market, cfg = {}) {
  const f = {
    yesBid: 'yes_bid_dollars',
    yesAsk: 'yes_ask_dollars',
    noBid: 'no_bid_dollars',
    noAsk: 'no_ask_dollars',
    last: 'last_price_dollars',
    yesBidSize: 'yes_bid_size_fp',
    yesAskSize: 'yes_ask_size_fp',
    ...cfg,
  };
  const yesBid = price(market?.[f.yesBid]);
  const yesAsk = price(market?.[f.yesAsk]);
  const noBid = price(market?.[f.noBid]);
  const last = price(market?.[f.last]);
  // S4: a YES ask is implied by the best NO bid. A "1.0000" ask is what the API reports when the
  // NO side of the book is empty; paired with no_bid 0.0000 it is not a real offer, and reading it
  // as one would manufacture a 57c mid out of a 14c bid. Both cases are excluded here.
  const impliedAsk = noBid === null ? null : Math.round((1 - noBid) * 1e4) / 1e4;
  const ask = yesAsk !== null && yesAsk < 0.9999 ? yesAsk : impliedAsk;
  const twoSided = yesBid !== null && ask !== null && ask > yesBid;
  const mid = twoSided ? Math.round(((yesBid + ask) / 2) * 1e4) / 1e4 : null;
  // S4: fall back in a documented order, never invent a mid from one side.
  const mark = mid ?? last ?? yesBid ?? ask ?? null;
  return {
    yesBid,
    yesAsk: ask,
    noBid,
    last,
    mid,
    mark,
    basis: mid !== null ? 'mid' : last !== null ? 'last trade' : yesBid !== null ? 'best bid' : ask !== null ? 'best ask' : 'none',
    twoSided,
    spread: twoSided ? Math.round((ask - yesBid) * 1e4) / 1e4 : null,
    yesBidSize: size(market?.[f.yesBidSize]),
    yesAskSize: size(market?.[f.yesAskSize]),
  };
}

/**
 * Order book maths for GET /markets/{ticker}/orderbook (S4/S5).
 * Input is the raw `orderbook_fp` object. Levels are returned best first.
 */
export function bookOf(orderbookFp, cfg = {}) {
  const sides = {
    yes: 'yes_dollars',
    no: 'no_dollars',
    ...cfg,
  };
  const read = (key) => {
    const rows = orderbookFp?.[sides[key]];
    if (!Array.isArray(rows)) return [];
    return rows
      .map(([p, q]) => ({ price: price(p), qty: size(q) }))
      .filter((row) => row.price !== null && row.qty !== null && row.qty > 0)
      .sort((a, b) => b.price - a.price); // S4: API sends ascending with best last
  };
  const yes = read('yes');
  const no = read('no');
  const bestYesBid = yes.length ? yes[0].price : null;
  const bestNoBid = no.length ? no[0].price : null;
  const yesAsk = bestNoBid === null ? null : Math.round((1 - bestNoBid) * 1e4) / 1e4;
  const noAsk = bestYesBid === null ? null : Math.round((1 - bestYesBid) * 1e4) / 1e4;
  const twoSided = yesAsk !== null && bestYesBid !== null && yesAsk > bestYesBid;
  return {
    yes,
    no,
    bestYesBid,
    bestNoBid,
    yesAsk,
    noAsk,
    empty: yes.length === 0 && no.length === 0,
    twoSided,
    spread: twoSided ? Math.round((yesAsk - bestYesBid) * 1e4) / 1e4 : null,
    mid: twoSided ? Math.round(((bestYesBid + yesAsk) / 2) * 1e4) / 1e4 : null,
  };
}

/** Contracts available to buy YES at or below `limitPrice`: NO bids in [1-limit, 1]. */
export function contractsForYesAtMost(book, limitPrice) {
  const bookNo = book?.no ?? [];
  return bookNo
    .filter((level) => 1 - level.price <= limitPrice + 1e-9)
    .reduce((total, level) => total + level.qty, 0);
}

/** Contracts available to sell YES at or above `limitPrice`: YES bids in [limit, 1]. */
export function contractsForYesAtLeast(book, limitPrice) {
  const bookYes = book?.yes ?? [];
  return bookYes
    .filter((level) => level.price >= limitPrice - 1e-9)
    .reduce((total, level) => total + level.qty, 0);
}

/**
 * Walk the book to fill `contracts` YES at or better than the implied ask, returning the volume
 * weighted price actually paid. Null when the book cannot fill the size, which is reported rather
 * than padded with a better price.
 */
export function walkYesBuy(book, contracts) {
  let left = num(contracts);
  if (left === null || left <= 0) return null;
  let cost = 0;
  for (const level of [...(book?.no ?? [])].sort((a, b) => b.price - a.price)) {
    const levelPrice = Math.round((1 - level.price) * 1e4) / 1e4;
    const take = Math.min(left, level.qty);
    cost += take * levelPrice;
    left -= take;
    if (left <= 1e-9) return { filled: num(contracts), averagePrice: cost / num(contracts), complete: true };
  }
  const filled = num(contracts) - left;
  return { filled, averagePrice: filled > 0 ? cost / filled : null, complete: false };
}

/* -------------------------------------------------------------------- swings */

/** Absolute threshold in dollars, inclusive, symmetric. */
export const THRESHOLD = 0.1;

/**
 * Swing between two observations of the same market (S21: never use previous_* fields here).
 * Returns null unless both marks exist and the move is >= $0.10 in either direction.
 */
export function swing(previous, next, threshold = THRESHOLD) {
  const a = num(previous);
  const b = num(next);
  if (a === null || b === null) return null;
  const delta = Math.round((b - a) * 1e4) / 1e4;
  if (Math.abs(delta) + 1e-9 < threshold) return null;
  return {
    previous: a,
    current: b,
    delta,
    direction: delta > 0 ? 'up' : 'down',
    // percentage of the previous price, expressed in its natural unit
    percentOfPrevious: a > 0 ? Math.round((delta / a) * 1e4) / 100 : null,
  };
}

/* ------------------------------------------------------------- triage score */

/**
 * A transparent 0-100 heuristic used only to order the second feed. It is not a forecast, not an
 * expected return and not Kalshi data. Weights are fixed and published on the methodology page.
 */
export function triageScore({ moveAbs = 0, sizeAtTouch = null, spread = null, volume24h = null, watched = false } = {}) {
  const parts = {
    move: Math.min(40, (Math.abs(moveAbs) / 0.5) * 40),
    depth: sizeAtTouch === null ? 0 : Math.min(30, (Math.log10(1 + Math.max(0, sizeAtTouch)) / 3) * 30),
    spread: spread === null ? 0 : Math.max(0, Math.min(20, (0.10 - Math.min(spread, 0.1)) * 200)),
    volume: volume24h === null ? 0 : Math.min(10, (Math.log10(1 + Math.max(0, volume24h)) / 4) * 10),
  };
  const watchBonus = watched ? 0 : 0; // reserved: no bonus is applied today, documented so it cannot drift
  const total = parts.move + parts.depth + parts.spread + parts.volume + watchBonus;
  return { score: Math.round(Math.min(100, total)), parts };
}

/* --------------------------------------------------------------------- topics */

export const TOPICS = [
  { id: 'gas', label: 'Gas prices' },
  { id: 'elections', label: 'Elections' },
  { id: 'culture', label: 'Culture' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'golf', label: 'Golf' },
];

/**
 * Routing rules, all from the official API (S16-S18). Kalshi publishes no "Gas" and no "Culture"
 * category, so each topic names the official selector it uses and says when it is derived.
 * `keywords` is only a fallback for the demo catalogue, which does not carry every production
 * series; a keyword match is labelled as such on every row that uses it.
 */
export const TOPIC_RULES = [
  {
    topic: 'gas',
    official: 'series tag "Oil & Gas" or "Oil and energy"',
    selectors: [{ param: 'tags', value: 'Oil & Gas' }, { param: 'tags', value: 'Oil and energy' }],
    keywords: ['gas price', 'gasoline', 'per gallon', 'aaa'],
    derived: false,
    note: 'Kalshi files US gas price (KXAAAGASM) under Economics with tags Oil & Gas / Oil and energy (S18); there is no Gas category (S16).',
  },
  {
    topic: 'elections',
    official: 'series category "Elections"',
    selectors: [{ param: 'category', value: 'Elections' }],
    keywords: ['election', 'vote', 'ballot', 'primary', 'senate', 'house', 'governor', 'president'],
    derived: false,
    note: 'Elections is a published category in the official category list (S16).',
  },
  {
    topic: 'culture',
    official: 'series category "Entertainment"',
    selectors: [{ param: 'category', value: 'Entertainment' }],
    keywords: ['movie', 'film', 'album', 'grammy', 'oscar', 'emmy', 'box office', 'tv', 'celebrity', 'award', 'music'],
    derived: true,
    note: 'Kalshi publishes no Culture category (S16). This tab maps the request to the official Entertainment category and says so on every row.',
  },
  {
    topic: 'crypto',
    official: 'series category "Crypto"',
    selectors: [{ param: 'category', value: 'Crypto' }],
    keywords: ['bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'doge', 'xrp', 'crypto'],
    derived: false,
    note: 'Crypto is a published category with its own tag list (S16).',
  },
  {
    topic: 'golf',
    official: 'series tag "Golf"',
    selectors: [{ param: 'tags', value: 'Golf' }],
    keywords: ['golf', 'pga', 'ryder cup', 'masters', 'president cup'],
    derived: false,
    note: 'Golf is a tag inside Sports, not a category (S16, S17).',
  },
];

/**
 * Decide whether a series belongs to a topic, and record which rule decided it.
 * Order: official selector first (category list, then tags), keyword fallback second.
 */
export function routeSeries(series, topic, rules = TOPIC_RULES) {
  const rule = rules.find((entry) => entry.topic === topic);
  if (!rule || !series) return { matched: false, rule: null, evidence: null };
  const categories = Array.isArray(series.categories) ? series.categories : [];
  const tags = Array.isArray(series.tags) ? series.tags : [];
  for (const selector of rule.selectors) {
    if (selector.param === 'category' && categories.includes(selector.value)) {
      return { matched: true, rule: `category "${selector.value}"`, evidence: 'S16/S17 series.categories', official: true, derived: Boolean(rule.derived) };
    }
    if (selector.param === 'tags' && tags.includes(selector.value)) {
      return { matched: true, rule: `tag "${selector.value}"`, evidence: 'S17 series.tags', official: true, derived: Boolean(rule.derived) };
    }
  }
  const haystack = `${series.ticker ?? ''} ${series.title ?? ''}`.toLowerCase();
  const keyword = rule.keywords.find((word) => haystack.includes(word));
  if (keyword) {
    return { matched: true, rule: `keyword "${keyword}"`, evidence: 'fallback, not an official selector', official: false, derived: true };
  }
  return { matched: false, rule: null, evidence: null };
}

/* ----------------------------------------------------------------- resolution */

/**
 * Resolution state of one market, from the official status/result enums (S8, S9).
 * Nothing is inferred: until result is yes/no/scalar the row says unresolved.
 */
export function resolutionOf(market) {
  const result = String(market?.result ?? '').trim().toLowerCase();
  const status = String(market?.status ?? '').trim().toLowerCase();
  const settled = result === 'yes' || result === 'no' || result === 'scalar';
  const terminal = status === 'finalized';
  return {
    status: status || null,
    result: settled ? result : null,
    settledValue: num(market?.settlement_value_dollars),
    settlementTs: market?.settlement_ts || null,
    decided: settled,
    finalized: terminal,
    label: settled ? `Resolved ${result.toUpperCase()}` : status === 'determined' ? 'Determined, settlement running' : status === 'closed' ? 'Closed, awaiting determination' : status === 'finalized' ? 'Finalized, no result field' : 'Open',
  };
}

/* ------------------------------------------------------------------ portfolio */

/**
 * Simulated fill ledger. Book-keeping only: no order is ever sent anywhere.
 * Cash is reduced by price x contracts + fee; a position's mark value is contracts x mark.
 */
export function positionValue(position, mark) {
  const contracts = num(position?.contracts) ?? 0;
  const price = num(mark);
  if (price === null) return null; // a missing mark is unknown, not zero
  return contracts * price;
}

export function portfolioSummary(ledger, marks = {}) {
  let cash = num(ledger?.cash) ?? 0;
  let realised = 0;
  let fees = 0;
  const positions = Array.isArray(ledger?.positions) ? ledger.positions : [];
  let openValue = 0;
  let unpriced = 0;
  for (const position of positions) {
    // An explicitly null mark means "could not be priced"; only a market that is absent from the
    // marks map falls back to the entry price, and the caller is told how many it could not price.
    const supplied = Object.prototype.hasOwnProperty.call(marks, position.ticker);
    const value = positionValue(position, supplied ? marks[position.ticker] : position.entryPrice);
    if (value === null) unpriced += 1;
    else openValue += value;
  }
  for (const fill of Array.isArray(ledger?.fills) ? ledger.fills : []) {
    fees += num(fill.fee) ?? 0;
    if (fill.realised !== undefined && fill.realised !== null) realised += num(fill.realised) ?? 0;
  }
  return {
    cash,
    openValue,
    equity: cash + openValue,
    realised,
    fees,
    unpricedPositions: unpriced,
    openPositions: positions.length,
  };
}

/**
 * Mark-to-market a YES position at resolution: a YES result pays $1 per contract, NO pays $0.
 * The settlement fee is zero (S12).
 */
export function settlementOf(position, result) {
  const contracts = num(position?.contracts) ?? 0;
  const entry = num(position?.entryPrice);
  const feePaid = num(position?.fee) ?? 0;
  if (entry === null) return null;
  const verdict = String(result ?? '').toLowerCase();
  if (verdict !== 'yes' && verdict !== 'no') return null;
  const payout = verdict === 'yes' ? contracts : 0;
  return { payout, realised: Math.round((payout - contracts * entry - feePaid) * 1e6) / 1e6 };
}

/* ----------------------------------------------------------------- chart range */

/** Time windows offered by the chart. Values are milliseconds. */
export const RANGES = [
  { id: '30s', label: '30 seconds', ms: 30_000, bucketMs: 5_000 },
  { id: '5m', label: '5 minutes', ms: 300_000, bucketMs: 15_000 },
  { id: '1h', label: '1 hour', ms: 3_600_000, bucketMs: 60_000 },
  { id: '6h', label: '6 hours', ms: 21_600_000, bucketMs: 3_600_000 },
  { id: '24h', label: '24 hours', ms: 86_400_000, bucketMs: 3_600_000 },
];

/** Largest bucket interval the candlestick endpoint accepts is 1440 minutes (S6). */
export const CANDLE_INTERVALS = [1, 60, 1440];

/** Choose the candlestick interval for a window without exceeding the official enum. */
export function candleIntervalFor(rangeMs) {
  if (rangeMs <= 3_600_000) return 1;
  if (rangeMs <= 86_400_000) return 60;
  return 1440;
}

/** Keep the points of a sample series inside [now - ms, now]. */
export function withinRange(samples, nowMs, rangeMs) {
  const from = nowMs - rangeMs;
  return (Array.isArray(samples) ? samples : [])
    .filter((sample) => num(sample?.t) !== null && sample.t >= from && sample.t <= nowMs + 1000)
    .sort((a, b) => a.t - b.t);
}
