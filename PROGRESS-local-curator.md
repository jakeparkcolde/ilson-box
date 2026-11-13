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

Main integration (2026-11-14): lead approved continuing on main 67a5a67 and changed the final AGY diff base to **67a5a67..HEAD**. Rebased all feature commits on main; only generated payload/bootstrap assignments conflicted and were resolved by regenerating from merged canonical sources. Windows/Intel stdin transport and diagnostics exception preservation remain intact; no environment payload transport remains.

Added exact 67a5a67 diagnostics bytes to known-source upgrade hashes and a regression for upgrade/rollback from that baseline. Updated the newly merged large-stream test to seed only files actually present in its old release and compare helper code separately from the new persistent OS lock file. Focused merged tests: transport5 OK (skip1), updater10 OK. Verified all 9 payload files, both bootstrap copies, synced curator sources, stdin boot strings, single generated markers, bash syntax and diff whitespace. Final payload 59,648 base64 characters, carried through stdin. Actual Windows execution remains unrun here.

Final regression starting in owned hc program `local-curator-final-suite`; log `.scratch/final-regression.log`. No code changes while it runs.

Lead follow-up: a private absolute path in main's Windows-fix documentation requires a further main docs commit. Stopped owned final-suite t340 promptly (HUP, interrupted at about one minute; no complete result), verified its process group is gone, removed the terminal. Partial log preserved as `.scratch/interrupted-pre-doc-fix-regression.log`; no test failure/pass count claimed. Await new main notice, rebase, then run the final suite once. New feature docs/README/course guide/progress contain no personal absolute paths or tailnet hostnames; external handoff/review notes use home-relative project paths as well.

## Final validation and close-out — 2026-11-14

- Rebased on sanitized main **9321b35** with no conflicts. Tested implementation HEAD **a95cb2f**; only this final progress record is committed afterward, with no code/payload changes.
- Final full suite, run once after the new-main notice: `python3 -m unittest discover -s tests -v < /dev/null` — **922 tests in 352.543s, OK (skipped=39), exit 0**. Log: `.scratch/final-regression.log`.
- Focused coverage: curator23, course update10, legacy payload5, stream transport5(skip1), scheduled jobs48, course learn7, installer24(skip4), diagnostics17. Full suite contains all these groups. Both curator sources are identical; both 9-file payloads and bootstrap blocks match sources. Bash syntax / compile / whitespace checks passed. No jobs.conf/launchd changes.
- Not executed: actual Windows/PowerShell 5.1 curator/update/Win32/ACL behavior, real Intel installs, real launchd 23:00/sleep/reboot, real user licensing/AI/network/production. Course update first use requires a reviewed immutable pin; no new feed/installer/version has been published.
- AGY review package prepared externally under the lead's `agy-impl2-review/`: final BRIEF plus **9321b35..HEAD** target.diff. No AGY launched; lead reviews/merges later. No main checkout, push, Release or mini changes.
- Close-out: owned regression terminals t33w (completed pre-integration), t340 (interrupted per lead), t342 (final exit0) all inspected and removed. Final owned process group verified gone. No task browser/preview server or running test process retained. No media outputs to archive; source files preserved. No manual deletions pending.
