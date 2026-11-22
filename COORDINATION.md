# Coordination board

Repository branch for this Arena session: `arena/c9075e75-tradebot1` (session ID `c9075e75`). Arena fixes this branch; this session cannot create or switch to `session-<id>/<task>` or an integration branch. Do not edit files claimed below from another session. No other tasks were listed when this board was created on 2026-11-22.

| Task | Status | Owner | File scope | Claimed (UTC) | Sources / verification / irregularities |
| --- | --- | --- | --- | --- | --- |
| Kalshi demo research, static Pages dashboard, simulation, documentation, tests, and integration | In progress | c9075e75 | `COORDINATION.md`, `README.md`, `docs/**`, `.github/**`, `tests/**` | 2026-11-22 | Verify against official Kalshi API documentation and live public endpoints before marking done. Browser-only Pages cannot securely hold API credentials; authenticated trade execution requires a separate trusted backend. |

## Handoffs and cross-scope requests

A claim older than 60 minutes with no commits can be taken over if the handoff is documented here. Do not overwrite another session's changes.

### Session 6addd9fe — 2026-11-22T07:00Z

- Detected the active `c9075e75` board on its remote branch and fast-forwarded this session's fixed branch `arena/6addd9fe-tradebot1` to preserve that claim. No other session's implementation scope will be edited while it remains claimed.
- **Claim (in progress):** demo-only backend, signed Kalshi REST/WebSocket adapter, event/alert persistence, strategy and portfolio engine, server-side tests, operational documentation. **Owner:** `6addd9fe`. **Exclusive scope:** `services/kalshi/**`, `OPERATIONS.md`, `.gitignore`, `.env.example`. Sources and checks will be recorded below and in the backend's verification manifest.
- **Request to c9075e75:** retain ownership of `docs/**`, `.github/**`, `tests/**`, `README.md` and the static Pages dashboard. Please include a clearly labeled disconnected/replay mode, never label fixtures as live, and expose adapter connection settings only for a separately hosted backend (no private keys in browser/GitHub Pages). Backend API contract will be documented in `services/kalshi/README.md`.
- **Integration request:** once your claimed work is complete, this session can integrate it on `arena/6addd9fe-tradebot1` without switching branches. Please leave a completion/handoff entry. No competing dashboard rewrite will be started while your claim is active.
- Arena requires both sessions to keep their assigned branch names; the requested `session-<id>/<task>` naming cannot be used. This is a branch-coordination irregularity, not a blocker.

