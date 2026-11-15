# HANDOFF impl1 — 2026-11-15 KST

Objective: lead t2v5 worker t3kv implements usage timeline in isolated worktree; main untouched. Launch verified gpt-6.1-sol / xhigh. Studio Mac17,14. Follow IMPL-BRIEF-1-BOX.md, BRIEF Go, DESIGN-v2 and SYNC-CONTRACT.

Authorization: local worktree code/tests/commits only. No push/release/merge/production/server changes/Mac mini/AGY launch/chmod/rm/sudo/chown. Report Korean via hc send t2v5. No child agents assigned. Lead extra: student how-to + instructor draft in docs with screenshot slots. Pricing manifest shared with server worker.

Paths: worktree ~/orca/workspaces/ilson-box/usage-timeline; branch feat/usage-timeline-20261115, base f95c0e0. Handoff folder as this file. DESIGN-v2/SYNC-CONTRACT/PRICING-MANIFEST mirrored in docs/usage-timeline and handoff. Price source official Anthropic docs read through Aside, checked 2026-11-15, anthropic-20261115, cache TTL unknown min/max 5m/1h range.

Completed: design/contract commit a73e5d5; collector/CLI/sync/tests commit b074765. Uncommitted web owner/session/origin API, standalone /usage-history offline license controls, year heatmap light/dark keyboard/tabs, course collectors/modules/allowlists regenerated embedded installers, student/instructor docs/README/day1 checklist, 2 historical fixture adaptations for new course modules. Codex intentionally preparation only. SQL server handled by another worker from contract. Collection and sharing separately OFF. Local state/usage-timeline 0700/0600 and snapshot exclusion, HMAC source/session/message IDs, selected scope cwd check, metadata-only ledger, explicit optional backfill, 366-day retention. JSON field/model strict allowlist. Unknown format partial. Off stops new collection+upload. Unlink disables uploads and requests revoke+delete with offline pending credential retained only for deletion. HTTPS config base URL default absent; loopback HTTP for fake tests.

Validation: related 20 tests passed most recently (collector+fake HTTP+web API). Course suite 61 tests passed, 8 skipped (pwsh unavailable). Full suite currently running, first run started before 2 historical fixture fixes and will fail those 2; final full rerun still REQUIRED. Full command stdin /dev/null. Python3.9 source interpreter once failed UTF8 detection for huge design script; compile Unicode source corrected, files now saved/verified. Do not claim native Intel/Windows installs or production sync verified.

Processes: hc t3m7 box-usage-tests command full suite -> /tmp/ilson-usage-full-tests.log, shell PID 77313; inspect/wait using hc, no polling sleeps. hc t3m8 box-usage-preview Python PID 77322, started Nov15 09:31:48, cwd worktree, LISTEN 127.0.0.1:62157, synthetic temporary home /private/var/folders/fj/dg8_lcwj31z46p9hj060t2zc0000gp/T/ilson-usage-preview-xkjkl6w8/user/box. Ownership verified ps+lsof. Restart python3 /tmp/ilson-usage-preview.py creates NEW temp home+port; no Tailscale route created. Stop preview and verify PID/port release before done. HC course-tests t3md already completed/read/removed. No agents spawned.

Browser: Aside only, own tabs opened and closed within one-shot calls. Screenshot API filesystem paths are in browser sandbox and not directly visible; use screenshot() Buffer as base64 redirected to file and decode, never print image payload into model. Current QA exec shell session 6102 may still run; /tmp/ilson-usage-browser-qa.txt includes snapshots + base64; /tmp/ilson-usage-dark.png and mobile.png are decoded. Light screenshot /tmp/ilson-usage-light.png inspected. Need inspect dark/mobile+keyboard WIDTH lines and ensure tabs closed if QA errors. /tmp/ilson-usage-preview-info.json contains synthetic preview location/port, no real credentials. /tmp/ilson-usage-pricing.txt holds primary price snapshot. No actual user logs read by this worker; fixtures synthetic only, prior EVIDENCE schema used.

Next actions:
1. Finish browser QA: inspect dark/mobile screenshot, keyboard arrow focus result and body width, fix concrete UI issues. If guide captures needed keep synthetic screenshots in review bundle (source tracked screenshots not archive).
2. Test safety holes: source switch own consent window test added; broad suite still running. Check no snapshot leak using real temp Box snapshot test if needed. Validate source scan bound/fairness, credential lifetime/off state, JSON export no extra fields. Avoid unrequested scope.
3. Wait initial full suite, inspect errors, run final full suite after fixes with stdin /dev/null (HC terminal), preserve output. Run syntax/diff check.
4. Commit web stage, course stage, docs stage with CODEX_REVIEW_OFF=1. Update PROGRESS. Worktree sole writer. No main merge by worker.
5. AGY review bundle handoff agy-impl1-review/: BRIEF.md, target.diff f95c0e0..HEAD, full test output+validation limits; do not launch AGY. Report completed commits/tests/docs to hc send t2v5.
6. Close own Aside tabs, synthetic preview PID+port and completed HC test terminals after evidence saved; record closeout/restart. No completed media outputs to archive (code/task review screenshots only).

Current HEAD: b074765129ae8e48c68b82469a9cf4cf001257b5

Git status at checkpoint:
```
 M .gitignore
 M PROGRESS-usage-timeline.md
 M README.md
 M "course/00_\352\260\225\354\235\230_\354\213\234\354\236\221.md"
 M course/ilson.py
 M course/install-intel-mac.sh
 M course/install-windows.ps1
 M course/install_payload.py
 M course/pack_course.py
 M "docs/\354\202\254\354\232\251\353\262\225.md"
 M template/lib/usage_timeline.py
 M template/lib/web-admin-server.py
 M template/web/current/index.html
 M template/web/dashboard.js
 M tests/test_course_payload_transport.py
 M tests/test_course_update.py
 M tests/test_usage_timeline.py
?? course/lib/usage_sync.py
?? course/lib/usage_timeline.py
?? docs/usage-timeline/PRICING-MANIFEST.json
?? "docs/\352\260\225\354\202\254\354\232\251-\354\210\230\352\260\225\354\203\235-AI-\354\202\254\354\232\251-\352\270\260\353\241\235-\353\263\264\353\212\224-\353\262\225.md"
?? "docs/\353\202\264-AI-\354\202\254\354\232\251-\352\270\260\353\241\235-\353\263\264\353\212\224-\353\262\225.md"
?? template/web/usage-history.css
?? template/web/usage-history.html
?? template/web/usage-history.js
?? tests/test_usage_timeline_web.py
```

Continuation prompt: Read HANDOFF-impl1.md and IMPL-BRIEF-1-BOX.md in ~/orca/projects/Studio_base/handoffs/work/2026-11-15-ilson-box-usage-timeline. Continue as t2v5 worker in ~/orca/workspaces/ilson-box/usage-timeline only. Finish browser QA, final full suite, commits, AGY bundle, and own service cleanup; report Korean with hc send t2v5. Do not edit main/push/release/Mac mini/production or launch AGY.
