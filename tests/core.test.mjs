import test from 'node:test';
import assert from 'node:assert/strict';
import { topicFor, price, qty, delta, swing, qualifies, resolution, paperBuy, paperPnl, estimate } from '../docs/assets/core.mjs';
test('strict fields and no fabricated zero', () => {
  assert.equal(price(''), null); assert.equal(price('0.0000'), 0); assert.equal(price('1.1'), null);
  assert.equal(qty(''), null); assert.equal(estimate({last_price_dollars:'0.2'}), null);
});
test('signed swings include both boundaries and reject missing samples', () => {
  assert.equal(swing('0.2000','0.3000'), 0.1); assert.equal(swing('0.3000','0.2000'), -0.1);
  assert.equal(swing('0.2000','0.2999'), null); assert.equal(swing('','0.45'), null);
  assert.equal(delta('0.1','0.2'), 0.1);
});
test('only supported topics, no presumptive ROI', () => {
  assert.equal(topicFor({title:'Gas prices next week?'}), 'gas');
  assert.equal(topicFor({category:'Elections',title:'Next Pope?'}), null);
  assert.equal(topicFor({category:'Elections',title:'Presidential election 2028?'}), 'elections');
  assert.equal(topicFor({title:'Golf: PGA winner?'}), 'golf');
  assert.equal(topicFor({title:'Fed rate decision'}), null);
  assert.equal(qualifies({ status:'active',yes_bid_dollars:'0.40',yes_ask_dollars:'0.45',volume_24h_fp:'101' }),true);
  assert.equal(qualifies({ status:'active',yes_bid_dollars:'0.40',yes_ask_dollars:'0.90',volume_24h_fp:'101' }),false);
});
test('resolution and paper P&L never pretend unconfirmed outcome', () => {
  const m={ticker:'X',event_ticker:'E',status:'active',yes_ask_dollars:'0.56',yes_bid_dollars:'0.53'};
  const t=paperBuy(m,'crypto','screen'); assert.equal(t.entry, .56);
  assert.ok(Math.abs(paperPnl(t,m) + .03)<1e-9);
  assert.equal(resolution({...m,status:'closed',result:'yes'}),null);
  assert.equal(resolution({...m,status:'determined',result:'yes'}),null);
  assert.ok(Math.abs(paperPnl(t,{...m,status:'finalized',result:'yes'}) - .44)<1e-9);
  assert.equal(paperPnl(t,{...m,yes_bid_dollars:''}),null);
});
