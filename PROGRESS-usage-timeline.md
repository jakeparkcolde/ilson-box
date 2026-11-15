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

- Final review added seen_at metadata and a regression test so replayed old stream chunks cannot rewind final token counters. Equal-timestamp conflicting usage becomes partial/null instead of guessed numbers. Schema migration adds metadata only. Privacy controls now wait up to 3s for an existing bounded collection lock, so one off action succeeds after the short tick. Related suite 24 tests pass.
- t3mn final-suite attempt was deliberately stopped after the replay fix was identified (partial output retained as /tmp/ilson-usage-final-tests-interrupted.log); it is not a passing test result. A fresh full suite follows the committed final code.

- Native-compatibility review: Python official zoneinfo documentation confirms Windows often lacks system IANA data. Added stdlib UTC/Asia-Seoul fallbacks (retained modern dates only, Korea UTC+9) and a no-tzdata simulation regression; other missing zones fail explicitly. Related suite 25 tests pass. No new dependency/install. Source https://docs.python.org/3/library/zoneinfo.html read through Aside and tab closed.
- t3mp suite attempt stopped for that real Windows compatibility fix; partial log retained /tmp/ilson-usage-final-tests-before-timezone.log. Full final suite will rerun after this commit. No passing result claimed for interrupted runs.
- Close-out: own synthetic preview t3m8/PID77322 terminated with SIGTERM after start/cwd/port/descendant verification; PID exited and port62157 released; HC terminal removed. No Tailscale route created, none changed. Restart python3 /tmp/ilson-usage-preview.py (new synthetic directory/port). Own Aside tabs closed; no active preview/browser remains. No archive-eligible completed content media produced (only code and synthetic QA evidence).

## Final verification / delivery — 2026-11-15 KST

- Final code SHA 82410b39c55e2679879320a84ca53841304a2e78. Exact full suite `python3 -m unittest discover -s tests </dev/null`: **1012 tests / 370.636s / OK (skipped=40)**, exit0 (hc t3mt). Output preserved in lead handoff `agy-impl1-review/test-output.txt`. Related25 and course61 results above are supplemented by this final full run.
- Python/JS/shell syntax and git diff whitespace checks pass. Main remains clean at f95c0e0; feature worktree clean before this final notes commit. No push/release/merge/production/DB/Mac mini changes or AGY execution.
- Guides: docs/내-AI-사용-기록-보는-법.md and docs/강사용-수강생-AI-사용-기록-보는-법.md; student steps distinguish full Mac vs Intel/Windows CLI, with screenshot slots. Course native OS install/ACL and actual deployed-site sync/retention remain unexecuted release checks. Codex remains 준비 중.
- AGY review bundle lives in lead handoff `agy-impl1-review/`: BRIEF, target.diff f95c0e0..final HEAD, final/initial test outputs, validation notes and synthetic browser screenshots. Independent AGY verdict and local-main merge belong to the lead.
- Close-out 2026-11-15: all own Aside tabs closed; synthetic preview PID77322/port62157 SIGTERM+exit+port release verified, terminal removed; all task test HC terminals (including final t3mt after exit0/log preservation) removed. No Tailscale route created/changed, no active task preview/browser retained. Restart `python3 /tmp/ilson-usage-preview.py` creates a new temporary synthetic home/port. No archive-eligible completed media produced; code/QA evidence preserved.
