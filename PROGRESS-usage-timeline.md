# Usage timeline progress

2026-11-15 KST · owner lead t2v5 · writer t3kv · gpt-6.1-sol / xhigh (hc argv verified).
Worktree /Users/koldeumaegmini/orca/workspaces/ilson-box/usage-timeline, branch feat/usage-timeline-20261115, base f95c0e0. Studio Mac17,14. Main checkout untouched.

- Read BRIEF/DESIGN/REVIEW/EVIDENCE and reference image; DESIGN-v2 and SYNC-CONTRACT written in handoff folder and docs/usage-timeline.
- Authorized: local implementation/tests/commits; forbidden: push/release/Mac mini/production/server changes/AGY launch/chmod/rm/sudo/chown.
- Additional lead request: student and instructor how-to guides with screenshot slots.
- Running task services/browser tabs: none. Pricing/QA browser work will use Aside, no Chrome.
- Verification pending. Next: collector, CLI, fake sync server tests, web, course packaging, docs, full suite, AGY bundle.

- Collector/ledger + CLI + opt-in sync client implemented. Synthetic suite: 15 tests pass (2026-11-15). Covered stream dedupe, midnight/timezone/DST, OFF/gaps, partial/truncated logs, path scope/link rejection, payload field/model mutation properties, CLI/course CLI, fake HTTP link/upload/backoff/revoke. Course packaging changes not yet regenerated/committed.
- Official Anthropic pricing inspected through Aside REPL (tab opened and closed in same task): https://platform.claude.com/docs/en/about-claude/pricing, checked 2026-11-15. Cache write TTL absent → cost min/max for 5m/1h, never billing amount.
- No running browser tab or preview service. Next: web API/UI and course installer payloads/docs, full suite.
