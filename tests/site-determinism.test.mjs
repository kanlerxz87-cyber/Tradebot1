import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import path from 'node:path';
import { promisify } from 'node:util';

const run = promisify(execFile);
const ROOT = path.resolve(new URL('..', import.meta.url).pathname);

// The generator used to bake a relative age ("24m ago") into every footer. Two
// consequences, both bad: the published page stated an age that was wrong from the
// moment it was served, and `build-site.mjs --check` failed for every page older
// than 90 seconds, so the CI gate was really a clock. These tests pin the fix.

async function htmlPages(dir = ROOT, out = []) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.') || ['node_modules', 'docs', 'site', 'templates', 'data', 'verification'].includes(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) await htmlPages(full, out);
    else if (entry.name.endsWith('.html')) out.push(full);
  }
  return out;
}

test('no generated page carries a build-time relative age', async () => {
  const pages = await htmlPages();
  assert.ok(pages.length >= 19, `expected the generated pages, found ${pages.length}`);
  const offenders = [];
  for (const page of pages) {
    const html = await readFile(page, 'utf8');
    const body = html.replace(/<script[\s\S]*?<\/script>/g, '');
    const hit = body.match(/\b\d+\s*(?:s|m|h|d)\s+ago\b/);
    if (hit) offenders.push(`${path.relative(ROOT, page)}: "${hit[0]}"`);
  }
  assert.deepEqual(offenders, [], 'relative ages must be computed in the browser, not baked');
});

test('the footer keeps the absolute stamp and marks it for client-side ageing', async () => {
  const html = await readFile(path.join(ROOT, 'board.html'), 'utf8');
  const m = html.match(/<time datetime="([^"]+)" data-obs-iso="([^"]+)">([^<]+)<\/time>\s*<span data-obs-rel/);
  assert.ok(m, 'expected an absolute <time> carrying data-obs-iso plus an empty data-obs-rel slot');
  assert.equal(m[1], m[2]);
  assert.match(m[1], /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/, 'the stamp is a UTC instant');
  assert.match(m[3], /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}Z$/, 'the visible stamp is the absolute time, never a relative one');
  assert.ok(!html.includes('data-obs-rel>[0-9'), 'the relative slot starts empty');
});

test('build-site.mjs --check still passes after the clock moves past the build', async () => {
  const { stdout } = await run(process.execPath, [path.join(ROOT, 'scripts/build-site.mjs'), '--check'], { cwd: ROOT });
  assert.match(stdout, /up to date/);
});

test('the build id comes from the data, not from the environment', async () => {
  // A page generated in one CI run could never match the same data rendered in another
  // when the badge carried $GITHUB_SHA: `--check` was guaranteed to fail in CI and pass
  // locally. The id is a hash of the data timestamps now, so any SHA gives the same render.
  const env = { ...process.env, GITHUB_SHA: 'deadbeefcafe' };
  const { stdout } = await run(process.execPath, [path.join(ROOT, 'scripts/build-site.mjs'), '--check'], { cwd: ROOT, env });
  assert.match(stdout, /up to date/);
  const html = await readFile(path.join(ROOT, 'executive-summary.html'), 'utf8');
  const badge = html.match(/data build ([0-9a-f]{7})/);
  assert.ok(badge, 'the badge shows a data-derived id');
  assert.ok(!html.includes('deadbee'), 'no environment value leaks into the page');
});
