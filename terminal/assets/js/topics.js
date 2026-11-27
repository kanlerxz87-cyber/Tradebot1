/* topics.js — the five tracked verticals, their official metadata, and a classifier
   that prefers the exchange's own fields over guesses.

   Why this file changed (2026-11-27, session 2573166c)
   ---------------------------------------------------
   The first version of this classifier scored free text only. Two consequences,
   both visible on the live site:

     1. A golf event titled "Presidents Cup: …" matched the elections keyword
        "president" and was filed under Elections. Golf events whose titles do not
        contain the literal word "golf" (most of them) landed in the wrong topic.
     2. Gas-price markets could only be found by the words "gas"/"fuel", so any
        contract that expressed the same thing numerically (a strike like
        ">$3.50") was invisible.

   Kalshi returns a `category` on every market/event and `tags` on the series, so
   the classifier now uses them first and only falls back to words. Every result
   carries the evidence it used, and the dashboard prints that evidence, so a
   reader can check the classification rather than trust it.

   Official sources for the field names and the values used here
   ------------------------------------------------------------
   - GET /markets returns `category` per market and `tags` per series
     https://docs.kalshi.com/api-reference/market/get-markets
   - GET /events returns `category`, `series_ticker`, `markets`
     https://docs.kalshi.com/api-reference/events/get-events
   - Category values used below (Elections, Crypto, Entertainment, Economics,
     Sports, Golf) are the values actually present in this repository's own
     captured API payloads: docs/desk/data/series.json (717 series: Elections 150,
     Entertainment 150, Crypto 150, Economics 139, Sports 128; tag Golf 128) and
     data/snapshot.json. Nothing here is invented.
   */
'use strict';

const TOPICS = [
  {
    id: 'gas', name: 'Gas Prices', short: 'Gas', cls: 'gas', color: '#ffc44d',
    /* Official: series KXAAAGAS* is category Economics with the oil/energy tags
       (docs/desk/data/series.json; KXAAAGASM is the worked example in Kalshi's
       own terms page). The tag list is deliberately narrow so that every other
       Economics market (CPI, GDP, jobs) is NOT called a gas market. */
    categories: [],
    tags: ['oil and energy', 'oil & gas', 'gas', 'gasoline'],
    seriesPrefixes: ['kxaaagas'],
    keywords: ['gas price', 'gasoline', 'aaa gas', 'pump price', 'fuel price', 'diesel price', 'natural gas'],
    blurb: 'Retail gasoline and diesel contracts, settled against a published energy-agency figure. ' +
      'Identified by the official series ticker and the oil/energy tags, not by the word "gas".',
    sources: [
      ['EIA — Gasoline & Diesel Fuel Update', 'https://www.eia.gov/petroleum/gasdiesel/'],
      ['AAA — Gas Prices (settlement source for KXAAAGAS)', 'https://gasprices.aaa.com/'],
      ['EIA — Natural Gas Weekly Update', 'https://www.eia.gov/naturalgas/weekly/'],
    ],
  },
  {
    id: 'elections', name: 'Elections & Politics', short: 'Elections', cls: 'elections', color: '#5aa9ff',
    categories: ['elections'],
    tags: ['us elections', 'senate', 'house', 'governor', 'presidential'],
    seriesPrefixes: [],
    keywords: ['election', 'presidential nominee', 'senate', 'governor', 'electoral', 'midterm', 'ballot'],
    blurb: 'US and international electoral outcomes, control of chambers, and nominations. ' +
      'Identified by the official Elections category.',
    sources: [
      ['FEC — Election & voting data', 'https://www.fec.gov/data/elections/'],
      ['FEC — Official site', 'https://www.fec.gov/'],
      ['USA.gov — Elections', 'https://www.usa.gov/election-office'],
    ],
  },
  {
    id: 'culture', name: 'Culture & Entertainment', short: 'Culture', cls: 'culture', color: '#c084fc',
    /* Kalshi has no "Culture" category; the official Entertainment category is the
       closest verified equivalent and is what this project has always used. */
    categories: ['entertainment'],
    tags: ['music', 'awards', 'television', 'movies', 'celebrities'],
    seriesPrefixes: [],
    keywords: ['oscar', 'grammy', 'emmy', 'golden globe', 'box office', 'album', 'billboard', 'rotten tomatoes', 'game of the year'],
    blurb: 'Entertainment, awards, music, film, TV and pop culture — the official Entertainment category ' +
      '(Kalshi has no separate Culture category).',
    sources: [
      ['Academy Awards (official)', 'https://www.oscars.org/'],
      ['Recording Academy (official)', 'https://www.grammy.com/'],
      ['Emmys (official)', 'https://www.emmys.com/'],
    ],
  },
  {
    id: 'crypto', name: 'Crypto', short: 'Crypto', cls: 'crypto', color: '#00dd94',
    categories: ['crypto'],
    tags: ['crypto', 'bitcoin', 'btc', 'ethereum', 'eth'],
    seriesPrefixes: [],
    keywords: ['bitcoin', 'ethereum', 'solana', 'dogecoin', 'xrp', 'stablecoin', 'crypto'],
    blurb: 'Digital-asset price milestones and crypto-industry events. Identified by the official Crypto category.',
    sources: [
      ['CoinGecko — Bitcoin', 'https://www.coingecko.com/en/coins/bitcoin'],
      ['Coinbase — BTC/USD price', 'https://www.coinbase.com/price/bitcoin'],
      ['Kalshi — crypto markets', 'https://kalshi.com/markets/crypto'],
    ],
  },
  {
    id: 'golf', name: 'Golf', short: 'Golf', cls: 'golf', color: '#a3e635',
    /* Golf is a TAG under the Sports category, not a category of its own. Using the
       tag first is what stops "Presidents Cup" being filed as an election. */
    categories: [],
    tags: ['golf', 'pga', 'lpga', 'dp world tour', 'liv golf'],
    seriesPrefixes: ['kxpgatour', 'kxdptour', 'kxlpga'],
    keywords: ['pga', 'lpga', 'masters', 'ryder cup', 'presidents cup', 'open championship', 'fedex cup', 'birdie', 'hole in one'],
    blurb: 'PGA Tour, LPGA, DP World Tour, majors and team events — the official Golf tag under Sports.',
    sources: [
      ['PGA Tour (official)', 'https://www.pgatour.com/'],
      ['Masters Tournament (official)', 'https://www.masters.com/'],
      ['USGA (official)', 'https://www.usga.org/'],
    ],
  },
];

