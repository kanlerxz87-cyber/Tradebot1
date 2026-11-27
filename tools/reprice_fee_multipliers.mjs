#!/usr/bin/env node
// Re-price the simulated book against Kalshi's published per-series fee multipliers.
//
//   node tools/reprice_fee_multipliers.mjs --dry-run   # show what would change
//   node tools/reprice_fee_multipliers.mjs --apply     # rewrite data/live/portfolio.json
//
// Why this exists (2026-11-27). tools/strategies.mjs used to charge every simulated fill
// the general taker fee without the per-series multiplier M, although the fee schedule
// publishes M per series and the project's own positions sit on a series the schedule lists
// as 0/0. Every KXBTCY ("BTC price range EOY") fill was therefore charged $0.01 that the
// exchange's published schedule does not charge. The model is fixed in tools/fees.mjs and
// tools/strategies.mjs; this script applies the same published multipliers to the fills
// already recorded, so the committed ledger and the model agree.
//
// Source: https://kalshi.com/docs/kalshi-fee-schedule.pdf ("Non-Standard Fees",
// made effective 2026-07-07). No price, size or timestamp is touched: only fee fields, the
// derived P&L fields that contain a fee, and the summary totals.
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { takerFee, seriesMultiplier, seriesFromTicker, MULTIPLIER_SOURCE, FEE_SOURCE } from './fees.mjs';
import { SERIES_API_SOURCE } from './strategies.mjs';
import { portfolioSummary } from './strategies.mjs';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname);
const FILE = path.join(ROOT, 'data', 'live', 'portfolio.json');
const APPLY = process.argv.includes('--apply');
const round2 = (n) => Math.round((n + Number.EPSILON) * 100) / 100;

const portfolio = JSON.parse(await readFile(FILE, 'utf8'));
const before = { ...portfolio.summary };
const changes = [];

for (const position of portfolio.positions) {
  const series = position.seriesTicker || seriesFromTicker(position.ticker);
  // A fill that already recorded the exchange-published multiplier keeps it; otherwise the
  // published schedule row is used, and an unlisted series keeps the general multiplier of 1.
  const recorded = Number(position.feeMultiplier);
  const keepRecorded = position.feeMultiplierSource === SERIES_API_SOURCE
    && Number.isFinite(recorded) && recorded >= 0;
  const multiplier = keepRecorded ? recorded : seriesMultiplier(series, 'taker');
  const entryFee = round2(takerFee(position.contracts, position.entryPrice, multiplier));

  // Fill fields the older records never stored, so a reader can check the arithmetic.
  position.seriesTicker = series;
  position.feeMultiplier = multiplier;
  position.feeMultiplierSource = keepRecorded ? SERIES_API_SOURCE : MULTIPLIER_SOURCE;

  if (entryFee !== position.entryFee) {
    changes.push({ ticker: position.ticker, field: 'entryFee', from: position.entryFee, to: entryFee });
    position.entryFee = entryFee;
  }

  if (position.exitPrice != null) {
    const exitFee = round2(takerFee(position.contracts, position.exitPrice, multiplier));
    if (exitFee !== position.exitFee) {
      changes.push({ ticker: position.ticker, field: 'exitFee', from: position.exitFee, to: exitFee });
      position.exitFee = exitFee;
    }
  }

  // Re-derive only the P&L fields whose formula contains a fee. An open position with no
  // stored exit price is marked at its own entry price (no spread assumed), which makes its
  // unrealised P&L exactly minus the entry fee.
  if (position.status === 'settled' && typeof position.payout === 'number') {
    position.realizedPnl = round2(position.payout - position.entryCost - position.entryFee);
  } else if (position.status === 'open') {
    const exit = position.exitPrice;
    position.unrealizedPnl = exit == null
      ? round2(-position.entryFee)
      : round2(position.contracts * exit - position.entryCost - position.entryFee - (position.exitFee ?? 0));
  }
}

portfolio.summary = portfolioSummary({
  positions: portfolio.positions,
  startingCash: portfolio.startingCash,
});
portfolio.feeSource = FEE_SOURCE;
portfolio.feeMultiplierSource = MULTIPLIER_SOURCE;
portfolio.feeRepricing = {
  performedAt: new Date().toISOString(),
  reason: 'Apply the published per-series fee multiplier M to fills recorded before the model used it.',
  source: MULTIPLIER_SOURCE,
  positionsAffected: new Set(changes.map((c) => c.ticker)).size,
  fieldsChanged: changes.length,
  summaryBefore: before,
  summaryAfter: portfolio.summary,
};

console.log(JSON.stringify({ changes, before, after: portfolio.summary }, null, 2));
if (APPLY) {
  await writeFile(FILE, `${JSON.stringify(portfolio, null, 2)}\n`);
  console.log(`wrote ${path.relative(ROOT, FILE)}`);
} else {
  console.log('dry run — pass --apply to write');
}
