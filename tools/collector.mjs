#!/usr/bin/env node
// The live collector. Runs in GitHub Actions (which has normal internet egress)
// on a schedule, and can be run by hand:
//
//   node tools/collector.mjs            # one full cycle, writes data/live/*
//   node tools/collector.mjs --dry-run  # fetch and report, write nothing
//
// What one cycle does:
//   1. reads the exchange status,
//   2. discovers the five focus topics from the official series catalogue,
//   3. reads open markets per topic, and closes/resolutions for markets it was
//      already tracking (so an event is followed until it resolves),
//   4. stores one price observation per tracked market, with the timestamp the
//      response was received,
//   5. turns consecutive observations into >= $0.10 swing alerts,
//   6. scores those alerts for the model-filtered feed,
//   7. runs every simulated strategy against the observation, and settles any
//      simulated position whose market has finalized,
//   8. writes data/live/{feed,state,portfolio}.json.
//
// It never writes a price it did not receive, never interpolates between
// observations, and never claims a cause for a move.

import { writeFile, mkdir, readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { createClient, normaliseOrderbook, DEFAULT_ROOT, SOURCES } from './kalshi.mjs';
import { TOPICS, topicForSeries, seriesSourceUrl } from './topics.mjs';
import { detectSwing, yesMid, researchScore, resolutionOf, rankForFilteredFeed, round2, round4, SWING_THRESHOLD } from './alerts.mjs';
import { STRATEGIES, openPosition, settlePosition, markToMarket, portfolioSummary, STRATEGY_SOURCE } from './strategies.mjs';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname);
const DATA_DIR = path.join(ROOT, 'data', 'live');
const STATE_FILE = path.join(DATA_DIR, 'state.json');
const FEED_FILE = path.join(DATA_DIR, 'feed.json');
const PORTFOLIO_FILE = path.join(DATA_DIR, 'portfolio.json');

const args = new Set(process.argv.slice(2));
const DRY = args.has('--dry-run');

// Bounds. These are project choices to stay inside the documented rate limits
// (https://docs.kalshi.com/getting_started/rate_limits) and to keep each cycle
// short enough for a scheduled job. They are reported on the site so the
// coverage of a cycle is honest: this is a sample of the open markets in each
// topic, not a census of the exchange.
const MAX_SERIES_PER_TOPIC = 12;
const MAX_MARKETS_PER_TOPIC = 60;
const MAX_TRACKED_RESOLUTIONS = 40;
const RETENTION_DAYS = 14;
const MAX_HISTORY_POINTS = 720;
const MAX_FEED_ROWS = 400;

const now = new Date();
const nowIso = now.toISOString();
const runId = nowIso.replace(/[:.]/g, '-');

function log(...args2) { console.log(`[collector ${nowIso}]`, ...args2); }

