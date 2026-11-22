/* topics.js — the five tracked topic verticals and the keyword classifier.
   Classifier works on free-text fields returned by the Kalshi API
   (event title, subtitle, category, series ticker). No hardcoded market data. */
'use strict';

const TOPICS = [
  {
    id: 'gas', name: 'Gas Prices', short: 'Gas', cls: 'gas', color: '#ffc44d',
    keywords: ['gas price', 'gasoline', 'natural gas', 'petrol', 'crude', 'wti', 'brent oil', 'fuel price', 'gas'],
    blurb: 'Retail gasoline and energy contracts — tracked against public EIA reference data.',
    sources: [
      ['EIA — Gasoline & Diesel Fuel Update', 'https://www.eia.gov/petroleum/gasdiesel/'],
      ['EIA — US retail gasoline prices (all formulations)', 'https://www.eia.gov/tools/faqs/faq.php?id=23&t=10'],
      ['EIA — Natural Gas Weekly Update', 'https://www.eia.gov/naturalgas/weekly/'],
    ],
  },
  {
    id: 'elections', name: 'Elections & Politics', short: 'Elections', cls: 'elections', color: '#5aa9ff',
    keywords: ['election', 'presidential', 'president ', 'senate', 'house of', 'governor', 'primary', 'electoral',
      'midterm', 'nomination', 'ballot', 'democrat', 'republican', 'congress', 'mayor', 'referendum', 'appoint'],
    blurb: 'US and international electoral outcomes, control of chambers, and nominations.',
    sources: [
      ['FEC — Election & voting data', 'https://www.fec.gov/data/elections/'],
      ['FEC — Official site', 'https://www.fec.gov/'],
      ['USA.gov — Elections', 'https://www.usa.gov/election-office'],
    ],
  },
  {
    id: 'culture', name: 'Culture & Entertainment', short: 'Culture', cls: 'culture', color: '#c084fc',
    keywords: ['oscar', 'grammy', 'emmy', 'golden globe', 'movie', 'film', 'box office', 'album', 'music', 'tv',
      'streaming', 'celebrity', 'awards', 'culture', 'billboard', 'spotify', 'netflix', 'television'],
    blurb: 'Entertainment, awards, music, film, TV and pop-culture events.',
    sources: [
      ['Academy Awards (official)', 'https://www.oscars.org/'],
      ['Recording Academy (official)', 'https://www.grammy.com/'],
      ['Emmys (official)', 'https://www.emmys.com/'],
    ],
  },
  {
    id: 'crypto', name: 'Crypto', short: 'Crypto', cls: 'crypto', color: '#00dd94',
    keywords: ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'solana', ' dogecoin', 'doge', 'xrp', 'coinbase',
      'binance', ' stablecoin', 'ripple', 'cardano'],
    blurb: 'Digital-asset price milestones and crypto-industry events.',
    sources: [
      ['CoinGecko — Bitcoin', 'https://www.coingecko.com/en/coins/bitcoin'],
      ['CoinGecko — Ethereum', 'https://www.coingecko.com/en/coins/ethereum'],
      ['Coinbase — BTC/USD price', 'https://www.coinbase.com/price/bitcoin'],
    ],
  },
  {
    id: 'golf', name: 'Golf', short: 'Golf', cls: 'golf', color: '#a3e635',
    keywords: ['golf', 'pga', 'masters', 'ryder cup', 'liv golf', 'open championship', 'pgatour', 'us open golf',
      'the open', 'fedex cup', 'wk', 'tournament winner golf'],
    blurb: 'PGA Tour, majors (Masters, US Open, The Open, PGA Championship), Ryder Cup and LIV.',
    sources: [
      ['PGA Tour (official)', 'https://www.pgatour.com/'],
      ['Masters Tournament (official)', 'https://www.masters.com/'],
      ['USGA (official)', 'https://www.usga.org/'],
    ],
  },
];

const TOPIC_BY_ID = Object.fromEntries(TOPICS.map(t => [t.id, t]));

/* Score-match a free-text blob against each topic's keyword list.
   Returns array of {id, score} sorted desc; empty when nothing matches. */
function classifyText(text) {
  const hay = ' ' + String(text || '').toLowerCase() + ' ';
  const out = [];
  for (const t of TOPICS) {
    let score = 0;
    for (const kw of t.keywords) {
      const k = kw.trim();
      if (k && hay.includes(k)) score += k.length >= 6 ? 2 : 1;
    }
    if (score > 0) out.push({ id: t.id, score });
  }
  return out.sort((a, b) => b.score - a.score);
}

/* Classify a Kalshi market/event object into a topic id (or null). */
function classifyMarket(m) {
  const blob = [m.title, m.subtitle, m.category, m.event_ticker, m.series_ticker, m.yes_sub_title, m.rules_primary]
    .filter(Boolean).join(' ');
  const matches = classifyText(blob);
  return matches.length ? matches[0].id : null;
}

/* News-search + topic-source links for the "possible drivers" row.
   These are search/reference links, never fabricated facts. */
function driverLinks(topicId, title) {
  const q = encodeURIComponent(title || '');
  const links = [{ label: 'Google News search', url: 'https://www.google.com/search?tbm=nws&q=' + q }];
  const t = TOPIC_BY_ID[topicId];
  if (t) for (const [label, url] of t.sources) links.push({ label, url });
  return links;
}
