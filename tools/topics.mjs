// Topic routing for the five focus topics.
//
// The rule each topic uses was decided by reading the live demo API, not by
// guesswork, and every mapping is recorded with the request that proves it:
//
//   crypto    GET /series?category=Crypto   -> series whose category is Crypto
//   elections GET /series?category=Elections -> series whose category is Elections
//   culture   GET /series?category=Culture   -> exactly 1 series (KXXBANNEDGROK)
//   golf      GET /series?tags=Golf         -> NO Golf *category* exists; golf
//                                              series are category "Sports" with
//                                              the tag "Golf"
//   gas       GET /series?category=Economics&tags=Gas and tags=Gas both return
//             only DIESEL / DIESELM in the demo catalogue on 2026-11-22. There
//             is no "Gas" or "Gasoline" category. The fee schedule names the US
//             gas price series KXAAAGASM, which was NOT present in the demo
//             series catalogue at capture time.
//
// The consequences are visible on the site and flagged on flagged.html:
//   F-03 gas: only diesel series are discoverable through the series filters.
//   F-04 golf: tag-based discovery, because the category is Sports.
//
// Nothing here invents a topic. A market that matches no rule is left out and
// counted, so the coverage table can show it.

export const TOPICS = [
  {
    id: 'gas',
    label: 'Gas prices',
    blurb: 'US fuel prices, from the Kalshi series that settle on Energy Information Administration data.',
    discovery: [
      { kind: 'series-tags', value: 'Gas', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?tags=Gas' },
      { kind: 'series-category', value: 'Economics', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?category=Economics&tags=Gas' },
    ],
    dataSources: [
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
    blurb: 'Bans, awards and entertainment events. Kalshi files these under the Culture category.',
    discovery: [
      { kind: 'series-category', value: 'Culture', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?category=Culture' },
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
  if (categories.has('crypto')) return 'crypto';
  if (categories.has('elections')) return 'elections';
  if (categories.has('culture')) return 'culture';
  if (tags.has('golf')) return 'golf';
  if (tags.has('gas') || tags.has('gasoline') || tags.has('diesel')) return 'gas';
  return null;
}

export function seriesSourceUrl(ticker) {
  return `https://external-api.demo.kalshi.co/trade-api/v2/series/${encodeURIComponent(ticker)}`;
}
