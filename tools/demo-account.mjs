#!/usr/bin/env node
// Authenticated demo-account snapshot.
//
// This is the only place in the project that signs a Kalshi request, and it
// runs in GitHub Actions with repository secrets. A static GitHub Pages site
// cannot do this: the browser would have to hold the private key, and the
// Kalshi preflight does not even allow the KALSHI-ACCESS-* headers, so a
// signed request from a page is impossible rather than merely unwise.
//
// Signing rules, verbatim from the docs:
//   message = timestamp_ms + METHOD + path   (path WITHOUT query parameters)
//   Ed25519 keys sign the message directly; RSA keys use RSA-PSS-SHA256
//   timestamp must be within 30 s of Kalshi's clock
//   headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-SIGNATURE, KALSHI-ACCESS-TIMESTAMP
// https://docs.kalshi.com/getting_started/api_keys
//
// Refuses to run against anything but the two official demo roots, so a typo in
// an environment variable cannot push a "demo" order into production.

import { createSign, createPrivateKey, sign as edSign } from 'node:crypto';
import { writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { DEMO_REST_ROOTS } from './kalshi.mjs';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname);
const OUT = path.join(ROOT, 'data', 'account.json');

const KEY_ID = process.env.KALSHI_API_KEY_ID ?? '';
const PRIVATE_KEY_PEM = process.env.KALSHI_PRIVATE_KEY ?? '';
const REST_ROOT = (process.env.KALSHI_REST_ROOT ?? DEMO_REST_ROOTS[0]).replace(/\/$/, '');

function nowIso() { return new Date().toISOString(); }

async function write(payload) {
  await mkdir(path.dirname(OUT), { recursive: true });
  await writeFile(OUT, JSON.stringify(payload, null, 2) + '\n');
  console.log('wrote', path.relative(ROOT, OUT));
}

function sign(privateKeyPem, message) {
  const key = createPrivateKey(privateKeyPem);
  const isEd25519 = key.asymmetricKeyType === 'ed25519';
  if (isEd25519) {
    return edSign(null, Buffer.from(message), key).toString('base64');
  }
  if (key.asymmetricKeyType !== 'rsa') {
    throw new Error(`unsupported key type: ${key.asymmetricKeyType}`);
  }
  const signer = createSign('RSA-SHA256');
  signer.update(message);
  // RSA-PSS with SHA-256, MGF1-SHA256, salt length = digest length.
  return signer.sign({ key, padding: 6 /* RSA_PKCS1_PSS_PADDING */, saltLength: 32 }).toString('base64');
}

async function signedGet(restPath, query = '') {
  const pathOnly = restPath; // never include the query string in the signature
  const timestamp = String(Date.now());
  const signature = sign(PRIVATE_KEY_PEM, timestamp + 'GET' + pathOnly);
  const url = REST_ROOT + pathOnly + (query ? `?${query}` : '');
  const res = await fetch(url, {
    headers: {
      accept: 'application/json',
      'KALSHI-ACCESS-KEY': KEY_ID,
      'KALSHI-ACCESS-SIGNATURE': signature,
      'KALSHI-ACCESS-TIMESTAMP': timestamp,
    },
  });
  const text = await res.text();
  let json = null;
  try { json = text ? JSON.parse(text) : null; } catch { /* leave null */ }
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status} for ${pathOnly}`);
    err.status = res.status;
    err.code = json?.error?.code;
    err.body = json;
    throw err;
  }
  return json;
}

async function main() {
  if (!DEMO_REST_ROOTS.includes(REST_ROOT)) {
    console.error(`Refusing to sign against ${REST_ROOT}: not an official demo root.`);
    process.exitCode = 1;
    return;
  }

  if (!KEY_ID || !PRIVATE_KEY_PEM) {
    // No credentials configured. Publish the absence rather than an invented
    // balance; the site renders this as "not connected" and keeps the
    // simulated portfolio separate and clearly labelled.
    await write({
      connected: false,
      checkedAt: nowIso(),
      restRoot: REST_ROOT,
      reason: 'KALSHI_API_KEY_ID and/or KALSHI_PRIVATE_KEY are not set in this repository, so no authenticated demo-account read was made.',
      howToConnect: [
        'Create a demo account at https://demo.kalshi.co/ (Kalshi tutorial: https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account)',
        'Create an API key on the demo site and add KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY as repository secrets',
        'Re-run the "Demo account snapshot" workflow',
      ],
      docs: 'https://docs.kalshi.com/getting_started/api_keys',
      demoDocs: 'https://docs.kalshi.com/getting_started/demo_env',
      balance: null,
      positions: null,
      fills: null,
      settlements: null,
    });
    console.log('no credentials; wrote a disconnected snapshot');
    return;
  }

  const snapshot = {
    connected: false,
    checkedAt: nowIso(),
    restRoot: REST_ROOT,
    balance: null,
    positions: null,
    fills: null,
    settlements: null,
    errors: [],
  };

  try {
    snapshot.balance = await signedGet('/trade-api/v2/portfolio/balance');
    snapshot.connected = true;
  } catch (err) {
    snapshot.errors.push({ call: 'balance', status: err.status ?? null, code: err.code ?? null, message: err.message });
  }
  for (const [key, restPath, query] of [
    ['positions', '/trade-api/v2/portfolio/positions', 'count_filter=position&settlement_status=all&limit=200'],
    ['fills', '/trade-api/v2/portfolio/fills', 'limit=200'],
    ['settlements', '/trade-api/v2/portfolio/settlements', 'limit=200'],
  ]) {
    try {
      snapshot[key] = await signedGet(restPath, query);
      if (!snapshot.connected) snapshot.connected = true;
    } catch (err) {
      snapshot.errors.push({ call: key, status: err.status ?? null, code: err.code ?? null, message: err.message });
    }
  }

  snapshot.sources = {
    balance: 'https://docs.kalshi.com/api-reference/portfolio/get-balance',
    positions: 'https://docs.kalshi.com/api-reference/portfolio/get-positions',
    fills: 'https://docs.kalshi.com/api-reference/portfolio/get-fills',
    settlements: 'https://docs.kalshi.com/api-reference/portfolio/get-settlements',
    signing: 'https://docs.kalshi.com/getting_started/api_keys',
  };
  snapshot.demoWarning = 'Kalshi states that demo market prices and behaviour may not reflect real markets. https://docs.kalshi.com/getting_started/demo_env';

  await write(snapshot);

  if (snapshot.errors.length) {
    console.error('some authenticated reads failed:', JSON.stringify(snapshot.errors, null, 2));
    // A partially connected account is still useful, but a run where every
    // read failed should be red.
    if (!snapshot.connected) process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error('fatal', err?.stack ?? err);
  process.exitCode = 1;
});
