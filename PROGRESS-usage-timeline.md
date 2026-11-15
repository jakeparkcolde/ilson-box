# Usage timeline progress

2026-11-15 KST · owner lead t2v5 · writer t3kv · gpt-6.1-sol / xhigh (hc argv verified).
Worktree ~/orca/workspaces/ilson-box/usage-timeline, branch feat/usage-timeline-20261115, base f95c0e0. Studio Mac17,14. Main checkout untouched.

- Read BRIEF/DESIGN/REVIEW/EVIDENCE and reference image; DESIGN-v2 and SYNC-CONTRACT written in handoff folder and docs/usage-timeline.
- Authorized: local implementation/tests/commits; forbidden: push/release/Mac mini/production/server changes/AGY launch/chmod/rm/sudo/chown.
- Additional lead request: student and instructor how-to guides with screenshot slots.
- Running task services/browser tabs: none. Pricing/QA browser work will use Aside, no Chrome.
- Verification pending. Next: collector, CLI, fake sync server tests, web, course packaging, docs, full suite, AGY bundle.

- Collector/ledger + CLI + opt-in sync client implemented. Synthetic suite: 15 tests pass (2026-11-15). Covered stream dedupe, midnight/timezone/DST, OFF/gaps, partial/truncated logs, path scope/link rejection, payload field/model mutation properties, CLI/course CLI, fake HTTP link/upload/backoff/revoke. Course packaging changes not yet regenerated/committed.
- Official Anthropic pricing inspected through Aside REPL (tab opened and closed in same task): https://platform.claude.com/docs/en/about-claude/pricing, checked 2026-11-15. Cache write TTL absent → cost min/max for 5m/1h, never billing amount.
- No running browser tab or preview service. Next: web API/UI and course installer payloads/docs, full suite.

- Web API/UI added: standalone /usage-history privacy controls bypass network license evaluation; session/origin/owner checks retained, ordinary admin gate unchanged. Related suite 19 tests green. Student guide and instructor draft added with screenshot slots, first-day optional checklist added.
- Temporary verification services started: hc t3m7 box-usage-tests (full suite, /tmp/ilson-usage-full-tests.log); hc t3m8 box-usage-preview, Python PID 77322, worktree cwd, port 62157, synthetic-only temporary home. No production data or credentials. Preview restart: python3 /tmp/ilson-usage-preview.py (new temporary home/port each start). Must close at verification end.

- Browser QA completed via Aside with synthetic 272-day / 1218-turn ledger: light/dark and Claude tab metrics rendered; ArrowRight moved Jan 1 → Jan 8 with aria label; mobile viewport/body both 390px (no document overflow). Own Aside tabs closed. Screenshots /tmp/ilson-usage-light.png, dark.png, mobile.png inspected. Snapshots /tmp/ilson-usage-browser-qa.txt (contains base64 screenshots, do not print whole file).
- Course suite 61 tests pass / 8 platform skips; hc t3md read and removed. Related suite now 20 tests pass, including new-folder consent isolation. Initial full suite remains running; known 2 legacy fixture errors already corrected in working tree, final rerun pending.

- Initial full suite: 1006 tests / 378.976s / 40 skips, failed 3 errors + 1 privacy failure. Fixed: historical course fixtures now explicitly omit not-yet-existing new modules; repository notes use home-relative paths; existing exact CLI baseline hash (26bf963 / 3d53bdb bytes) pinned in manager-baseline because our CLI commit displaced it from the builder's latest-20 history window. No broad update acceptance relaxation.
- Added scan fairness (unread/changed files before exhausted cursors) and tests for >256 files, unchanged incremental reads, real temporary snapshot exclusion and refusal of pretracked usage state. Related suite 22 tests pass.
