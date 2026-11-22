// Public-data arithmetic. Nulls stay null; model outputs are never official facts.
export const BASE = 'https://external-api.demo.kalshi.co/trade-api/v2';
export const TOPICS = ['gas', 'elections', 'culture', 'crypto', 'golf'];
export const DOCS = {
  markets: 'https://docs.kalshi.com/api-reference/market/get-markets',
  events: 'https://docs.kalshi.com/api-reference/events/get-events',
  orderbook: 'https://docs.kalshi.com/api-reference/market/get-market-orderbook',
  candles: 'https://docs.kalshi.com/api-reference/market/get-market-candlesticks',
  portfolio: 'https://docs.kalshi.com/api-reference/portfolio/get-balance',
  orders: 'https://docs.kalshi.com/api-reference/orders/create-order-v2',
  ticker: 'https://docs.kalshi.com/websockets/market-ticker',
};
export const LABELS = {all: 'All topics', gas: 'Gas prices', elections: 'Elections', culture: 'Culture', crypto: 'Crypto', golf: 'Golf'};
export function topicFor(event) {
  if (TOPICS.includes(event?.topic) && event?.topic_rule) return event.topic;
  const metadata = event?.series_metadata || {};
  const words = [metadata.title, ...(metadata.tags || []), event?.title].filter(Boolean).join(' ').toLowerCase();
  const category = String(metadata.category || '').toLowerCase();
  const matches = new Set();
  if (/\b(gasoline|gas prices?|gallon of gas|pump prices?)\b/.test(words)) matches.add('gas');
  if (/\b(elections?|electoral|presidential nominee|presidential nomination|democratic nominee|republican nominee)\b/.test(words)) matches.add('elections');
  if (category === 'crypto' || /\b(bitcoin|ethereum|cryptocurrency|crypto)\b/.test(words)) matches.add('crypto');
  if (/\b(golf|pga|lpga|ryder cup)\b/.test(words)) matches.add('golf');
  if (category === 'culture' || /\b(grammy|oscars?|emmy|box office|movie|album|celebrity)\b/.test(words)) matches.add('culture');
  return matches.size === 1 ? [...matches][0] : null;
}
export function numeric(value) {
  if (value === '' || value === null || value === undefined || typeof value === 'boolean' || typeof value === 'object') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
export function price(value) { const n = numeric(value); return n !== null && n >= 0 && n <= 1 ? n : null; }
export function qty(value) { const n = numeric(value); return n !== null && n >= 0 ? n : null; }
export function dollars(value, compact = false) {
  const n = numeric(value);
  return n === null ? '—' : new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', maximumFractionDigits:2, ...(compact ? {notation:'compact'} : {})}).format(n);
}
export function count(value) { const n = qty(value); return n === null ? '—' : new Intl.NumberFormat('en-US', {maximumFractionDigits:2, notation:n >= 100000 ? 'compact' : 'standard'}).format(n); }
export function marketUrl(ticker) { return `${BASE}/markets/${encodeURIComponent(ticker)}`; }
export function eventUrl(ticker) { return `${BASE}/events/${encodeURIComponent(ticker)}`; }
export function bookUrl(ticker) { return `${marketUrl(ticker)}/orderbook`; }
export function sample(market) { return price(market?.last_price_dollars); }
export function delta(previous, current) {
  const a = price(previous), b = price(current);
  return a === null || b === null ? null : (Math.round(b * 1000000) - Math.round(a * 1000000)) / 1000000;
}
export function swing(previous, current) { const d = delta(previous, current); return d !== null && Math.abs(d) >= 0.10 ? d : null; }
export function resolution(market) { return market?.status === 'finalized' && ['yes', 'no'].includes(market?.result) ? market.result.toUpperCase() : null; }
export function notional(market) { return qty(market?.dollar_volume); }
// Retained export for older tests/consumers, deliberately no longer estimates turnover.
export function estimate(market) { return notional(market); }
export function qualifies(market) {
  const bid = price(market?.yes_bid_dollars), ask = price(market?.yes_ask_dollars);
  const size = qty(market?.yes_ask_size_fp);
  return market?.status === 'active' && bid !== null && ask !== null && ask > bid &&
    Math.round((ask - bid) * 1000000) <= 40000 && size !== null && size >= 10 && ask > 0 && ask < 1;
}
export function sumConfirmed(values) {
  return values.length && values.every(value => numeric(value) !== null) ? values.reduce((sum, value) => sum + Number(value), 0) : null;
}
export function eventGroups(markets, events, metric = 'notional') {
  const groups = new Map();
  for (const market of markets) {
    const event = events.get(market.event_ticker);
    if (!event) continue;
    if (!groups.has(market.event_ticker)) groups.set(market.event_ticker, {event, markets:[]});
    groups.get(market.event_ticker).markets.push(market);
  }
  const result = [...groups.values()].map(group => ({...group,
    notional: sumConfirmed(group.markets.map(notional)),
    contracts: sumConfirmed(group.markets.map(market => qty(market.volume_24h_fp))),
  }));
  const value = group => metric === 'contracts' ? group.contracts : group.notional;
  return result.sort((a,b) => (value(b) ?? -1) - (value(a) ?? -1) || (b.contracts ?? -1) - (a.contracts ?? -1));
}
export function normalizeBook(payload, observedAt, source) {
  if (!payload?.orderbook_fp || !Array.isArray(payload.orderbook_fp.yes_dollars) || !Array.isArray(payload.orderbook_fp.no_dollars)) return null;
  const parse = levels => levels.map(([p,q]) => ({price:price(p), quantity:qty(q)})).filter(level => level.price !== null && level.quantity !== null && level.quantity > 0).sort((a,b) => b.price-a.price);
  const yes = parse(payload.orderbook_fp.yes_dollars), no = parse(payload.orderbook_fp.no_dollars);
  const asks = bids => bids.map(level => ({...level,price:Math.round((1-level.price)*1e6)/1e6,derived:true})).sort((a,b) => a.price-b.price);
  return {yesBids:yes,noBids:no,yesAsks:asks(no),noAsks:asks(yes),observedAt,source};
}
export class MoveDetector {
  constructor(windowMs=60000) { this.windowMs=windowMs; this.points=new Map(); }
  observe(ticker,value,at) {
    if (price(value) === null || !Number.isFinite(at)) return null;
    const old=this.points.get(ticker)||[];
    if(old.length && at<=old.at(-1).at)return null;
    const points=old.filter(point=>at-point.at<=this.windowMs);
    let change=null;
    if(points.length && value!==points.at(-1).value) {
      const values=points.map(point=>point.value);
      const from=value>points.at(-1).value?Math.min(...values):Math.max(...values);
      const move=swing(from,value);
      if(move!==null)change={from,to:value,change:move,at};
    }
    this.points.set(ticker,(change?[]:points).concat({value,at}).slice(-1000));
    return change;
  }
  reset() { this.points.clear(); }
}
// Compatibility functions for historical local ledgers, never an exchange-fill claim.
export function paperBuy(market,topic,strategy,at=new Date().toISOString()) {
  const ask=price(market?.yes_ask_dollars),size=qty(market?.yes_ask_size_fp);
  if(market?.status!=='active'||ask===null||ask<=0||ask>=1||size===null||size<1)return null;
  return {ticker:market.ticker,eventTicker:market.event_ticker,topic,strategy,entry:ask,at,result:null};
}
export function paperPnl(trade,market) {
  const result=resolution(market);
  if(result)return(result==='YES'?1:0)-trade.entry;
  const bid=price(market?.yes_bid_dollars);
  return bid===null?null:bid-trade.entry;
}
export function csvCell(value) {
  let text=String(value??'');
  if(/^[=+\-@\t\r]/.test(text))text="'"+text; // prevent spreadsheet formula injection
  return '"'+text.replaceAll('"','""')+'"';
}