async function main() {
  const client = createClient({ root: process.env.KALSHI_REST_ROOT || DEFAULT_ROOT, timeoutMs: 25000 });
  const state = await loadState();

  log('root', client.root);

  // 1. exchange status
  let exchange = null;
  try {
    exchange = await client.exchangeStatus();
    log('exchange active:', exchange.exchange_active, 'trading:', exchange.trading_active);
  } catch (err) {
    log('exchange status failed:', err.message);
  }

  // 2. topic discovery
  const discovery = {};
  const seriesByTopic = {};
  for (const topic of TOPICS) {
    seriesByTopic[topic.id] = [];
    discovery[topic.id] = { topic: topic.id, rules: [], seriesFound: 0, seriesRead: 0, errors: [] };
    for (const rule of topic.discovery) {
      const url = rule.kind === 'series-tags'
        ? new URL(`${client.root}/series?tags=${encodeURIComponent(rule.value)}`).toString()
        : new URL(`${client.root}/series?category=${encodeURIComponent(rule.value)}`).toString();
      let found = [];
      try {
        const res = rule.kind === 'series-tags'
          ? await client.listSeries({ tags: rule.value })
          : await client.listSeries({ category: rule.value });
        found = res.series ?? [];
        log(`discovery ${topic.id} ${rule.kind}=${rule.value}: ${found.length} series`);
      } catch (err) {
        discovery[topic.id].errors.push({ rule, message: err.message });
        log(`discovery ${topic.id} ${rule.kind}=${rule.value} failed: ${err.message}`);
        continue;
      }
      discovery[topic.id].rules.push({ ...rule, requestUrl: url, returned: found.length });
      for (const s of found) {
        const mapped = topicForSeries(s);
        if (mapped !== topic.id) continue;
        if (seriesByTopic[topic.id].some((x) => x.ticker === s.ticker)) continue;
        seriesByTopic[topic.id].push({
          ticker: s.ticker,
          title: s.title ?? '',
          category: s.category ?? '',
          categories: s.categories ?? [],
          tags: s.tags ?? [],
          feeType: s.fee_type ?? '',
          feeMultiplier: s.fee_multiplier ?? null,
          frequency: s.frequency ?? '',
          settlementSources: (s.settlement_sources ?? []).filter((x) => x && x.url),
          sourceUrl: seriesSourceUrl(s.ticker),
        });
      }
      discovery[topic.id].seriesFound = seriesByTopic[topic.id].length;
    }
  }

  // 3. markets + resolutions
  const markets = [];
  const coverage = {};
  for (const topic of TOPICS) {
    const series = seriesByTopic[topic.id].slice(0, MAX_SERIES_PER_TOPIC);
    coverage[topic.id] = {
      topic: topic.id,
      seriesDiscovered: seriesByTopic[topic.id].length,
      seriesRead: 0,
      seriesWithOpenMarkets: 0,
      marketsOpen: 0,
      marketsObserved: 0,
      seriesCapped: seriesByTopic[topic.id].length > MAX_SERIES_PER_TOPIC,
      marketCapReached: false,
      errors: discovery[topic.id].errors,
    };
    for (const s of series) {
      if (markets.filter((m) => m.topic === topic.id).length >= MAX_MARKETS_PER_TOPIC) { coverage[topic.id].marketCapReached = true; break; }
      let open = [];
      try {
        const res = await client.listMarkets({ series_ticker: s.ticker, status: 'open', limit: 100 });
        open = res.markets ?? [];
        coverage[topic.id].seriesRead += 1;
      } catch (err) {
        coverage[topic.id].errors.push({ series: s.ticker, message: err.message });
        continue;
      }
      if (open.length) coverage[topic.id].seriesWithOpenMarkets += 1;
      for (const m of open) {
        if (markets.filter((x) => x.topic === topic.id).length >= MAX_MARKETS_PER_TOPIC) { coverage[topic.id].marketCapReached = true; break; }
        markets.push(toMarketRow(m, topic.id, s));
      }
      coverage[topic.id].marketsOpen += open.length;
    }
  }

  // Resolve anything still being tracked, including markets that dropped out of
  // the open list. This is what "follow events until they resolve" means here.
  const trackedTickers = new Set(Object.keys(state.tracked ?? {}));
  for (const m of markets) trackedTickers.add(m.ticker);
  const resolutions = {};
  const resolutionQueue = [...trackedTickers].slice(0, MAX_TRACKED_RESOLUTIONS + markets.length);
  for (const ticker of resolutionQueue) {
    const existing = resolutions[ticker];
    if (existing) continue;
    if (markets.some((m) => m.ticker === ticker)) continue; // already have fresh data
    try {
      const res = await client.getMarket(ticker);
      const m = res.market;
      if (!m) continue;
      resolutions[ticker] = {
        ticker,
        status: m.status,
        result: m.result ?? '',
        settlementTs: m.settlement_ts ?? null,
        settlementValue: m.settlement_value_dollars ?? m.settlement_value ?? null,
        closeTime: m.close_time ?? null,
        expirationValue: m.expiration_value ?? '',
        resolution: resolutionOf(m),
        checkedAt: nowIso,
        sourceUrl: new URL(`${client.root}/markets/${encodeURIComponent(ticker)}`).toString(),
      };
    } catch (err) {
      // A 404 here is information, not an error to hide.
      resolutions[ticker] = {
        ticker, status: 'unknown', result: '', resolution: resolutionOf({ status: 'unknown' }),
        error: err.message, checkedAt: nowIso,
        sourceUrl: new URL(`${client.root}/markets/${encodeURIComponent(ticker)}`).toString(),
      };
    }
  }
  log(`resolved/checked ${Object.keys(resolutions).length} tracked markets`);

  // 4. observations. One per market per cycle; an order book read for the
  // markets where we will actually quote a spread or depth.
  const tracked = { ...(state.tracked ?? {}) };
  const observations = [];
  for (const m of markets) {
    const prev = tracked[m.ticker];
    const obs = {
      ticker: m.ticker,
      marketTicker: m.ticker,
      eventTicker: m.eventTicker,
      title: m.title,
      topic: m.topic,
      yesBid: m.yesBid,
      yesAsk: m.yesAsk,
      noBid: m.noBid,
      noAsk: m.noAsk,
      yesMid: yesMid(m.yesBid, m.yesAsk),
      lastPrice: m.lastPrice,
      volume24h: m.volume24h,
      openInterest: m.openInterest,
      liquidityDollars: m.liquidityDollars,
      observedAt: m.fetchedAt,
      sourceUrl: m.sourceUrl,
      seriesFeeMultiplier: m.seriesFeeMultiplier ?? null,
    };

    // Order book only for markets that already have a prior observation, or
    // that moved - keeps the request count bounded while still giving depth
    // where a move actually happened.
    const provisionalDelta = prev && prev.yesMid != null && obs.yesMid != null ? round4(obs.yesMid - prev.yesMid) : null;
    const wantBook = prev ? true : markets.indexOf(m) < 12;
    if (wantBook) {
      try {
        const bookRaw = await client.getOrderbook(m.ticker);
        const book = normaliseOrderbook(bookRaw);
        obs.book = book;
        obs.orderbookUrl = new URL(`${client.root}/markets/${encodeURIComponent(m.ticker)}/orderbook`).toString();
      } catch (err) {
        obs.bookError = err.message;
      }
    }

    if (prev) {
      const swing = detectSwing(prev, obs);
      if (swing) {
        obs.delta = swing.delta;
        obs.absDelta = swing.absDelta;
        obs.direction = swing.direction;
        obs.prevObservedAt = prev.observedAt;
        obs.qualifies = swing.qualifies;
      }
    } else {
      obs.delta = null;
      obs.note = 'first observation of this market in this record; no previous price to compare';
    }
    observations.push(obs);
    coverage[m.topic].marketsObserved += 1;

    // 5. history for the chart, capped, timestamped with the observation time.
    const hist = tracked[m.ticker]?.history ?? [];
    if (obs.yesMid != null) {
      hist.push({ t: obs.observedAt, bid: obs.yesBid, ask: obs.yesAsk, mid: obs.yesMid });
    }
    tracked[m.ticker] = {
      marketTicker: m.ticker,
      eventTicker: m.eventTicker,
      topic: m.topic,
      title: m.title,
      seriesTicker: m.seriesTicker,
      yesMid: obs.yesMid,
      yesBid: obs.yesBid,
      yesAsk: obs.yesAsk,
      observedAt: obs.observedAt,
      history: trimHistory(hist),
      lastSeenAt: obs.observedAt,
      closeTime: m.closeTime,
      sourceUrl: m.sourceUrl,
    };
    if (provisionalDelta != null && obs.book) {
      obs.provisionalDelta = provisionalDelta;
    }
  }

  // 6. alerts
  const newAlerts = [];
  for (const obs of observations) {
    if (!obs.qualifies) continue;
    const crossDepth = obs.direction === 'up' ? obs.book?.yesAskDepthContracts : obs.book?.yesBidDepthContracts;
    const spread = obs.book?.spread ?? null;
    const ageSeconds = Math.max(0, (now - new Date(obs.observedAt)) / 1000);
    const scored = researchScore({
      absDelta: obs.absDelta,
      crossDepthContracts: crossDepth,
      spread,
      volume24h: obs.volume24h,
      ageSeconds,
    });
    newAlerts.push({
      id: `${obs.ticker}|${obs.observedAt}`,
      kind: 'swing',
      marketTicker: obs.ticker,
      eventTicker: obs.eventTicker,
      title: obs.title,
      topic: obs.topic,
      direction: obs.direction,
      from: round4(obs.yesMid - obs.delta),
      to: obs.yesMid,
      delta: obs.delta,
      absDelta: obs.absDelta,
      observedAt: obs.observedAt,
      previousObservedAt: obs.prevObservedAt,
      threshold: SWING_THRESHOLD,
      crossDepthContracts: crossDepth ?? null,
      spread,
      volume24h: obs.volume24h,
      score: scored.score,
      scoreParts: scored.parts,
      scoreMissing: scored.missing,
      eligibleForFilteredFeed: scored.eligible,
      marketUrl: obs.sourceUrl,
      orderbookUrl: obs.orderbookUrl ?? null,
      // No cause is claimed. The sources the exchange itself names for the
      // contract are the only links offered as "where to look".
      settlementSources: seriesByTopic[obs.topic]?.find((s) => s.ticker === obs.eventTicker?.split('-')[0])?.settlementSources ?? [],
      note: 'observed difference between two consecutive polls of the demo order book mid-price; no cause is inferred',
    });
  }
  log(`new alerts this cycle: ${newAlerts.length}`);

  // 7. simulated trading
  const portfolio = await loadJson(PORTFOLIO_FILE, defaultPortfolio());
  const openByTicker = new Map(portfolio.positions.filter((p) => p.status === 'open').map((p) => [p.ticker, p]));
  let opened = 0;
  for (const obs of observations) {
    if (openByTicker.has(obs.ticker)) continue;
    const row = {
      ...obs,
      lastDelta: obs.delta,
      yesAsk: obs.book ? bestAskFromBook(obs.book) : obs.yesAsk,
      noAsk: obs.book ? bestNoAskFromBook(obs.book) : obs.noAsk,
      yesBid: obs.book ? obs.book.bestYesBid : obs.yesBid,
      noBid: obs.book ? obs.book.bestNoBid : obs.noBid,
      spread: obs.book?.spread ?? null,
      yesAskDepthContracts: obs.book?.yesAskDepthContracts ?? null,
      yesMid: obs.yesMid,
    };
    for (const strategy of STRATEGIES) {
      const decision = strategy.evaluate(row);
      if (!decision) continue;
      const contracts = 1;
      const position = openPosition({
        ticker: obs.ticker, topic: obs.topic,
        strategyId: strategy.id, side: decision.side, price: decision.price,
        contracts, at: obs.observedAt, title: obs.title,
        eventTicker: obs.eventTicker, seriesTicker: obs.seriesTicker ?? null,
        feeMultiplier: obs.seriesFeeMultiplier ?? null,
        reason: decision.reason,
      });
      portfolio.positions.push(position);
      openByTicker.set(obs.ticker, position);
      opened += 1;
      break; // one simulated position per market at a time
    }
  }
  log(`simulated positions opened: ${opened}`);

  // settle + mark
  let settled = 0;
  for (const p of portfolio.positions) {
    if (p.status !== 'open') continue;
    const r = resolutions[p.ticker];
    if (r && ['determined', 'finalized'].includes(r.status) === false && r.status !== 'unknown') { /* still open */ }
    if (r && (r.result === 'yes' || r.result === 'no') && r.status === 'finalized') {
      const done = settlePosition(p, { status: 'finalized', result: r.result }, nowIso);
      if (done) { Object.assign(p, done); settled += 1; continue; }
    }
    const obs = observations.find((o) => o.ticker === p.ticker);
    if (obs && obs.book) {
      const m = markToMarket(p, { yesBid: obs.book.bestYesBid, noBid: obs.book.bestNoBid, seriesFeeMultiplier: obs.seriesFeeMultiplier ?? p.feeMultiplier });
      if (m) Object.assign(p, { markedAt: nowIso, ...m });
    }
  }
  log(`simulated positions settled: ${settled}`);

  if (portfolio.positions.length > 0 && portfolio.note) {
    delete portfolio.note;
  }
  portfolio.summary = portfolioSummary({ positions: portfolio.positions, startingCash: portfolio.startingCash });
  portfolio.updatedAt = nowIso;
  portfolio.runId = runId;

  // 8. write
  const feed = await loadJson(FEED_FILE, { alerts: [], runs: [] });
  const mergedAll = dedupeById([...(feed.alerts ?? []), ...newAlerts]).sort((a, b) => String(b.observedAt).localeCompare(String(a.observedAt)));
  // The seed feed ships one labelled "worked example" so the page layout had a row
  // to render before the first real observation. Once at least one genuine
  // two-observation swing exists, the example is dropped: a live alert chat should
  // not carry a row that is not a live alert.
  const realAlerts = mergedAll.filter((a) => !a.isDemoExample);
  const merged = realAlerts.length ? realAlerts : mergedAll;
  const filtered = rankForFilteredFeed(merged.filter((a) => a.eligibleForFilteredFeed === true));

  const nextState = {
    version: 1,
    updatedAt: nowIso,
    runId,
    root: client.root,
    exchange: exchange ? {
      exchangeActive: exchange.exchange_active ?? null,
      tradingActive: exchange.trading_active ?? null,
      intraExchangeTransfersActive: exchange.intra_exchange_transfers_active ?? null,
      indexStatuses: exchange.exchange_index_statuses ?? [],
      source: SOURCES.exchangeStatus,
    } : { error: 'exchange status unavailable this cycle', source: SOURCES.exchangeStatus },
    discovery,
    coverage,
    tracked,
    resolutions: mergeResolutions(state.resolutions, resolutions),
    limits: {
      maxSeriesPerTopic: MAX_SERIES_PER_TOPIC,
      maxMarketsPerTopic: MAX_MARKETS_PER_TOPIC,
      maxTrackedResolutions: MAX_TRACKED_RESOLUTIONS,
      retentionDays: RETENTION_DAYS,
      maxHistoryPoints: MAX_HISTORY_POINTS,
      maxFeedRows: MAX_FEED_ROWS,
    },
    marketCount: markets.length,
    observationCount: observations.length,
  };

  const nextFeed = {
    version: 1,
    updatedAt: nowIso,
    runId,
    threshold: SWING_THRESHOLD,
    rule: 'A swing alert is recorded when the observed mid-price of a tracked market differs from the previous observation of the same market by >= $0.10 in either direction.',
    ruleSource: SOURCES.orderbookSemantics,
    scoreDisclosure: 'The filtered feed is ranked by a 0-100 project heuristic (move size, crossable depth, spread, 24h volume, freshness). It is not a forecast, not return on investment, and not Kalshi data.',
    alerts: merged.slice(0, MAX_FEED_ROWS),
    filteredIds: filtered.slice(0, MAX_FEED_ROWS).map((a) => a.id),
    runs: [...(feed.runs ?? []), {
      runId, at: nowIso, exchangeActive: exchange?.exchange_active ?? null,
      markets: markets.length, observations: observations.length,
      newAlerts: newAlerts.length, newPositions: opened, settledPositions: settled,
      errors: Object.values(discovery).flatMap((d) => d.errors).length + Object.values(coverage).flatMap((c) => c.errors).length,
      // Pacing and 429 handling, so a partly-rate-limited cycle is visible in the record
      // instead of surfacing only as an unexplained shortfall of markets per topic.
      requests: typeof client.stats === 'function' ? client.stats() : null,
    }].slice(-200),
    observations: observations.map(stripForFeed),
  };

  if (DRY) {
    log('dry run: nothing written');
    log('markets', markets.length, 'observations', observations.length, 'alerts', newAlerts.length);
    if (!markets.length) process.exitCode = 2;
    return;
  }

  // A cycle that observed nothing is a failed cycle, not a fresh start. Keep
  // the previous files so the published site never goes blank, and exit non-zero
  // so the workflow shows red instead of silently publishing an empty feed.
  const existingState = await loadJson(STATE_FILE, null);
  if (!markets.length && existingState?.tracked && Object.keys(existingState.tracked).length) {
    log('no markets observed this cycle; keeping the previous committed data unchanged');
    process.exitCode = 3;
    return;
  }

  await mkdir(DATA_DIR, { recursive: true });
  await writeJson(STATE_FILE, nextState);
  await writeJson(FEED_FILE, nextFeed);
  await writeJson(PORTFOLIO_FILE, portfolio);
  log('wrote', path.relative(ROOT, STATE_FILE), path.relative(ROOT, FEED_FILE), path.relative(ROOT, PORTFOLIO_FILE));
  log(`tracked markets: ${Object.keys(tracked).length}; portfolio equity: ${portfolio.summary.equity}`);
  log('strategy source:', STRATEGY_SOURCE);
}

