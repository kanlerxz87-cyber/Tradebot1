#!/usr/bin/env node
// Kalshi demo connectivity probe — measures, never guesses.
// Runs from a GitHub-hosted runner (has egress) or locally (records sandbox failures honestly).
// Writes probe/results.json with raw status codes and CORS headers as evidence.
//
// Official sources for what is being tested:
//  - REST/WS hosts:      https://docs.kalshi.com/getting_started/api_environments
//  - Public reads:       https://docs.kalshi.com/getting_started/quick_start_market_data
//  - Signed requests:    https://docs.kalshi.com/getting_started/quick_start_authenticated_requests
//  - WS handshake auth:  https://docs.kalshi.com/getting_started/quick_start_websockets
//
// No credentials are used or required. Nothing here places orders.

import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { request as httpsRequest } from 'node:https';
import { randomBytes } from 'node:crypto';

const OUT = join(dirname(fileURLToPath(import.meta.url)), 'results.json');

const ORIGIN_A = 'https://kanlerxz87-cyber.github.io'; // published Pages origin
const ORIGIN_B = 'http://localhost:8000';              // second origin to detect echo-vs-wildcard

const REST_HOSTS = [
  { name: 'external-api.demo (recommended)', host: 'external-api.demo.kalshi.co' },
  { name: 'demo-api (legacy supported)', host: 'demo-api.kalshi.co' },
];
const WS_HOSTS = [
  { name: 'external-api-ws.demo (recommended)', host: 'external-api-ws.demo.kalshi.co', path: '/trade-api/ws/v2' },
  { name: 'demo-api ws (legacy supported)', host: 'demo-api.kalshi.co', path: '/trade-api/ws/v2' },
];

const CORS_HEADERS = [
  'access-control-allow-origin',
  'access-control-allow-credentials',
  'access-control-allow-methods',
  'access-control-allow-headers',
  'access-control-expose-headers',
  'vary',
];
const RATE_HEADERS = ['x-ratelimit-limit', 'x-ratelimit-remaining', 'x-ratelimit-reset', 'x-ratelimit-cost'];

function pick(headers, names) {
  const out = {};
  for (const n of names) {
    const v = headers[n] ?? headers[n.toLowerCase()];
    if (v !== undefined) out[n] = Array.isArray(v) ? v.join(', ') : String(v);
  }
  return out;
}

async function timedFetch(url, options = {}, bodyLimit = 400) {
  const started = Date.now();
  try {
    const res = await fetch(url, { ...options, signal: AbortSignal.timeout(15000), redirect: 'manual' });
    const raw = await res.text();
    let json = null;
    try { json = JSON.parse(raw); } catch {}
    return {
      ok: res.ok,
      status: res.status,
      ms: Date.now() - started,
      cors: pick(Object.fromEntries(res.headers), CORS_HEADERS),
      rate_limit: pick(Object.fromEntries(res.headers), RATE_HEADERS),
      body_sample: raw.slice(0, bodyLimit),
      body_bytes: raw.length,
      json,
      error: null,
    };
  } catch (err) {
    return {
      ok: false,
      status: null,
      ms: Date.now() - started,
      cors: {},
      rate_limit: {},
      body_sample: '',
      body_bytes: 0,
      json: null,
      error: String(err?.cause?.code || err?.name || err?.message || err),
    };
  }
}

// Raw TLS HTTP upgrade attempt so we can read the exact handshake status code
// (browsers cannot see this; Node has no built-in way beyond this request shape).
function wsHandshake(host, path, origin) {
  return new Promise((resolve) => {
    const key = randomBytes(16).toString('base64');
    const started = Date.now();
    let settled = false;
    const done = (result) => { if (!settled) { settled = true; resolve(result); } };
    let req;
    try {
      req = httpsRequest({
        host,
        path,
        method: 'GET',
        timeout: 15000,
        headers: {
          Connection: 'Upgrade',
          Upgrade: 'websocket',
          Origin: origin,
          'Sec-WebSocket-Key': key,
          'Sec-WebSocket-Version': '13',
        },
      }, (res) => {
        const chunks = [];
        res.on('data', (c) => { if (chunks.join('').length < 400) chunks.push(c); });
        res.on('end', () => done({
          status: res.statusCode,
          ms: Date.now() - started,
          headers: pick(res.headers, ['upgrade', 'connection', 'sec-websocket-accept', 'www-authenticate']),
          body_sample: Buffer.concat(chunks).toString('utf8').slice(0, 300),
          error: null,
        }));
      });
      req.on('error', (e) => done({ status: null, ms: Date.now() - started, headers: {}, body_sample: '', error: String(e.code || e.message) }));
      req.on('timeout', () => { req.destroy(new Error('timeout')); });
      req.end();
    } catch (e) {
      done({ status: null, ms: Date.now() - started, headers: {}, body_sample: '', error: String(e.message) });
    }
  });
}

