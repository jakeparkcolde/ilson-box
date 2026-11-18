# L0 catalog contract — schema 2, box-l0-bundle-30d-v2

Stage B consumes only `web/current/opensource-catalog.json` from the trusted installed
Box distribution. It never fetches, updates or writes a catalog. The bundled review candidate contains 12 reference introductions. Preparing
this candidate does not complete lead/AGY review or authorize release.

## Envelope

Required exact keys: `schema_version` (integer 2), monotonically increasing
`catalog_version` (positive safe integer), `generated_at` and `valid_until`
(UTC `YYYY-MM-DDTHH:MM:SSZ`, at most 30 × 24 hours apart), `policy_version`
(`box-l0-bundle-30d-v2`), `revocation_version` (nonnegative safe integer),
`revoked_repo_ids` (unique opaque IDs), `signature`, `source_commit` (40 lowercase
hex), `repos` (at most 500). Maximum file size: 1 MiB. Duplicate JSON keys,
nonfinite numbers, duplicate repo identities and unknown envelope keys fail
validation. No future generation dates. All flags require the exact boolean
type, never truthiness or a default approval.

Stage B's exact signature marker is
`{"kind":"bundled","key_id":null,"value":null}`. This is **distribution trust,
not cryptographic signature verification**. `verify_trusted_bundle` is the
explicit Stage C hook; remote/unknown signatures fail closed. No remote updater
or network fallback exists. Stage C must replace this boundary with verified
signatures, trusted key management, atomic file replacement and durable version/
revocation state before accepting remote data.

## Repo object

All keys are required, including nullable values. Unknown, missing or invalid
fields hide the entire row from list/detail/links. No raw source object is
returned until it passes every gate. A complete synthetic example is maintained
in `tests/opensource_fixtures.py`; it is not shipped as catalog content.

- Identity: `id` = stable opaque 32 lowercase hex, `github_id` = positive integer,
  `full_name` = owner/name, `category` = build/design/grow/make/run,
  `curated_order` = integer 0–10000 (ascending, ties use opaque ID). IDs must stay
  stable between exports so revocations remain meaningful.
- Korean prose: `one_liner`, `mild_md`, `use_cases` (array), `prerequisites`
  (array), nonempty `limitations` (array), `preparation`, `cost`,
  `data_processing`. Empty use cases display “대상 확인 중”. `mild_md` is displayed
  as plain text, with no markdown/HTML execution, command copying or link parsing.
- `difficulty`: integer 1–5 or null; `box_burden`: browse/guided/expert/unknown.
  This burden concerns browsing/preparation, never execution permission.
- `license`: exact `spdx`, Korean `conditions`, `url`, `reviewed:true`. SPDX must
  be in the consumer's reviewed subset; changes need policy review. The original
  URL must be the repo's `/blob/<source.commit>/LICENSE`. Only the manual-reference exception below permits a different licence file.
- `gitbap_url`: exactly `https://www.gitbap.com/r/<full_name>` (null only for
  manual-reference not_curated entries, avoiding a fictitious summary link);
  `official_url`: exactly `https://github.com/<full_name>`. No arbitrary links,
  query strings, fragments, credentials, media URLs or local paths.
- `source`: exact `summary_id`, `summary_revision` (positive integer or null),
  `lang:ko`, `readme_hash`, `summary_readme_hash` (equal 64 hex), `model`,
  `summary_created_at`, `synced_at`, `status_checked_at`, `commit` (40 hex), `copy_origin`.
  Dates remain distinct. Source status must be less than 72 hours old at envelope generation.
- `review`: exact `hidden:false`, `review_status:approved`,
  `metadata_verdict:ok`, `metadata_warning:null`, `content_scan:ok`, `policy:approved`, `rights:approved`,
  `maintenance:active`, `archived:false`, `disabled:false`, `prohibited:false`,
  `requirements_confirmed:true`, `key_required:false`, `paid_api_required:false`,
  `reviewed_at`, `valid_until` (at most 30 days after review), `target_commit`
  (equals source commit), `policy_version:box-l0-bundle-30d-v2`, `past_safety_pass`,
  `past_alive_pass` (boolean or null), `past_evaluated_at` (UTC or null),
  `metadata_checked_at` (less than 72 hours old at generation). Current checks/review dates
  cannot follow envelope generation. Historical passes grant no permissions.
- `catalog_approved:true`, `runnable:false` are independent mandatory gates.
- `approval_path`: gitbap-reviewed (original metadata/hash gates, copy_origin=gitbap)
  or reference-manual-20261115 (the narrowly scoped exception below).
- `preview`: null or exact `approved:true`, Korean `input`, `result`,
  `placement`, `source`. No generated substitute when missing.
- `video`: null or exact `public_approved` (boolean), `lang`, `made_at`,
  `duration_s` (integer 1–7200), `gitbap_url`, Korean `approval_basis`,
  `valid_until`. Only an approved, unexpired Korean video is advertised, via the
  same GitBap page. A ready flag, file path or another language cannot qualify.

Prose has bounded lengths and excludes HTML, script/command patterns, private
paths and recognized secret formats. Known Box secrets are additionally checked
with the existing redactor; a changed row is hidden. This is not a replacement
for the human source/content/rights/cost review. Export must never contain raw
README, private or paid content, command text, credentials or user documents.

## Failure, expiry and revocation

- Valid newer empty catalogs replace previous content with the empty state.
- Corrupt, oversized, missing, unreadable or older catalogs retain the process's
  last validated copy **only until its original validity ends**. Same-version
  content changes are rejected; they require a new catalog version.
