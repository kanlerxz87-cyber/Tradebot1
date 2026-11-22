#!/usr/bin/env node
// Offline link checker.
//
// Checks every published HTML file for:
//   * internal links and assets that do not exist on disk
//   * anchors that point at an id the target page does not define
//   * a page with no navigation back to the board
//   * external links with a missing or non-http scheme
//
// It never makes a network request: external URLs are checked for shape only.
// Run: node scripts/check-links.mjs

import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { existsSync } from 'node:fs';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname);

async function htmlFiles(dir = ROOT, out = []) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.') || entry.name === 'node_modules' || entry.name === 'templates' || entry.name === 'tests' || entry.name === 'tools' || entry.name === 'scripts') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (['data', 'assets', '.github', 'verification'].includes(entry.name)) continue;
      await htmlFiles(full, out);
    } else if (entry.name.endsWith('.html')) out.push(full);
  }
  return out;
}

function stripQuery(href) { return href.split('#')[0].split('?')[0]; }

async function main() {
  const files = await htmlFiles();
  const problems = [];
  let checked = 0;
  let external = 0;

  // Cache page ids for anchor checks.
  const idCache = new Map();
  async function idsOf(file) {
    if (idCache.has(file)) return idCache.get(file);
    const text = await readFile(file, 'utf8');
    const ids = new Set([...text.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]));
    idCache.set(file, ids);
    return ids;
  }

  for (const file of files) {
    const text = await readFile(file, 'utf8');
    const rel = path.relative(ROOT, file);
    const hrefs = [...text.matchAll(/href="([^"]+)"/g)].map((m) => m[1]);
    const srcs = [...text.matchAll(/src="([^"]+)"/g)].map((m) => m[1]);

    for (const href of hrefs) {
      checked += 1;
      if (href.startsWith('data:') || href.startsWith('mailto:')) continue;
      if (/^https?:\/\//.test(href)) { external += 1; continue; }
      if (href.startsWith('#')) {
        const target = href.slice(1);
        if (target && !(await idsOf(file)).has(target)) problems.push(`${rel}: dead in-page anchor ${href}`);
        continue;
      }
      const [target, fragment] = href.split('#');
      const cleaned = stripQuery(target);
      if (!cleaned) continue;
      const full = path.resolve(path.dirname(file), cleaned);
      if (!existsSync(full)) { problems.push(`${rel}: missing target ${cleaned}`); continue; }
      if (fragment) {
        // A fragment into a page whose ids are added by JavaScript is allowed
        // only when the page is one of the known dynamic ones.
        const ids = await idsOf(full);
        const dynamic = /\/(flagged|market|dashboard)\.html$/.test(full);
        if (!ids.has(fragment) && !dynamic) problems.push(`${rel}: anchor ${fragment} not found in ${path.relative(ROOT, full)}`);
      }
    }

    for (const src of srcs) {
      checked += 1;
      if (/^https?:\/\//.test(src) || src.startsWith('data:')) { external += 1; continue; }
      const full = path.resolve(path.dirname(file), stripQuery(src));
      if (!existsSync(full)) problems.push(`${rel}: missing asset ${src}`);
    }

    if (!rel.includes('categories/') && !/<nav class="main"/.test(text)) problems.push(`${rel}: no main navigation`);
    if (!/assets\/style\.css/.test(text)) problems.push(`${rel}: stylesheet not linked`);
  }

  console.log(`${files.length} pages, ${checked} references, ${external} external, ${problems.length} problems.`);
  if (problems.length) {
    console.error(problems.slice(0, 40).join('\n'));
    process.exitCode = 1;
  }
}

main().catch((err) => { console.error(err); process.exitCode = 1; });