async function main() {
  const probes = [];
  const add = (p) => { const { json: _json, ...rest } = p; probes.push(rest); console.log(`- ${rest.name}: ${rest.error ? 'ERROR ' + rest.error : rest.status}`); };

  for (const { name, host } of REST_HOSTS) {
    const base = `https://${host}/trade-api/v2`;

    add({ name: `${name} GET /exchange/status`, kind: 'rest', host,
      ...(await timedFetch(`${base}/exchange/status`, { headers: { Origin: ORIGIN_A } })) });

    const markets = await timedFetch(`${base}/markets?limit=1&status=open`, { headers: { Origin: ORIGIN_A } });
    add({ name: `${name} GET /markets?limit=1&status=open (Origin A)`, kind: 'rest', host, ...markets });

    add({ name: `${name} GET /markets?limit=1&status=open (Origin B)`, kind: 'rest', host,
      ...(await timedFetch(`${base}/markets?limit=1&status=open`, { headers: { Origin: ORIGIN_B } })) });

    // Preflight for a signed POST (KALSHI-ACCESS-* headers) — decides if a browser could ever place orders.
    add({ name: `${name} OPTIONS preflight signed POST /portfolio/events/orders`, kind: 'preflight', host,
      ...(await timedFetch(`${base}/portfolio/events/orders`, {
        method: 'OPTIONS',
        headers: {
          Origin: ORIGIN_A,
          'Access-Control-Request-Method': 'POST',
          'Access-Control-Request-Headers': 'content-type,kalshi-access-key,kalshi-access-signature,kalshi-access-timestamp',
        },
      })) });

    // Preflight for plain JSON GET (baseline).
    add({ name: `${name} OPTIONS preflight GET /markets (content-type json)`, kind: 'preflight', host,
      ...(await timedFetch(`${base}/markets`, {
        method: 'OPTIONS',
        headers: {
          Origin: ORIGIN_A,
          'Access-Control-Request-Method': 'GET',
          'Access-Control-Request-Headers': 'content-type',
        },
      })) });

    // Dynamic follow-ups from the first market (orderbook + event + candles).
    const first = markets.json?.markets?.[0];
    const ticker = first?.ticker || null;
    const eventTicker = first?.event_ticker || null;

    if (ticker) {
      add({ name: `${name} GET /markets/{ticker}/orderbook`, kind: 'rest', host,
        ...(await timedFetch(`${base}/markets/${encodeURIComponent(ticker)}/orderbook`, { headers: { Origin: ORIGIN_A } })) });
      let series = null;
      if (eventTicker) {
        const ev = await timedFetch(`${base}/events/${encodeURIComponent(eventTicker)}`, { headers: { Origin: ORIGIN_A } });
        add({ name: `${name} GET /events/{event_ticker}`, kind: 'rest', host, ...ev });
        series = ev.json?.event?.series_ticker || null;
      }
      if (series) {
        const end = Math.floor(Date.now() / 1000);
        add({ name: `${name} GET candlesticks (period 1m)`, kind: 'rest', host,
          ...(await timedFetch(`${base}/series/${encodeURIComponent(series)}/markets/${encodeURIComponent(ticker)}/candlesticks?start_ts=${end - 3600}&end_ts=${end}&period_interval=1`, { headers: { Origin: ORIGIN_A } })) });
      }
    }
  }

  for (const { name, host, path } of WS_HOSTS) {
    add({ name: `${name} WS handshake (no auth headers)`, kind: 'ws', host, ...(await wsHandshake(host, path, ORIGIN_A)) });
  }

  const byKind = (k) => probes.filter((p) => p.kind === k);
  const corsOkForA = (p) => {
    const a = p.cors['access-control-allow-origin'];
    return !!a && (a === '*' || a === ORIGIN_A);
  };
  const publicReadsA = byKind('rest').filter((p) => p.status === 200 && !p.name.includes('Origin B'));
  const signedPreflight = probes.find((p) => p.name.includes('signed POST'));
  const allowHeaders = (signedPreflight?.cors['access-control-allow-headers'] || '').toLowerCase();
  const signedAllowed = ['kalshi-access-key', 'kalshi-access-signature', 'kalshi-access-timestamp'].every((h) => allowHeaders.includes(h));
  const wsProbes = byKind('ws');

  const results = {
    generated_at: new Date().toISOString(),
    runner: {
      node: process.version,
      os: `${process.platform} ${process.arch}`,
      github_run_id: process.env.GITHUB_RUN_ID || null,
      github_repository: process.env.GITHUB_REPOSITORY || null,
      sandbox_note: process.env.GITHUB_ACTIONS ? 'GitHub-hosted runner (has egress to kalshi.co)' : 'local run — if all REST probes report network errors, this sandbox blocks egress to Kalshi hosts (expected; use the Actions run as evidence)',
    },
    origins_tested: [ORIGIN_A, ORIGIN_B],
    probes,
    verdicts: {
      public_reads_cors_allowed_for_pages_origin: publicReadsA.length > 0 && publicReadsA.every(corsOkForA),
      public_reads_cors_allowed_detail: publicReadsA.map((p) => ({ name: p.name, status: p.status, allow_origin: p.cors['access-control-allow-origin'] || null, allow_credentials: p.cors['access-control-allow-credentials'] || null })),
      origin_b_also_echoed: (() => { const p = probes.find((x) => x.name.includes('Origin B')); const a = p?.cors['access-control-allow-origin']; return a === ORIGIN_B || a === '*'; })(),
      signed_requests_preflight_allowed_from_browser: signedAllowed,
      signed_preflight_allow_headers: signedPreflight?.cors['access-control-allow-headers'] || null,
      signed_preflight_status: signedPreflight?.status ?? null,
      ws_unauthenticated_handshake: wsProbes.map((p) => ({ name: p.name, status: p.status, error: p.error })),
      rate_limit_headers_observed: probes.some((p) => Object.keys(p.rate_limit || {}).length > 0),
    },
    sources: [
      'https://docs.kalshi.com/getting_started/api_environments',
      'https://docs.kalshi.com/getting_started/quick_start_market_data',
      'https://docs.kalshi.com/getting_started/quick_start_authenticated_requests',
      'https://docs.kalshi.com/getting_started/quick_start_websockets',
    ],
  };

  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, JSON.stringify(results, null, 2));
  console.log(`\nWrote ${OUT}`);
  console.log(JSON.stringify(results.verdicts, null, 2));
}

main().catch((e) => { console.error(e); process.exit(1); });