function bestAskFromBook(book) {
  const lvl = book.yesAsks?.[0];
  return lvl ? lvl[0] : null;
}
function bestNoAskFromBook(book) {
  const lvl = book.noAsks?.[0];
  return lvl ? lvl[0] : null;
}

function stripForFeed(obs) {
  return {
    ticker: obs.ticker, topic: obs.topic, observedAt: obs.observedAt,
    yesBid: obs.yesBid, yesAsk: obs.yesAsk, yesMid: obs.yesMid,
    delta: obs.delta ?? null, absDelta: obs.absDelta ?? null,
    qualifies: obs.qualifies ?? false, sourceUrl: obs.sourceUrl,
    note: obs.note ?? null,
  };
}

function toMarketRow(m, topic, series) {
  return {
    ticker: m.ticker,
    eventTicker: m.event_ticker ?? '',
    seriesTicker: series.ticker,
    // Published by GET /series as `fee_multiplier` ("a floating point multiplier applied to
    // the fee calculations"): https://docs.kalshi.com/api-reference/market/get-series
    seriesFeeMultiplier: series.feeMultiplier ?? null,
    topic,
    title: m.title ?? '',
    yesBid: num(m.yes_bid_dollars),
    yesAsk: num(m.yes_ask_dollars),
    noBid: num(m.no_bid_dollars),
    noAsk: num(m.no_ask_dollars),
    lastPrice: num(m.last_price_dollars),
    previousPrice: num(m.previous_price_dollars),
    yesBidSize: num(m.yes_bid_size_fp),
    yesAskSize: num(m.yes_ask_size_fp),
    volume24h: num(m.volume_24h_fp),
    volume: num(m.volume_fp),
    openInterest: num(m.open_interest_fp),
    liquidityDollars: num(m.liquidity_dollars),
    status: m.status ?? '',
    result: m.result ?? '',
    closeTime: m.close_time ?? '',
    expectedExpiration: m.expected_expiration_time ?? '',
    rulesPrimary: m.rules_primary ?? '',
    rulesSecondary: m.rules_secondary ?? '',
    marketType: m.market_type ?? '',
    fetchedAt: nowIso,
    sourceUrl: new URL(`https://external-api.demo.kalshi.co/trade-api/v2/markets/${encodeURIComponent(m.ticker)}`).toString(),
  };
}

