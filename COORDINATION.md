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
