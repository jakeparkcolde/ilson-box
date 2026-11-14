# L0 catalog contract — schema 1, box-l0-v1

Stage B consumes only `web/current/opensource-catalog.json` from the trusted installed
Box distribution. It never fetches, updates or writes a catalog. The distributed
catalog is deliberately empty. Candidate research is not publication approval.

## Envelope

Required exact keys: `schema_version` (integer 1), monotonically increasing
`catalog_version` (positive safe integer), `generated_at` and `valid_until`
(UTC `YYYY-MM-DDTHH:MM:SSZ`, at most 72 hours apart), `policy_version`
(`box-l0-v1`), `revocation_version` (nonnegative safe integer),
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
  `full_name` = owner/name, `category` = automation/documents/data/design/sites,
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
  URL must be the repo's `/blob/<source.commit>/LICENSE`. Nonstandard licence
  filenames need a separately reviewed contract extension; they are hidden now.
- `gitbap_url`: exactly `https://www.gitbap.com/r/<full_name>`;
  `official_url`: exactly `https://github.com/<full_name>`. No arbitrary links,
  query strings, fragments, credentials, media URLs or local paths.
- `source`: exact `summary_id`, `summary_revision` (positive integer or null),
  `lang:ko`, `readme_hash`, `summary_readme_hash` (equal 64 hex), `model`,
  `summary_created_at`, `synced_at`, `status_checked_at`, `commit` (40 hex).
  Dates remain distinct. Source status must be less than 72 hours old.
- `review`: exact `hidden:false`, `review_status:approved`,
  `metadata_verdict:ok`, `content_scan:ok`, `policy:approved`, `rights:approved`,
  `maintenance:active`, `archived:false`, `prohibited:false`,
  `requirements_confirmed:true`, `key_required:false`, `paid_api_required:false`,
  `reviewed_at`, `valid_until` (at most 7 days after review), `target_commit`
  (equals source commit), `policy_version:box-l0-v1`, `past_safety_pass`,
  `past_alive_pass` (boolean or null), `past_evaluated_at` (UTC or null),
  `metadata_checked_at` (less than 72 hours old). Current checks/review dates
  cannot follow envelope generation. Historical passes grant no permissions.
- `catalog_approved:true`, `runnable:false` are independent mandatory gates.
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
- Expiry closes all bodies, samples and external links. Individual review/source
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
