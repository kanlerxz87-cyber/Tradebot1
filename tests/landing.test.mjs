// Tests for the root landing page: the generator's output and the live-refresh runtime.
// Run: node --test tests/landing.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel) => readFileSync(path.join(ROOT, rel), "utf8");
const json = (rel) => JSON.parse(readFileSync(path.join(ROOT, rel), "utf8"));

const PAGE = read("index.html");
const TOPICS = ["gas", "elections", "culture", "crypto", "golf"];

test("landing page is a complete document with one main landmark", () => {
  assert.match(PAGE, /<!DOCTYPE html>/i);
  assert.match(PAGE, /<title>[^<]+<\/title>/);
  assert.equal((PAGE.match(/<main/g) || []).length, 1);
  assert.equal((PAGE.match(/<\/main>/g) || []).length, 1);
  assert.ok(!PAGE.includes("{{"), "no unreplaced template token may reach the published page");
});

test("landing page organises the five topics and nothing else", () => {
  for (const topic of TOPICS) {
    assert.ok(PAGE.includes(`class="chip ${topic}"`), `missing topic chip ${topic}`);
  }
  // No sixth topic may creep in through the data.
  const chips = new Set([...PAGE.matchAll(/class="chip ([a-z]+)"/g)].map((m) => m[1]));
  for (const chip of chips) {
    assert.ok(
      [...TOPICS, "ok", "warn", "bad", "filtered", "all"].includes(chip),
      `unexpected chip class "${chip}" — the brief allows five topics only`,
    );
  }
});

