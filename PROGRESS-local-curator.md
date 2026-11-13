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

Stage 1: added synchronized stdlib-only curator sources and 19 isolated acceptance tests. Tests passed (`.scratch/curator-tests.log`): original bytes/mtime, default OFF/no enumeration, allowlist and links/hardlinks/reparse rejection, per-vault lock, addendum, limits/partial failures, atomic no-clobber publication/retry, revocation, local license cache, Korean paths, due/catch-up/clock checks. No network/AI execution path. Private `.staging` under the output filesystem permits atomic publication for external-volume vaults; it is always excluded from inputs.

Lead steering (2026-11-14): independent fix/windows-payload-20261114 worker owns payload transfer changes in both installers after Windows environment-variable size failure (42,088 chars). Do not edit transfer sections. Await merge notice, then rebase main and regenerate final payload. Curator and course update helper will further increase embedded size. Installer suggested-rules logic remains in this scope.

Stage 2: full CLI curator/diary bypass the network-capable generic license gate, and the existing watchdog spawns a silent offline tick without blocking its checks. No jobs.conf or launchd registration added. Status distinguishes consent, auto setting, actual launchctl registration, old watchdog compatibility, and clock-review state. Full docs/tidy guidance explain boundaries. Added remote-Markdown escaping, UNC/remote Windows drive rejection, and a nonblocking-watchdog test. Curator acceptance now 21 passing tests; initial hc progress count of 20 was a counting error (the initial file had 19).

Stage 3: course curator/diary manual-only dispatch, pinned `ilson update` + `--rollback`, strict installer SHA-256/revision/edition validation, bounded payload extraction, known-source all-or-nothing upgrades, OS upgrade lock, self-check with automatic recovery, applied/failed/rolled-back backup status, and a local pin builder. The update reads the pinned official installer as a data container; it does not execute installer shell/PowerShell or modify apps/wrappers/Python selection/PATH/vaults. No remote feed has been published: first use requires a lead-supplied pin; saved pins stay immutable until a new pin is provided. Intel suggested-rules refresh backs up different old bytes with a dated exclusive name, refreshes atomically, preserves the actual vault CLAUDE.md, and is idempotent.

Validation so far: curator 23 tests (including killed owner/partial-publication retry), course update 8 tests, legacy payload upgrade 5 tests, existing scheduled-jobs 48 tests passed. Windows-specific Win32 path/parent pinning and reparse/remote-drive rejection are implemented but NOT executed on real Windows. Both curator source copies remain byte-identical. Packaging/full suite are still pending the separately owned Windows payload fix.

Pre-integration packaging checkpoint: payload regenerated (about 59.3k base64 chars, so it still requires the separately owned Windows file-transfer fix). All 9 helper files and both embedded bootstrap blocks match source bytes. No installer transfer logic changed. Package regression caught a stricter-safe-path regression for Apple's relative `/var -> private/var` system alias; restored only the three exact known OS aliases while retaining user symlink/reparse/hardlink rejection. Course learning 7 tests now pass; installer tests 24 pass (4 skipped); Windows static tests 3 pass (3 skipped). Course update 9 tests pass, including rollback I/O failure recovery. Final full-suite run follows; another packaging pass is required after main integration.

Full pre-integration regression (HEAD 01e255d): `python3 -m unittest discover -s tests -v < /dev/null` ran 915 tests in 371.755s, with exactly 1 ERROR and 38 skips. Error was a test source-layout assumption: newly packaged `install_payload.py` is canonically under `course/`, not `course/lib/`. Corrected only that source mapping in `tests/test_install_diagnostics.py`; diagnostics group rerun in progress. Log retained `.scratch/full-regression.log`. Owned full-suite hc terminal t33w exited (1), result inspected, removed with hc rm. No owned preview/browser/server remains.

Lead boundary while Windows 67a5a67 is under AGY review: no further implementation before PASS/main merge; finish only the running test and source-path mapping fix, then await the lead's merge notice.