const TOPIC_BY_ID = Object.fromEntries(TOPICS.map(t => [t.id, t]));

const norm = (s) => String(s == null ? '' : s).trim().toLowerCase();

/* Score-match a free-text blob against each topic's keyword list.
   Kept for the fallback path and for callers that only have a title. */
function classifyText(text) {
  const hay = ' ' + norm(text) + ' ';
  const out = [];
  for (const t of TOPICS) {
    let score = 0;
    for (const kw of t.keywords) {
      const k = norm(kw);
      if (k && hay.includes(k)) score += k.length >= 6 ? 2 : 1;
    }
    if (score > 0) out.push({ id: t.id, score });
  }
  return out.sort((a, b) => b.score - a.score);
}

/* Classify a Kalshi market (optionally with its event and series metadata).
   Returns { topic, evidence, confidence } — `topic` is null when the market is
   outside the five verticals, and null is a real answer, not a failure.

   Priority:
     1. series ticker prefix   — the exchange's own identifier for the product
     2. tag                    — an official series field
     3. category               — an official market/event field
     4. title keywords         — a guess, always labelled as one
   Within 2 and 3, exact membership in the table above; no substring scoring, so
   "Oil and energy" cannot drag an unrelated Economics market into gas. */
function classifyMarket(m, extra = {}) {
  if (m && m._topic) {
    return { topic: m._topic, evidence: (m._topicEvidence || 'supplied by caller'), confidence: 'supplied' };
  }
  const src = m || {};
  const series = norm(src.series_ticker || extra.series_ticker);
  const tags = [...(src.tags || extra.tags || [])].map(norm);
  const category = norm(src.category || extra.category);

  for (const t of TOPICS) {
    for (const prefix of t.seriesPrefixes) {
      if (series.startsWith(prefix)) {
        return { topic: t.id, evidence: `series ${series.toUpperCase()}`, confidence: 'series' };
      }
    }
  }
  for (const t of TOPICS) {
    const hit = t.tags.find((tag) => tags.includes(norm(tag)));
    if (hit) return { topic: t.id, evidence: `tag "${hit}"`, confidence: 'tag' };
  }
  for (const t of TOPICS) {
    const hit = t.categories.find((c) => category === norm(c));
    if (hit) return { topic: t.id, evidence: `category "${src.category || extra.category}"`, confidence: 'category' };
  }
  const blob = [src.title, src.subtitle, src.yes_sub_title, extra.title, extra.subtitle, series]
    .filter(Boolean).join(' ');
  const matches = classifyText(blob);
  if (matches.length && matches[0].score >= 2) {
    return { topic: matches[0].id, evidence: 'title keywords', confidence: 'keyword' };
  }
  return { topic: null, evidence: category ? `out of scope (category "${src.category || extra.category}")` : 'out of scope', confidence: 'none' };
}

/* News-search + topic-source links for the "possible drivers" row.
   These are search/reference links, never fabricated facts. */
function driverLinks(topicId, title) {
  const q = encodeURIComponent(String(title || '').slice(0, 90));
  const links = [{ label: 'Google News search', url: 'https://www.google.com/search?tbm=nws&q=' + q }];
  const t = TOPIC_BY_ID[topicId];
  if (t) for (const [label, url] of t.sources) links.push({ label, url });
  return links;
}