test("every leaderboard row carries a source link", () => {
  const table = PAGE.slice(PAGE.indexOf('id="leaderboard"'), PAGE.indexOf("</table>", PAGE.indexOf('id="leaderboard"')));
  assert.ok(table.length > 0, "leaderboard table missing");
  const rows = table.split("<tr>").slice(1);
  assert.ok(rows.length >= 2, "expected a header plus at least one data row");
  for (const row of rows.slice(1)) {
    assert.match(row, /<a href="https:\/\/kalshi\.com\/markets\//, "data row without a Kalshi source link");
  }
});

test("the page states its own data age and the missing demo account", () => {
  assert.match(PAGE, /Published snapshot/);
  assert.match(PAGE, /Demo account not connected|Demo account: <b>connected/);
});

test("snapshot-derived numbers match the published data file", () => {
  const latest = json("docs/desk/data/latest.json");
  const expected = Object.values(latest.topics).reduce((sum, t) => sum + (t.notional_24h_est || 0), 0);
  const rounded = Math.round(expected).toLocaleString("en-US");
  assert.ok(PAGE.includes(rounded), `page does not show total est. 24h notional ${rounded}`);
  assert.ok(PAGE.includes(String(latest.market_count)), "page does not show the tracked market count");
});

/* ------------------------------------------------------------------ runtime */
function makeDocument() {
  const hosts = new Map();
  const element = (sel) => ({
    sel,
    innerHTML: "",
    textContent: "",
    disabled: false,
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {},
    appendChild() {},
    querySelector: () => null,
    querySelectorAll: () => [],
  });
  return {
    hosts,
    readyState: "complete",
    documentElement: { style: {} },
    querySelector(sel) {
      if (!hosts.has(sel)) hosts.set(sel, element(sel));
      return hosts.get(sel);
    },
    querySelectorAll: () => [],
    addEventListener() {},
    getElementById(id) {
      const sel = "#" + id;
      if (!hosts.has(sel)) hosts.set(sel, element(sel));
      return hosts.get(sel);
    },
  };
}

// The runtime chains several promises; give the microtask queue room to settle.
const flush = async () => {
  for (let i = 0; i < 8; i += 1) await new Promise((resolve) => setImmediate(resolve));
};

function runLanding(payloads, fetchImpl) {
  const document = makeDocument();
  const calls = [];
  const sandbox = {
    document,
    console,
    Date,
    Math,
    Number,
    String,
    Object,
    Array,
    Promise,
    Error,
    isNaN,
    JSON,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    fetch: (url) => {
      calls.push(url);
      if (fetchImpl) return fetchImpl(url);
      const name = String(url).split("/").pop().split("?")[0];
      const body = payloads[name];
      if (body === undefined) return Promise.reject(new Error("HTTP 404"));
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(read("assets/landing.js"), sandbox, { filename: "landing.js" });
  return { document, calls, sandbox };
}

const livePayloads = {
  "latest.json": json("docs/desk/data/latest.json"),
  "alerts.json": json("docs/desk/data/alerts.json"),
  "resolved.json": json("docs/desk/data/resolved.json"),
  "paper.json": json("docs/desk/data/paper.json"),
};

test("runtime renders every panel from the published snapshot without throwing", async () => {
  const { document } = runLanding(livePayloads);
  await flush();
  const html = (sel) => (document.hosts.get(sel) || {}).innerHTML || "";
  assert.match(html("#kpiHost"), /Tracked markets/);
  assert.match(html("#topicCards"), /Open the gas prices desk/);
  assert.match(html("#leaderboard"), /<table>/);
  assert.match(html("#chatAll"), /chat-empty|class="msg"/);
  assert.match(html("#chatModel"), /chat-empty|class="msg"/);
  assert.match(html("#paperPanel"), /Simulated book/);
  assert.match(html("#resolvedPanel"), /Resolution tracker/);
  assert.match(html("#topStatus"), /Published snapshot/);
});

test("runtime never invents values when the snapshot is empty", async () => {
  const { document } = runLanding({
    "latest.json": { generated_at: null, generated_ts: 0, topics: {}, market_count: 0, event_count: 0, errors: [] },
    "alerts.json": { generated_at: null, threshold: 0.1, items: [] },
    "resolved.json": { generated_at: null, items: [] },
    "paper.json": { headline: {}, summary: {} },
  });
  await flush();
  const kpi = document.hosts.get("#kpiHost").innerHTML;
  const leaderboard = document.hosts.get("#leaderboard").innerHTML;
  assert.match(kpi, /—/, "empty data must render an em dash, never a number");
  assert.match(leaderboard, /No open events in the current snapshot\./);
  assert.ok(!leaderboard.includes("<tr>"), "no fabricated leaderboard rows");
});

test("runtime keeps the rendered page when a fetch fails", async () => {
  const { document } = runLanding({}, () => Promise.reject(new Error("HTTP 500")));
  await flush();
  const note = document.hosts.get("#liveNote").innerHTML;
  assert.match(note, /Live refresh unavailable/);
  assert.match(note, /HTTP 500/);
  // Panels were never written to, so the server-rendered markup survives untouched.
  assert.equal((document.hosts.get("#kpiHost") || { innerHTML: "untouched" }).innerHTML, "untouched");
});

test("runtime reads only files the collector already publishes", async () => {
  const { calls } = runLanding(livePayloads);
  await new Promise((resolve) => setImmediate(resolve));
  const allowed = new Set([
    "latest.json", "alerts.json", "resolved.json", "paper.json",
  ]);
  for (const url of calls) {
    const name = String(url).split("/").pop().split("?")[0];
    assert.ok(allowed.has(name), `unexpected data request: ${url}`);
    assert.match(String(url), /^docs\/desk\/data\//, "data must come from the published desk snapshot");
  }
});

test("the landing generator is the single source of the published page", () => {
  const template = read("tools/landing_template.html");
  for (const token of [
    "{{STATUS_HTML}}", "{{KPI_HTML}}", "{{TOPIC_CARDS_HTML}}", "{{LEADERBOARD_HTML}}",
    "{{CHAT_ALL_HTML}}", "{{CHAT_MODEL_HTML}}", "{{PAPER_HTML}}", "{{RESOLVED_HTML}}",
    "{{ERRORS_HTML}}", "{{GENERATED_AT}}",
  ]) {
    assert.ok(template.includes(token), `template is missing ${token}`);
  }
  assert.ok(existsSync(path.join(ROOT, "tools/build_landing.py")), "landing generator missing");
});