// Kalshi moved price fields to fixed-point strings ("0.5600", counts as
// "10.00"); a missing field is null, never 0.
function num(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function trimHistory(history) {
  const cutoff = Date.now() - RETENTION_DAYS * 86400000;
  const fresh = history.filter((h) => new Date(h.t).getTime() >= cutoff);
  return fresh.slice(-MAX_HISTORY_POINTS);
}

function dedupeById(rows) {
  const seen = new Set();
  const out = [];
  for (const r of rows) {
    if (!r?.id || seen.has(r.id)) continue;
    seen.add(r.id);
    out.push(r);
  }
  return out;
}

function mergeResolutions(old = {}, fresh = {}) {
  const merged = { ...old };
  for (const [k, v] of Object.entries(fresh)) {
    const previous = merged[k];
    // Never downgrade a finalised result back to an unknown one.
    if (previous && (previous.result === 'yes' || previous.result === 'no') && previous.status === 'finalized' && v.status === 'unknown') continue;
    merged[k] = v;
  }
  const cutoff = Date.now() - RETENTION_DAYS * 86400000;
  return Object.fromEntries(Object.entries(merged).filter(([, v]) => new Date(v.checkedAt).getTime() >= cutoff));
}

function defaultPortfolio() {
  return {
    version: 1,
    startingCash: 1000,
    cashNote: 'A simulated starting balance chosen for this project. It is NOT the cash in the Kalshi demo account; real demo-account figures are only shown when the authenticated snapshot job succeeds.',
    positions: [],
    summary: portfolioSummary({ positions: [], startingCash: 1000 }),
    updatedAt: null,
  };
}

async function loadJson(file, fallback) {
  try {
    if (!existsSync(file)) return fallback;
    return JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return fallback;
  }
}

async function loadState() {
  const s = await loadJson(STATE_FILE, {});
  return { tracked: {}, resolutions: {}, ...s };
}

async function writeJson(file, value) {
  await writeFile(file, JSON.stringify(value, null, 2) + '\n');
}

main().catch((err) => {
  console.error('[collector] fatal:', err?.stack ?? err);
  process.exitCode = 1;
});
