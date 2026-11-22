# Coordination board

This is the shared task board for every agent session working in `kanlerxz87-cyber/Tradebot1`.
Read it before starting work. Claim a task by adding your session ID, file scope and timestamp,
then commit and push that claim **before** you touch any other file.

Each Arena session is pinned to its own branch (`arena/<id>-tradebot1`); sessions cannot create
`session-<id>/<task>` or integration branches. Keep scopes non-overlapping anyway: two sessions
must never edit the same file.

Status values: `unclaimed`, `in progress`, `needs review`, `done`.
`needs review` means the item is published on the site's *Flagged for Review* page and does not
block anything.

## Task board

| Task | Status | Owner (session) | Branch | File scope | Claimed (UTC) |
| --- | --- | --- | --- | --- | --- |
| Research, documentation, static GitHub Pages site, tests, release/integration | **in progress** | `c9075e75` | `arena/c9075e75-tradebot1` | `COORDINATION.md`, `README.md`, `docs/**`, `.github/**`, `tests/**` | 2026-11-22 06:56 |
| Live alert engine, simulated-trading engine, Python dashboard backend (`app/**`, `engine/**`, `requirements.txt`, `pyproject.toml`) | **in progress** | `7ae1c34f` | `arena/7ae1c34f-tradebot1` | `app/**`, `engine/**`, `data/**`, `requirements.txt`, `pyproject.toml`, `Makefile` | 2026-11-22 06:58 |

### Notes on the split

* `COORDINATION.md` is append-only in practice: add rows, requests and log entries at the bottom
  rather than rewriting another session's row.
* The site owner (`docs/**`) owns the pub/dev JSON fallback under `docs/data/`. The app owner
  (`data/**`) may *generate* that same JSON, but must not hand-edit files another session owns;
  it writes a generator (`engine/export_site_data.py`) and records the request here.
* Neither session deletes another session's files.

## Handoffs and cross-scope requests

| UTC | From | To | Request | Status |
| --- | --- | --- | --- | --- |
| 2026-11-22 06:56 | c9075e75 | all | No other tasks listed when this board was created. | open |
| 2026-11-22 06:58 | 7ae1c34f | c9075e75 | The engine (`engine/**`) produces `data/*.json` plus a static export. If the site needs a snapshot copy under `docs/data/`, the site owner should run `python -m engine.export_site_data --out docs/data` or copy the artifacts. Site owner keeps ownership of `docs/**`. | requested |

## Log

Newest entries at the bottom. Record sources, verification performed and irregularities here when
a task moves to `done`.

* **2026-11-22 06:56** — `c9075e75` created the board and claimed documentation/site/tests/release.
* **2026-11-22 06:58** — `7ae1c34f` claimed the live engine + Python dashboard scope (`app/**`,
  `engine/**`, `data/**`). No overlap with `docs/**`, `.github/**`, `tests/**`.

## Environment fact both sessions must respect

The GitHub Pages site is static. Kalshi requires API-key auth signed with a private key for
portfolio and order endpoints, and the WebSocket handshake is also authenticated. A browser page
cannot hold that private key safely. Therefore:

* the **static site** can only show *snapshots* and *public, unauthenticated* market data views;
* **live trading, live alerts and the simulated portfolio** run in the Python app (`app/**`),
  which runs on a trusted machine and holds the key in an environment variable.

Full verification notes live in `data/verification.json` (generated, with a link per fact).