- Expiry closes all bodies, samples and external links. Individual review
  expiry hides the row. API supplies `visible_until` so the browser can close
  content at the earliest relevant deadline, even with a stalled refresh.
- Verification failure closes everything and remains closed through subsequent
  load failures until an acceptable trusted bundle is validated again.
- Valid envelope tombstones with a nondecreasing revocation version apply before
  rejecting an older catalog body. Tombstones accumulate for the server process
  and cannot be removed by rollback or a later empty revocation list.
- Stage B has no persistent update state: process restart with a replaced older
  installed distribution cannot guarantee rollback resistance. No updater is
  enabled here. Stage C must persist version floors and cumulative tombstones.
- Offline devices cannot learn unseen revocations; expiration limits that delay.
  After expiry, install a manually reviewed new distribution/catalog.

The existing session, licence, Host/Origin and runtime-update lock guards remain
in force. Company owner checks run on both reads. No workspace/AI/tool/installer
is initialized by these endpoints. Existing authentication/config reads and the
shared runtime lock are infrastructure; the only content read is the fixed
catalog. The file lives under web/current so the existing installer and update
allow-list include it, but is not registered as a public static asset.


## Reference-only manual approval (lead decision 2026-11-15)

The BRIEF manual path is restricted by the consumer's REFERENCE_REPOS allowlist
of 23 full names and GitHub numeric identities. Round 2 adds ten reviewed
repo-level introductions, including the vercel-labs/skills and
emilkowalski/skills collections; find-skills and emil-design-eng are examples
inside those collections, not independent repository cards. Round 3 (2026-11-19)
adds yihui-dev/awesome-opus5-5-videos as a repo-level example-and-prompt list
introduction, stating that MIT covers the list only while each video and prompt
belongs to its linked creator. The cards do not
claim these repositories were the carousel author's exact choices.
JuliusBrussee/caveman remains excluded while its skill/proxy scope needs review.
AI skills/plugins change the host agent's behavior; their descriptions explain
real requirements, external processing and costs and recommend a practice folder.
Categories are 만들고 점검하기 /
디자인 / 찾고 알리기 / 콘텐츠 만들기 / 운영·연결; empty categories remain available.
The bundled opaque IDs are the first 32 hex of SHA-256 of github:<numeric-id>.
Official identity, pinned README and licence text are reviewed; ambiguous names
and commercial services are not replaced with similarly named repositories or
SDKs. Remotion's company-use restrictions make it source-available rather than
an OSS entry in this list.

This path preserves actual metadata_verdict as ok/review/caution/not_curated.
Caution requires a nonempty Korean metadata_warning, displayed as “주의” on both
list and detail. Every non-ok card shows “깃밥 점검 전 · 소개만”; detail also shows
the exact verdict and check date. The check is a metadata heuristic, not a code
security scan. Unknown verdicts still fail closed.

Only FFmpeg/FFmpeg may use the pinned LICENSE.md URL and LGPL-2.1-or-later;
only python/cpython may use PSF-2.0. Both are explicit per-repo licence extensions.
FFmpeg conditions warn that optional components change its licence and can
prevent redistribution. CPython and Node.js have third-party notices as well
as their main PSF/MIT grants. API NOASSERTION results remain in source evidence;
they are not misrepresented as API MIT/PSF results.

Manual source.copy_origin is official-readme or gitbap-adapted. Existing Korean
GitBap introductions inform the latter, then copy is checked against the pinned
README and edited. summary_id, summary_revision, model and summary_readme_hash
must be null because MCP supplies no revision/model/upstream hash binding. The
actual pinned readme_hash remains required. summary_created_at is the editorial
copy date, not an invented GitBap date. content_scan:ok here records a Box content
policy review of introductory copy and README, not a full code security scan or
execution. Unavailable historical gate values stay null.

Only descriptions and fixed links are permitted: preview:null, video:null and
runnable:false. key_required/paid_api_required refer to L0 browsing, which asks
for neither keys nor payment. Text separately explains real account/API/model/
hardware requirements and possible costs. Difficulty is our introductory review
assessment, distinguished from execution burden. Execution still needs separate
approval and the original gates. catalog_approved marks the submitted editorial
candidate; lead/AGY review and Jake release approval remain required.

## Thirty-day bundled publication (CATALOG-CONTRACT §10 option 1)

Jake's approved maximum is exactly 30 × 24 hours UTC from the actual review.
The pre-export source/metadata check window remains 72 hours. After shipping,
this is a pinned introduction, not a claim of continuously fresh upstream status.
The producer sets envelope expiry to the minimum of generation+30 days and every
review/rights deadline. Review dates cannot follow generation, and each row's
expiry cannot exceed review+30 days. API/browser use the earliest visible review
or envelope deadline. Installation, reopening and re-export do not restart it.
UI dates use KST. Long timers are capped at the signed 32-bit browser timer limit
and re-armed, avoiding overflow before a 30-day deadline.

The cumulative revoked_repo_ids/revocation_version snapshot shares the bundle's
publication deadline; no separate 72-hour online revocation document is present
in this implementation. It does not prove that no new revocations exist. No
remote endpoint/import/job/key service or automatic renewal is introduced.
New monthly reviews and emergency revocations require a newly reviewed app
bundle through the existing approved update path. An unupdated/offline device
can miss new problems for the remaining lifetime, at most 30 days.

Old schema 1 / box-l0-v1 fail closed: the new schema/policy makes the changed
source/publication and revocation semantics explicit. Existing in-process
version floors and cumulative tombstones remain; an expired snapshot cannot
erase a tombstone. Clock values before generation fail closed. Persistent
rollback resistance across a restart with an older distribution remains a
future Stage C requirement; no remote updater is enabled here.
