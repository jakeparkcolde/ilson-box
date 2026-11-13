# Local curator implementation progress

2026-11-14 · worker implementation, lead t2v5 · branch feat/local-curator-20261114 · baseline e9e41a3.

Authorized: implement Bundle ② in this worktree only; AGY review is later. No push, Release, main-checkout edits, real installs, external AI calls, or production changes. Scratch files stay in `.scratch/`. No workers/review agents launched.

Read: IMPL-BRIEF-2, DESIGN A1–A6 / steps 5–7 / D1–D10, AGY review 6-4, MULTI-ACCOUNT-REVIEW B/D6. Machine verified Mac17,14 (Studio).

Plan:
1. Local curator, safe consent/license/path boundaries, atomic new notes, acceptance tests; commit.
2. Full watchdog and both CLI integrations, course manual-only behavior, docs; commit.
3. Course pinned updates/rollback and suggested-rules refresh, payload/hash regeneration; commit.
4. Full regression, review artifacts in Studio_base/agy-impl2-review, final Korean hc report.

Not yet verified: implementation, tests, Windows runtime. No servers/browsers started.

Stage 1: added synchronized stdlib-only curator sources and 20 isolated acceptance tests. Tests passed (`.scratch/curator-tests.log`): original bytes/mtime, default OFF/no enumeration, allowlist and links/hardlinks/reparse rejection, per-vault lock, addendum, limits/partial failures, atomic no-clobber publication/retry, revocation, local license cache, Korean paths, due/catch-up/clock checks. No network/AI execution path. Private `.staging` under the output filesystem permits atomic publication for external-volume vaults; it is always excluded from inputs.
