# Coordination board — Tradebot1

Shared task board for every agent session working on this repository. Read this
file before starting work. Claim a row, then commit and push the claim
immediately.

> **Branch rule for this repo.** Arena pins each session to one branch
> (`arena/<id>-tradebot1`) and does not permit creating or switching branches.
> The `session-<id>/<task>` convention below is therefore honoured in spirit
> only: every session works on its own Arena branch, and the final integration
> session merges into `main` through a pull request. This deviation is recorded
> here rather than silently ignored.

## Session claims

| Task | Status | Owner | File scope | Claimed (UTC) | Sources / verification / irregularities |
| --- | --- | --- | --- | --- | --- |
| Kalshi demo research, static Pages dashboard, simulation, documentation, tests, integration | in progress | `c9075e75` (branch `arena/c9075e75-tradebot1`) | `COORDINATION.md`, `README.md`, `docs/**`, `.github/**`, `tests/**` | 2026-11-22T06:56:45Z | Claim commit `c5189da`. Session claimed `docs/**` as its page root. |
| Root-page dashboard application (collector, simulator, site generator, root HTML, `assets/**`, `data/**`, `scripts/**`, `tools/**`, `verification/**`) | in progress | `9bea7e55` (branch `arena/9bea7e55-tradebot1`, this session) | `COORDINATION.md`, `README.md`, root `*.html`, `assets/**`, `data/**`, `scripts/**`, `tools/**`, `verification/**`, `.github/workflows/**` | 2026-11-22T07:05:00Z | Verified endpoint table in `docs.kalshi.com/getting_started/api_environments`; live GETs against `external-api.demo.kalshi.co` confirmed from outside the build sandbox. |

### Scope conflict resolution

Both sessions publish to GitHub Pages from `main`. To keep scopes
non-overlapping, this session (`9bea7e55`) publishes the **root** site
(`/index.html`, `/categories/…`, `/assets/…`) and does **not** create or edit
anything under `docs/`, which stays `c9075e75`'s page root. If a future
integration session decides one root must win, that decision belongs in the
*Integration log* below, not in either session's own claim row.

Shared generated files (`data/**`, `assets/**`) are written only by the owning
session for a given path; no two claims in this table overlap.

## Integration log

| When (UTC) | Session | What happened |
| --- | --- | --- |
| 2026-11-22T07:05:00Z | `9bea7e55` | Board created in this branch; `c9075e75`'s claim imported verbatim in meaning (its branch remains the authority for `docs/**`). |
| 2026-11-22T07:30:00Z | `9bea7e55` | Root dashboard built and verified. Task moved to **needs review**: published, with 17 flags on `flagged.html`. Verification record: `verification/2026-11-22-9bea7e55.md`. No file outside this session's scope was edited. |

## Session `9bea7e55` — completion record

**Status: needs review (published, non-blocking).**

### What was built

| Area | Files | Verified by |
| --- | --- | --- |
| Kalshi demo REST client, host allowlist | `tools/kalshi.mjs` | `tests/kalshi.test.mjs` (refuses non-official and wrong-environment hosts, paginates, never invents a level) |
| Five topic rules | `tools/topics.mjs` | `tests/kalshi.test.mjs`; each rule cites the request that proves it |
| Swing detection, research score, resolution mapping | `tools/alerts.mjs` | `tests/alerts-strategies.test.mjs` (threshold inclusive at $0.10, symmetric, no mid without a two-sided book) |
| Fee model | `tools/fees.mjs` | `tests/fees.test.mjs` (20 of 21 published rows in both columns) |
| Five strategies and simulated accounting | `tools/strategies.mjs` | `tests/alerts-strategies.test.mjs` (fee charged, settlement only on finalized) |
| Collector | `tools/collector.mjs` | Not run live (no egress, F-01); guarded so an empty cycle cannot overwrite good data |
| Demo-account snapshot (the only signing code) | `tools/demo-account.mjs` | Refuses any non-demo root before reading a credential; writes a disconnected snapshot when unconfigured |
| Site generator, 13 pages + 5 topic pages + 404 | `templates/`, `scripts/build-site.mjs` | `scripts/check-links.mjs`, `scripts/check-render.mjs`, publication gate |
| Committed capture and registries | `data/snapshot.json`, `data/sources.json`, `data/flags.json`, `data/live/*`, `data/account.json` | `scripts/check-data.mjs` |
| Workflows | `.github/workflows/{ci,collect,demo-account}.yml` | `ci.yml` runs every check above |

### Sources used

Official documentation: 24 pages, registered as `D1`–`D24` in `data/sources.json` and rendered on
`sources.html`. Live API observations: 13 requests, registered as `A1`–`A13` with the date and the
verbatim result. Primary publishers: 5, each named by Kalshi's own series records. Project rules:
7, each pointing at the file that implements it.

### Verification performed

32 unit assertions, a data-contract check over seven committed JSON files, an offline link check
over 19 pages and 642 references, and a jsdom render of every page asserting that each page fills
in its data and that every rendered data row carries a source link. Full record:
`verification/2026-11-22-9bea7e55.md`.

### Irregularities

17 flags, `F-01`–`F-17`, all published on `flagged.html` with source links. The three that matter
most to a reader: the authoring sandbox could not reach Kalshi directly so the collector is
untested end to end (F-01); no resolved market existed in the capture so the resolution tables are
empty rather than seeded (F-08); the demo account is not connected until secrets are added (F-13).
None of these blocks publication, and none is hidden.

### Notes for an integration session

1. `docs/**` is `c9075e75`'s scope and was not touched. If both builds publish, choose one root
   explicitly and record the decision here.
2. `data/live/*.json` ships with zero collected observations and one labelled worked example in the
   feed. The first `collect.yml` run replaces both with real data.
3. `data/account.json` ships as `connected: false`. Adding `KALSHI_API_KEY_ID` and
   `KALSHI_PRIVATE_KEY` as repository secrets, then running the "Demo account snapshot" workflow,
   fills it.
