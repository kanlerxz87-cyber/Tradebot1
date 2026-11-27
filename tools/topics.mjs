// Topic routing for the five focus topics.
//
// The rule each topic uses was decided by reading the official Kalshi taxonomy
// and live demo series responses, not by keyword guesswork:
//
//   crypto    GET /series?category=Crypto   -> series whose category is Crypto
//   elections GET /series?category=Elections -> series whose category is Elections
//   culture   GET /series?category=Culture returns two series in the demo probe
//             (KXXBANNEDGROK and KXXBANNEDMURRAYHILLGUY1); active entertainment/
//             awards series in both demo and production also live under category
//             "Entertainment" and "Social" (for example KXGAMEAWARDS).
//   golf      GET /series?tags=Golf         -> NO Golf *category* exists; golf
//                                              series are category "Sports" with
//                                              the tag "Golf"
//   gas       GET /series?tags=Gas returns DIESEL / DIESELM, while US retail
//             gasoline contracts (KXAAAGASM, KXAAAGASW) carry category
//             "Economics" / "Commodities" and tags "Oil and energy" / "Oil & Gas".
//             Those series are filtered strictly by gasoline/diesel scope/tag so
//             crude-oil or natural-gas contracts do not leak into gas prices.
//
// Nothing here invents a topic. A market that matches no rule is left out and
// counted, so the coverage table can show it.

export const TOPICS = [
  {
    id: 'gas',
    label: 'Gas prices',
    blurb: 'US fuel prices, from the Kalshi series that settle on AAA retail gasoline and EIA diesel data.',
    discovery: [
      { kind: 'series-tags', value: 'Gas', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?tags=Gas' },
      { kind: 'series-tags', value: 'Oil and energy', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?tags=Oil%20and%20energy' },
      { kind: 'series-tags', value: 'Oil & Gas', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?tags=Oil%20%26%20Gas' },
      { kind: 'series-category', value: 'Economics', tags: 'Gas', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?category=Economics&tags=Gas' },
    ],
    dataSources: [
      { name: 'AAA — daily US national average retail gas prices', url: 'https://gasprices.aaa.com/' },
      { name: 'Energy Information Administration — weekly retail diesel', url: 'https://www.eia.gov/dnav/pet/PET_PRI_SPT_S1_D.htm' },
    ],
    flags: ['F-03'],
  },
  {
    id: 'elections',
    label: 'Elections',
    blurb: 'Candidate, party and ballot contests, worldwide and domestic.',
    discovery: [
      { kind: 'series-category', value: 'Elections', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?category=Elections' },
    ],
    dataSources: [],
    flags: [],
  },
  {
    id: 'culture',
    label: 'Culture',
    blurb: 'Bans, awards, entertainment and social events across Culture, Entertainment and Social series.',
    discovery: [
      { kind: 'series-category', value: 'Culture', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?category=Culture' },
      { kind: 'series-category', value: 'Entertainment', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?category=Entertainment' },
      { kind: 'series-category', value: 'Social', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?category=Social' },
    ],
    dataSources: [],
    flags: [],
  },
  {
    id: 'crypto',
    label: 'Crypto',
    blurb: 'Bitcoin, Ethereum and other digital-asset price and milestone contracts.',
    discovery: [
      { kind: 'series-category', value: 'Crypto', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?category=Crypto' },
    ],
    dataSources: [
      { name: 'CF Benchmarks BRTI (Bitcoin Real Time Index)', url: 'https://www.cfbenchmarks.com/' },
    ],
    flags: [],
  },
  {
    id: 'golf',
    label: 'Golf',
    blurb: 'PGA, LIV and major-championship outcomes.',
    discovery: [
      { kind: 'series-tags', value: 'Golf', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?tags=Golf' },
    ],
    dataSources: [
      { name: 'ESPN golf', url: 'https://www.espn.com/golf/' },
      { name: 'PGA Tour', url: 'https://www.pgatour.com/' },
    ],
    flags: ['F-04'],
  },
];

export const TOPIC_BY_ID = Object.fromEntries(TOPICS.map((t) => [t.id, t]));

/**
 * Decide the topic of a series descriptor as returned by GET /series.
 * Only the series' own fields are used: its `category` and its `tags`.
 * Keyword matching is deliberately NOT used — a Georgia election market once
 * matched "gas" that way on an earlier build of a sibling project.
 */
export function topicForSeries(series) {
  if (!series) return null;
  const categories = new Set([series.category, ...(series.categories ?? [])].filter(Boolean).map((c) => String(c).toLowerCase()));
  const tags = new Set((series.tags ?? []).filter(Boolean).map((t) => String(t).toLowerCase()));
  const scope = String(series.product_metadata?.scope ?? '').toLowerCase();
  const title = String(series.title ?? '');
  const ticker = String(series.ticker ?? '').toUpperCase();
  if (categories.has('crypto')) return 'crypto';
  if (categories.has('elections')) return 'elections';
  if (categories.has('culture') || categories.has('entertainment') || categories.has('social')) return 'culture';
  if (tags.has('golf')) return 'golf';
  if (tags.has('gas') || tags.has('gasoline') || tags.has('diesel')) return 'gas';
  if (
    (tags.has('oil and energy') || tags.has('oil & gas') || categories.has('economics') || categories.has('commodities')) &&
    (/\bgasoline\b|\bdiesel\b/i.test(scope) || /\b(gas\s*pric|gasoline|diesel|aaa\s+gas)\b/i.test(title) || /^KXAAAGAS|^DIESEL/i.test(ticker))
  ) {
    return 'gas';
  }
  return null;
}

export function seriesSourceUrl(ticker) {
  return `https://external-api.demo.kalshi.co/trade-api/v2/series/${encodeURIComponent(ticker)}`;
}
