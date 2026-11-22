import test from 'node:test';
import assert from 'node:assert/strict';
import { takerFee, makerFee, roundUpCenticent, roundUpCent, PUBLISHED_FEE_TABLE, TAKER_RATE } from '../tools/fees.mjs';

// The formula is checked against the official fee schedule's own table, so a
// wrong implementation cannot pass just by being self-consistent.
// Source: https://kalshi.com/docs/kalshi-fee-schedule.pdf

test('the published table has 21 rows and all of them reproduce (AUD-05)', () => {
  // The schedule prints four columns: price for 1, fee for 1, price for 100, fee for 100.
  // Reading the third column as a fee made the $0.01 row look unreproducible; its real
  // fee for 100 contracts is $0.07. https://kalshi.com/docs/kalshi-fee-schedule.pdf
  assert.equal(PUBLISHED_FEE_TABLE.length, 21);
  assert.equal(takerFee(100, 0.01), 0.07);
  assert.equal(takerFee(1, 0.01), 0.01);
});

test('taker fee matches every reproducible published single-contract row', () => {
  for (const [price, publishedFee] of PUBLISHED_FEE_TABLE) {
    assert.equal(takerFee(1, price), publishedFee, `1 contract at $${price}`);
  }
});

test('taker fee matches every published 100-contract row', () => {
  for (const [price, , publishedFee100] of PUBLISHED_FEE_TABLE) {
    assert.equal(takerFee(100, price), publishedFee100, `100 contracts at $${price}`);
  }
});

test('rounding helpers round up, never down', () => {
  assert.equal(roundUpCenticent(0.00000001), 0.0001);
  assert.equal(roundUpCenticent(0.0001), 0.0001);
  assert.equal(roundUpCenticent(0.00011), 0.0002);
  assert.equal(roundUpCent(0.0001), 0.01);
  assert.equal(roundUpCent(0.0100001), 0.02);
  assert.equal(roundUpCent(0.01), 0.01);
});

test('fee is symmetric around 50c and zero at the boundaries and at zero contracts', () => {
  assert.equal(takerFee(100, 0.4), takerFee(100, 0.6));
  assert.equal(takerFee(100, 0), 0);
  assert.equal(takerFee(100, 1), 0);
  assert.equal(takerFee(0, 0.5), 0);
});

test('fee never decreases as count increases, at a fixed price', () => {
  let previous = 0;
  for (let n = 0; n <= 200; n += 7) {
    const fee = takerFee(n, 0.37);
    assert.ok(fee >= previous, `fee at ${n} contracts`);
    previous = fee;
  }
});

test('maker rate is 0.0175 relative to the taker rate of 0.07', () => {
  // 100 contracts at 50c: 100 * 0.0175 * 0.5 * 0.5 = 0.4375 -> rounds up to 0.44.
  assert.equal(makerFee(100, 0.5), 0.44);
  assert.ok(makerFee(100, 0.5) < takerFee(100, 0.5));
});

test('taker rate constant is the published 0.07', () => {
  assert.equal(TAKER_RATE, 0.07);
});
