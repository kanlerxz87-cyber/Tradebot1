// Kalshi-derived arithmetic and deliberately conservative topic rules. No private account data.
export const BASE = 'https://external-api.demo.kalshi.co/trade-api/v2';
export const DOCS = {
  markets: 'https://docs.kalshi.com/api-reference/market/get-markets',
  events: 'https://docs.kalshi.com/api-reference/events/get-events',
  orderbook: 'https://docs.kalshi.com/api-reference/market/get-market-orderbook',
  candles: 'https://docs.kalshi.com/api-reference/market/get-market-candlesticks',
  portfolio: 'https://docs.kalshi.com/api-reference/portfolio/get-balance',
  orders: 'https://docs.kalshi.com/api-reference/orders/create-order-v2'
};
export const TOPICS = ['gas', 'elections', 'culture', 'crypto', 'golf'];
export function topicFor(event) {
  const title = String(event?.title || '').toLowerCase();
  const category = String(event?.category || '').toLowerCase();
  if (/\b(gasoline|gas prices?|gallon of gas|pump prices?)\b/.test(title)) return 'gas';
  if (category === 'elections' && /\b(elect\w*|vot\w*|ballot|presiden\w*|senat\w*|governor\w*|mayor\w*|congress\w*|primary|party)\b/.test(title)) return 'elections';
  if (/\b(bitcoin|ethereum|ether|crypto|dogecoin|solana|btc|eth)\b/.test(title)) return 'crypto';
  if (/\b(golf|pga|masters|ryder cup|us open golf|open championship)\b/.test(title)) return 'golf';
  if (/\b(grammy|oscar|emmy|movie|film|music|album|artist|celebrity|box office|tv show|television|tiktok|youtube)\b/.test(title)) return 'culture';
  return null; // no guess from ticker prefixes or broad categories
}
export function price(value) {
  if (value === '' || value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 && n <= 1 ? n : null;
}
export function qty(value) {
  if (value === '' || value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n : null;
}
export function dollars(value) { return value === null ? '—' : '$' + value.toFixed(2); }
export function count(value) { return value === null ? '—' : new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value); }
export function marketUrl(ticker) { return `${BASE}/markets/${encodeURIComponent(ticker)}`; }
export function eventUrl(ticker) { return `${BASE}/events/${encodeURIComponent(ticker)}`; }
export function bookUrl(ticker) { return `${marketUrl(ticker)}/orderbook?depth=5`; }
export function sample(market) { return price(market?.last_price_dollars); }
// A simple transparent screen, NOT a forecast, model probability, recommendation, or ROI claim.
export function qualifies(market) {
  const bid = price(market?.yes_bid_dollars), ask = price(market?.yes_ask_dollars);
  const volume = qty(market?.volume_24h_fp);
  return market?.status === 'active' && bid !== null && ask !== null && ask > bid && ask - bid <= 0.08 && volume !== null && volume >= 100 && ask >= 0.12 && ask <= 0.88;
}
export function delta(previous, current) {
  const a = price(previous), b = price(current);
  return a === null || b === null ? null : Math.round((b - a) * 10000) / 10000;
}
export function swing(previous, current) { const d = delta(previous, current); return d !== null && Math.abs(d) >= 0.10 - 1e-9 ? d : null; }
export function resolution(market) { return market?.status === 'finalized' && ['yes', 'no'].includes(market?.result) ? market.result.toUpperCase() : null; }
export function estimate(market) { const p = sample(market), v = qty(market?.volume_24h_fp); return p === null || v === null ? null : p * v; }
// Paper trading: ask entry, bid mark, no fees/slippage; missing quote never marks or executes.
export function paperBuy(market, topic, strategy, at = new Date().toISOString()) {
  const ask = price(market?.yes_ask_dollars);
  if (market?.status !== 'active' || ask === null || ask <= 0 || ask >= 1) return null;
  return { ticker: market.ticker, eventTicker: market.event_ticker, topic, strategy, entry: ask, at, result: null };
}
export function paperPnl(trade, market) {
  const resolved = resolution(market);
  if (resolved) return (resolved === 'YES' ? 1 : 0) - trade.entry;
  const bid = price(market?.yes_bid_dollars);
  return bid === null ? null : bid - trade.entry;
}
