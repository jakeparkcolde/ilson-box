# Claude 배우기 — Fact sheet

Checked: 2026-10-20

Rules for writers: use only facts below. Each line = fact · tag · source actually fetched on 2026-10-20.
Tags: [verified] seen on the page · [inferred] implied by the page · [unverified] not confirmed.
Quotes in "double quotes" are the original English label; Korean gloss follows in ( ).
Many pages show only "Updated this week" instead of a date; where a page date was shown it is noted.
Several facts were read through a page-summarising fetch tool, so treat exact punctuation of long quotes as approximate; short UI labels were checked.

## A. Accounts and plans

### Sign-up and login
- Login/sign-up buttons on web, desktop and mobile: "Continue with Google" (구글로 계속) and "Continue with email" (이메일로 계속; a login link arrives by email, subject "Secure link to log in to Claude.ai"). [verified] — https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account
- If the email link is opened on a different device, it shows a verification code to type on the first device. [verified] — same URL
- Apple sign-in is not listed as a login method on that page (only Apple "Hide My Email" addresses used with email login). [verified] — same URL
- Phone verification is required for all new users and cannot be skipped; a six-digit code arrives by text message. [verified] (page date 2026-08-17) — https://support.claude.com/en/articles/8287232-verifying-your-phone-number
- Not accepted: VoIP numbers, Google Voice, app-generated numbers, landlines. Max three Claude accounts per phone number. The number cannot be changed after verification. [verified] — same URL
- Minimum age: "at least 18 years old to create and use a Claude account". [verified] (page date 2026-03-16) — https://support.claude.com/en/articles/13117299-minimum-age-requirement-access-restriction
- Consumer Terms: 18 or the higher local minimum age. [verified] (effective 2025-10-08) — https://www.anthropic.com/legal/consumer-terms
- "South Korea" is on the Claude.ai supported countries list. [verified] (page date 2026-03-16) — https://support.claude.com/en/articles/8461763-supported-countries
- Interface languages include "Korean" (also English, French, German, Hindi, Indonesian, Italian, Japanese, Portuguese (Brazilian), Spanish ×2). [verified] (page date 2026-08-06) — https://support.claude.com/en/articles/10769299-how-to-use-claude-in-your-preferred-language
- Change display language: profile icon (lower-left) → "Language" (언어). Claude replies in the language you write in, whatever the setting. [verified] — same URL

### Plans and prices (USD, as shown on claude.com)
- Free: $0. Includes chat on web/desktop/mobile, web search, file creation and code execution, memory, app connectors, Artifacts. Not included: Claude Code, Research, usage credits. Projects: "Up to 5". [verified] — https://claude.com/pricing
- Pro: "$17 Per month with annual subscription discount ($200 billed up front)" or "$20 if billed monthly". [verified] — https://claude.com/pricing
- Pro includes Claude Code, Research, Projects, more models, usage credits (per comparison table). [verified] — https://claude.com/pricing
- Max: card shows "From $100" "Per month", "Choose 5x or 20x more usage than Pro". Max is billed monthly only ("Both options are billed monthly"). [verified] — https://claude.com/pricing/max
- Max 5x = $100/month, Max 20x = $200/month; "These prices are for web subscriptions only." [verified] — https://support.claude.com/en/articles/11049741
- Max also lists "$100 to $200/month in API credits to build on the Claude Platform" (developer credits, not chat usage). [verified] — https://claude.com/pricing/max
- Max monthly API credits cannot be used in Claude Code or the Claude apps. [verified] — https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan
- Tax: pricing page says "Prices shown don't include applicable tax." [verified] — https://claude.com/pricing
- Pro help article: "$20 per month (US), with pricing in your local currency where supported"; "some regions include applicable taxes in the displayed price while others add tax at checkout"; current regional price: claude.ai/upgrade or the app store. [verified] — https://support.claude.com/en/articles/8325606-what-is-the-pro-plan
- App stores: "Mobile pricing may vary depending on your app platform." [verified] — https://support.claude.com/en/articles/11049741
- "Price and plans are subject to change at Anthropic's discretion." [verified] — https://claude.com/pricing
- Models by plan (comparison table): Free = Sonnet and Haiku; Pro = Opus, Sonnet, Haiku (Fable needs usage credits); Max = Opus, Sonnet, Haiku, Fable at "50% of weekly limits". [verified] — https://claude.com/pricing
- Claude Code needs a paid plan: quickstart lists Pro, Max, Team or Enterprise (or Console/cloud provider); Free does not include Claude Code. [verified] — https://code.claude.com/docs/en/quickstart.md , https://claude.com/pricing
- Upgrades take effect right away (unused time credited); downgrades take effect at the end of the billing period. [verified] — https://claude.com/pricing

### Usage limits
- "Every plan has usage limits that reset on a rolling five-hour session window, and paid plans add weekly limits on top." [verified] — https://claude.com/pricing
- Max gives "5x or 20x more usage per 5-hour session than Pro"; pricing page says Pro gives at least 5x Free's usage per session. [verified] — https://claude.com/pricing
- Usage depends on conversation length, features used, model and effort level; exact message counts are not published. [verified] — https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work
- claude.ai, Claude Code and Claude Desktop "count towards the same usage limit". [verified] — https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work
- Claude Code help: "These limits are shared across Claude and Claude Code". [verified] — https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan
- Anthropic may also limit usage "such as weekly and monthly caps or model and feature usage". [verified] — https://claude.com/pricing
- Check usage: "Settings > Usage" (설정 > 사용량). Pro/Max see progress bars: session bar (used share + time left in the 5-hour session) and weekly bar (when it resets). [verified] — https://support.claude.com/en/articles/9797557
- Max weekly limit "applies across all models" and resets at a fixed time assigned to your account. [verified] — https://support.claude.com/en/articles/11049741
- Things that use more allowance: long messages, big attachments, long conversations, Research/web search, model and effort choice, artifacts, multi-step tasks. [verified] — https://support.claude.com/en/articles/9797557
- Official tips: plan before you start, be specific and concise, batch similar requests, put core documents in a project (cached content counts less), start a new chat when a long one nears the limit, turn off web search/connectors when not needed. [verified] — https://support.claude.com/en/articles/9797557 , https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work
- When you hit a limit: "wait for it to reset, move to a higher plan, or, on paid plans, turn on usage credits". [verified] — https://claude.com/pricing
- Usage credits (사용 크레딧; older name "extra usage"): Pro, Max 5x, Max 20x; billed at standard API rates; turn on at "Settings > Usage" → "Usage credits" section → "Enable", set "Adjust limit" or "Set to unlimited", then "Add funds" → "Purchase"; optional auto-reload. [verified] — https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans
- Credits do not change reset times. App-store subscribers can enable usage credits only on the web. [verified] — same URL
- Usage credits are prepaid ("You'll then need to prepay to cover usage beyond your plan limits"). "Adjust limit" sets a monthly spend limit; "Set to unlimited" removes it. Auto-reload (optional) buys more funds when the balance drops below a threshold you set. Usage stops at the monthly spend limit, or when the balance runs out with auto-reload off. [verified 2026-10-20, added after review] — https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans
- Context length (대화 길이 한도) is separate from usage limits: newest models up to 1M tokens, others 500K or 200K; when a chat nears the limit Claude summarises earlier messages (needs code execution on). [verified] — https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work

### Cancel and refunds
- Web/desktop: initials or name (lower-left) → "Settings" → "Billing" → "Cancel". iOS/Android: initials (top-right) → "Billing" → "Manage subscription". [verified] — https://support.claude.com/en/articles/8325617-cancel-your-pro-or-max-subscription
- Cancellation takes effect at the end of the current billing period; cancel "at least 24 hours before your next billing date". [verified] — same URL
- Subscriptions bought in the iPhone/Android app are cancelled through Apple/Google if the app is deleted. [verified] — same URL
- Payments are generally non-refundable except where the Consumer Terms say otherwise; App Store refunds go through Apple. [verified] — https://claude.com/pricing
- Consumer Terms §6(4): residents of South Korea (also Brazil, Mexico, Taiwan) may withdraw within 7 days of subscribing without giving a reason; refund within 14 days to the original payment method; if the service was used during those days, a proportional amount may be deducted. [verified] — https://www.anthropic.com/legal/consumer-terms
- Paid plans auto-renew until cancelled (Consumer Terms §6). [verified] — same URL
- §6(4) how to withdraw: the easiest way is to cancel the subscription in the customer portal, or contact support@anthropic.com directly. Refund "without delay" and at the latest 14 days after Anthropic is notified, to the same payment method used for the original transaction, with no refund fee. Anthropic may deduct an amount proportional to the service provided before you notified withdrawal. (Page was served in Korean: "고객 포털을 통해 구독을 해지하는 것이며, 또는 support@anthropic.com로 직접 문의".) [verified 2026-10-20, added after review] — https://www.anthropic.com/legal/consumer-terms
- Purchases through an app distributor (e.g. an app store): you pay the distributor, and the distributor's terms, not these terms, govern payment method, billing and refunds; app subscriptions are cancelled through the distributor (§6(3)). The page does not name Apple or Google specifically. [verified 2026-10-20, added after review] — same URL
- Minimum age, Consumer Terms §2: 18 or the higher minimum age required in your region to consent to use the service. [verified 2026-10-20] — same URL

## B. Privacy and safety (Free, Pro, Max)

- Training is a user choice: chats and coding sessions are used to improve models only if you allow it ("model training setting"). Applies to Claude Code on these accounts too. [verified] — https://www.anthropic.com/news/updates-to-our-consumer-terms , https://code.claude.com/docs/en/data-usage.md
- Where: "Settings" → "Privacy" → toggle under "Help Improve our AI models" (AI 모델 개선에 도움 주기). Same steps on mobile. Direct page: claude.ai/settings/data-privacy-controls. [verified] (page date 2026-08-03) — https://privacy.claude.com/en/articles/12109829-how-do-i-change-my-model-improvement-privacy-settings
- Other Anthropic pages call the same setting "Model Improvement". [verified] (page date 2026-03-16) — https://privacy.claude.com/en/articles/10023580-is-my-data-used-for-model-training
- Turning it off: new chats and coding sessions are not used for future training; data already in a started training run or a trained model is not removed. [verified] — https://privacy.claude.com/en/articles/12109829-how-do-i-change-my-model-improvement-privacy-settings
- Retention, training allowed: up to 5 years (de-identified, in training pipelines). Training not allowed: 30 days. [verified] — https://code.claude.com/docs/en/data-usage.md , https://www.anthropic.com/news/updates-to-our-consumer-terms
- Deleted chats: removed from history immediately, deleted from back-end within 30 days; a deleted chat is not used for future training. [verified] (page date 2026-08-10) — https://support.claude.com/en/articles/8230524-delete-or-rename-a-conversation , https://www.anthropic.com/news/updates-to-our-consumer-terms
- Delete on web: hover the chat → "⋮" → "Delete" → confirm "Delete". Several: "Chats and tasks" (left sidebar) → "⋮" → "Select" → tick → "Delete". iOS: touch and hold → "Delete". [verified] — https://support.claude.com/en/articles/8230524-delete-or-rename-a-conversation
- Content flagged for usage-policy violations: inputs/outputs kept up to 2 years, safety scores up to 7 years. [verified] (page date 2026-07-01) — https://privacy.claude.com/en/articles/10023548-how-long-do-you-store-my-data
- Feedback (thumbs up/down): the whole related conversation is stored up to 5 years, de-linked from your user ID before use. [verified] — https://privacy.claude.com/en/articles/10023580-is-my-data-used-for-model-training
- Claude Code `/feedback`, `/bug`, `/share` transcripts are kept 5 years. [verified] — https://code.claude.com/docs/en/data-usage.md
- Incognito chat (시크릿 대화): all plans; on a new chat outside a project click the ghost icon (upper right); shows a black border and "Incognito chat" label. [verified] — https://support.claude.com/en/articles/12260368-use-incognito-chats
- Incognito chats: not in chat history, not saved to memory, not used for training; kept 30 days by default; not available inside projects; cannot be reopened once closed; in the new Claude experience they open in the previous chat experience (no file creation or code). [verified] — same URL
- Sensitive data guidance: be thoughtful about sharing "highly sensitive personal details" such as financial information (credit card numbers, bank account details, SSN), health records, passwords or login credentials. [verified] (page date 2026-05-22) — https://support.claude.com/en/articles/8325621-i-would-like-to-input-sensitive-data-into-my-chats-with-claude-who-can-view-my-conversations
- When training is allowed, data is de-linked from your user ID (e.g. email) before review; access limited to a small number of staff. [verified] — same URL
- Signing in with an employer-owned email may link the account to that organisation's enterprise account, whose admins may see it. [verified] — https://www.anthropic.com/legal/consumer-terms
- Usage Policy basics: no illegal activity, fraud, deceptive campaigns, spreading false information, privacy violations, etc. [verified] — https://www.anthropic.com/legal/aup
- High-risk uses (legal, healthcare, financial incl. personalised investment/tax advice, insurance, employment, housing…): a qualified human must review before it reaches the person, and people must be told AI was used. [verified] — https://www.anthropic.com/legal/aup
- Consumer Terms forbid relying on the service for securities/financial advice (Anthropic is not an investment adviser). [verified] — https://www.anthropic.com/legal/consumer-terms

## C. claude.ai basics

- Apps: web (claude.ai), desktop for macOS (one universal build) and Windows, iOS app; phones can also use claude.ai/mobile. Download page: claude.com/download. [verified] — https://claude.com/download
- Android app "Claude by Anthropic" exists (help articles give Android steps). Google Play link not fetched. [verified] — https://support.claude.com/en/articles/8230524-delete-or-rename-a-conversation
- Desktop app needs "macOS 13 (Ventura) or higher"; install: download → open file → launch from Applications → sign in. [verified] — https://support.claude.com/en/articles/10065433-install-claude-desktop
- New Claude experience (rolling out from 2026-09, Pro and Max first): Chat and Cowork merged, no "Chat"/"Cowork" choice; web search toggle removed (Claude searches when useful); Research via "+" → "Research" or typing /deep-research; Auto/Manual permission setting in the message box (Manual default); model picker stays; cannot switch back. [verified] (page date 2026-09-16) — https://support.claude.com/en/articles/16761823
- Model picker: selected model and effort appear next to the send button; click it; "More models" shows more. You can change model mid-chat; applies from the next reply. [verified] — https://support.claude.com/en/articles/8664678-how-can-i-change-the-model-version-that-i-m-chatting-with
- Current model names: Claude Fable 5.1, Claude Opus 5.5, Claude Sonnet 5.5, Claude Haiku 5.5 (older still listed: Opus 5, Sonnet 5, Fable 5, Opus 4.7/4.6, Sonnet 4.6). [verified] — https://platform.claude.com/docs/en/about-claude/models/overview , https://support.claude.com/en/articles/8664678-how-can-i-change-the-model-version-that-i-m-chatting-with
- Plain descriptions: Sonnet 5.5 "The best combination of speed and intelligence"; Haiku 5.5 fastest; Opus 5.5 long agentic and knowledge work; Fable 5.1 demanding reasoning, slower. [verified] — https://platform.claude.com/docs/en/about-claude/models/overview
- Upload types: PDF, DOCX, CSV, TXT, HTML, ODT, RTF, EPUB, JSON, XLSX; images JPEG, PNG, GIF, WebP. XLSX needs "code execution and file creation" turned on. [verified] — https://support.claude.com/en/articles/8241126-upload-files-to-claude
- Chat upload limits: 500MB per file, up to 20 files per chat, images up to 8000×8000 px, PDFs up to 1000 pages (≤100 pages: text and visuals; 101–1000: text only). Project files: 30MB each. [verified] (page shows 2026-07-23) — same URL
- How to upload: click the "+" button in the lower left corner of the chat box and select "Add files or photos"; or drag and drop files into the chat window; or paste copied images from the clipboard. No paperclip icon is mentioned. [verified 2026-10-20, added after review] — same URL
- HEIC/HEIF (common iPhone photo format) is not mentioned anywhere on the upload page; supported image formats are only JPEG, PNG, GIF, WebP. Treat HEIC as not supported and tell readers to use a screenshot (macOS screenshots are PNG). [verified 2026-10-20: not listed] — same URL
- File creation: Claude makes .xlsx, .pptx, .docx and PDF files to download (or save to Google Drive); can process CSV/TSV and make PNG charts; all plans; on by default for Free/Pro/Max. [verified] (page date 2026-08-06) — https://support.claude.com/en/articles/12111783
- Setting: "Settings > Capabilities" → "Code execution and file creation" (코드 실행 및 파일 생성). File-creation article says 30MB max per file for uploads and downloads. [verified] — same URL
- File-creation safety: watch Claude while it works and stop it if it accesses data unexpectedly; malicious text in files or websites could trick it. [verified] — same URL
- Web search: available to free accounts too (subject to limits); turn on via "+" (lower left) → "Web search" (checkmark). In the new experience there is no toggle. [verified] — https://support.claude.com/en/articles/10684626
- Web search answers include citations (source links and quotes). [verified] — same URL
- Research (리서치): paid plans only (Pro, Max, Team, Enterprise); "+" → "Research"; needs web search on; runs several linked searches. [verified] — https://support.claude.com/en/articles/11088861-use-research-on-claude
- Projects: all users; Free max five projects; "+ New Project"; files uploaded to a project are used in all its chats; "project instructions" apply to all its chats. [verified] — https://support.claude.com/en/articles/9519177
- Memory: on by default for Free, Pro, Max; "Settings > Memory" → "Generate memory from chats"; off options "Pause memory" / "Reset memory"; remembered items listed under "Topics" (edit or "Delete"); per chat: "+" → "Memory" before the first message. [verified] — https://support.claude.com/en/articles/11817273
- Searching past chats: paid plans only. [verified] — same URL
- "When a conversation expires or is deleted, related memory entries generated from it won't be removed," but individual memories can be deleted at any time: Settings > Memory → "Topics" → select a topic → edit icon to change it, or "Delete" to remove it. (A legacy section on the same page says the opposite for the old memory: "Deleted conversations are removed from memory synthesis.") [verified 2026-10-20, added after review] — https://support.claude.com/en/articles/11817273
- "Pause memory": Claude keeps its existing memory. "Reset memory": "Permanently deletes all memories including project memories." Memory is on by default for Free, Pro and Max "on the web, Claude Desktop, and Claude Mobile"; off by default for Team/Enterprise members. [verified 2026-10-20] — same URL
- Artifacts: "anything Claude makes for you that you'd put in front of someone" (designs, decks, documents, dashboards, small tools); open in a side panel; private until you share; all plans; need "Cloud code execution and file creation" in Settings > Capabilities. [verified] — https://support.claude.com/en/articles/17153992
- Artifacts made in a chat before 2026-09-16 are "Legacy artifacts": still work and can be shared, but new ones are made the new way. [verified] — same URL
- Connectors (brief): Gmail, Google Calendar, Google Drive connectors available to all users; manage under "Customize > Connectors"; in a chat "+" → "Connectors". Gmail can send/reply but asks approval first by default. [verified] — https://support.claude.com/en/articles/10166901
- Official beginner tutorial headings: "Your first prompt", "What a Claude response can look like", "Set up your first task", "What Claude remembers". [verified] — https://academy.claude.com/tutorials/getting-started-with-claude-ai

## D. Accuracy

- "Claude can occasionally produce responses that are incorrect or misleading" — called "hallucinating"; examples: outdated knowledge about current events, quotes that sound authoritative but are not grounded. [verified] (page date 2026-03-16) — https://support.claude.com/en/articles/8525154-claude-is-providing-incorrect-or-misleading-responses
- Guidance: do not use Claude as your only source of truth; scrutinise high-stakes advice; when web search is used, review the cited sources; report bad answers with the thumbs-down button. [verified] — same URL
- Consumer Terms: outputs may not always be accurate; do not rely on them without checking their accuracy yourself. [verified] — https://www.anthropic.com/legal/consumer-terms
- Official tips: allow Claude to say "I don't know"; for long documents ask for word-for-word quotes first; ask it to cite a source or quote for each claim and remove claims it cannot support; ask it to use only the provided documents; run the same request again and compare. [verified] — https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations
- "while these techniques significantly reduce hallucinations, they don't eliminate them entirely. Always validate critical information". [verified] — same URL

## E. Claude Code in the terminal

### Login
- Claude Code requires macOS 13.0 or later. Open Terminal: Cmd+Space → type Terminal → Enter. Paste with Cmd+V. [verified] — https://code.claude.com/docs/en/terminal-guide.md
- First run of `claude`: it opens a browser window to log in. If the browser does not open, press `c` to copy the login URL. If the browser shows a code, paste it at `Paste code here if prompted`. On success: `Login successful`, press Enter. [verified] — https://code.claude.com/docs/en/authentication.md
- Account types at login include Claude Pro/Max subscription (claude.ai account), Teams/Enterprise, Claude Console, cloud provider ("3rd-party platform"). [verified] — same URL
- Once logged in, credentials are stored (macOS Keychain) and you don't log in again. [verified] — https://code.claude.com/docs/en/quickstart.md , https://code.claude.com/docs/en/authentication.md
- `/login` (sign in / switch account), `/logout` (sign out; next `claude` walks through login and setup again). [verified] — https://code.claude.com/docs/en/authentication.md , https://code.claude.com/docs/en/commands.md
- `claude auth status`: shows login status as JSON (`--text` for readable); exit code 0 if logged in, 1 if not. [verified] — https://code.claude.com/docs/en/cli-reference.md
- If `ANTHROPIC_API_KEY` is set and approved, Claude Code bills the API key instead of the subscription. [verified] — https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan
- Subscription login missing: `/logout`, `claude update`, restart terminal, run `claude` and pick the right account. [verified] — same URL
- Login near expiry shows `Your login expires in 3 days · run /login to renew`; expired: `Login expired · Please run /login`. [verified] — https://code.claude.com/docs/en/authentication.md

### Folder trust
- Interactive sessions show a "workspace trust dialog" when started in a folder not yet trusted. [verified] — https://code.claude.com/docs/en/security.md
- Trust is saved per git repository root, or per start folder outside a repo; started in the home folder, trust lasts only that session and the prompt returns each launch. [verified] — https://code.claude.com/docs/en/permissions.md , https://code.claude.com/docs/en/security.md
- Trust is stored as `projects["<path>"].hasTrustDialogAccepted` in `~/.claude.json`; project allow rules in `.claude/settings.json` apply only after trust is accepted. [verified] — https://code.claude.com/docs/en/permissions.md

### Permission prompts and modes
- A prompt shows what Claude will do and asks "Do you want to proceed?" with options like "Yes", "Yes, and don't ask again for: …", "Yes, and switch to auto mode", "No"; "Esc to cancel", "Tab to amend" (add a note). [verified] — https://code.claude.com/docs/en/permissions.md
- "Yes, and don't ask again": permanent per repository for Bash commands; file edits only until the session ends. Choosing "No" without a comment stops the turn. [verified] — same URL
- Modes: `default` (labelled "Manual"; asks before edits/commands, reads run freely), `acceptEdits` (file edits and basic file commands without asking), `plan` (reads and proposes; no edits), `auto` (everything, with background safety checks), `dontAsk` (only pre-approved tools), `bypassPermissions` (everything, isolated containers/VMs only). [verified] — https://code.claude.com/docs/en/permission-modes.md
- Status bar: `⏸ manual mode on`, `⏵⏵ accept edits on`, `⏸ plan mode on`, `⏵⏵ auto mode on`, `⏵⏵ bypass permissions on`. [verified] — same URL
- Shift+Tab cycles `default` → `acceptEdits` → `plan` → (`bypassPermissions` if enabled) → `auto`; from `auto` the first press goes to `default`. [verified] — https://code.claude.com/docs/en/permission-modes.md , https://code.claude.com/docs/en/interactive-mode.md
- Auto mode is now the built-in starting mode for interactive terminal sessions (Claude Code v2.1.283+); available on all plans; a notice appears the first time. If auto is unavailable, the session starts in Manual. [verified] — https://code.claude.com/docs/en/permission-modes.md
- Auto mode: "A separate classifier model reviews actions before they run, blocking anything that escalates beyond your request, targets unrecognized infrastructure, or appears driven by hostile content Claude read. Explicit ask rules still force a prompt." [verified] — same URL
- "Auto mode reduces permission prompts but does not guarantee safety." [verified] — same URL
- Blocked by default (examples): downloading and running code (`curl | bash`), sending sensitive data to outside endpoints, production deploys, mass deletion in cloud storage, force push. Allowed: local file work in the folder, read-only web requests. [verified] — same URL
- Reads and edits inside the working folder are auto-approved; other actions go to the classifier; the classifier does not see tool results (so web/file text cannot talk to it directly). [verified] — same URL
- Blocked action → notification, listed in `/permissions` "Recently denied" (press `r` to retry with approval). 3 blocks in a row or 20 total → auto mode pauses and normal prompts return. [verified] — same URL
- Manual mode boundary: file tools ask before reading/writing outside the start folder, but an approved Bash command can write anywhere your account can. [verified] — https://code.claude.com/docs/en/security.md
- "You're responsible for reviewing proposed code and commands for safety before approval." [verified] — same URL

### Undo: checkpoints and rewind
- Every prompt that starts a turn creates a checkpoint of Claude's file edits; last 100 checkpoints per session kept; snapshots deleted about 30 days after last use. [verified] — https://code.claude.com/docs/en/checkpointing.md
- Open: `/rewind` (aliases `/checkpoint`, `/undo`) or press Esc twice on an empty prompt (with text, double Esc clears the text). [verified] — same URL , https://code.claude.com/docs/en/commands.md
- Menu actions: "Restore code and conversation", "Restore conversation", "Restore code", "Summarize from here", "Summarize up to here", "Never mind". [verified] — https://code.claude.com/docs/en/checkpointing.md
- Not undone: files changed by Bash commands (e.g. `rm`, `mv`, `cp`); your own manual edits outside Claude Code; edits from other sessions; most subagent edits; symlinked files. Nothing outside the computer (sent messages, web actions) is undone [inferred]. [verified] — same URL
- "Not a replacement for version control" — use Git for permanent history. [verified] — same URL

### Everyday commands and keys
- `/clear`: new conversation with empty context (aliases `/reset`, `/new`); the old one can be reopened with `/resume`. [verified] — https://code.claude.com/docs/en/commands.md
- `/resume`: pick a previous conversation; from the shell `claude -c` (continue latest in this folder) or `claude -r` (pick). [verified] — https://code.claude.com/docs/en/commands.md , https://code.claude.com/docs/en/quickstart.md
- `/model`: switch model (saved as default; press `s` to switch for this session only). [verified] — https://code.claude.com/docs/en/commands.md
- `/usage` (aliases `/cost`, `/stats`): session cost, plan usage limits and activity; Pro/Max see plan usage bars. `/status`: version, model, account, connectivity. [verified] — https://code.claude.com/docs/en/commands.md , https://code.claude.com/docs/en/costs.md
- `/usage-credits`: opens claude.ai Settings > Usage for Pro/Max. `/upgrade`: opens the upgrade page. `/privacy-settings`: Pro/Max privacy settings. [verified] — https://code.claude.com/docs/en/commands.md
- `/help`: show commands. Typing `/` lists commands. [verified] — https://code.claude.com/docs/en/commands.md
- Quit: `/exit` (alias `/quit`), or Ctrl+D twice, or Ctrl+C twice on an empty prompt. Esc interrupts Claude while it works (work so far is kept). [verified] — https://code.claude.com/docs/en/interactive-mode.md , https://code.claude.com/docs/en/quickstart.md
- Paste an image: Ctrl+V (Cmd+V in iTerm2) inserts an `[Image #N]` chip. Multiline: Shift+Enter (native in Apple Terminal). [verified] — https://code.claude.com/docs/en/interactive-mode.md
- Hitting a usage limit mid-task: Claude Code shows `Usage limit reached · limit resets …` and `Continuing automatically at … · esc to cancel` and continues after the reset if the window stays open (v2.1.234+, subscription logins). [verified] — https://code.claude.com/docs/en/interactive-mode.md
- Claude Code usage counts against the same plan limits as claude.ai; message `Usage limit reached · wrapping up` may appear. [verified] — https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan
- Local transcripts are kept 30 days by default under `~/.claude/projects/`. [verified] — https://code.claude.com/docs/en/data-usage.md

## F. Official learning resources

- Claude 101 — 13 lessons + quiz, 2.5 h, any plan: https://academy.claude.com/courses/claude-101 [verified]
- Claude Code 101 — 12 lessons, 1.5 h, needs Pro/Max/Team/Enterprise or API key: https://academy.claude.com/courses/claude-code-101 [verified]
- AI Fluency: Framework and foundations — 14 lessons + quiz, 4 h: https://academy.claude.com/courses/ai-fluency-framework-foundations [verified]
- AI capabilities and limitations — 13 lessons, 3.5 h, no prerequisites: https://academy.claude.com/courses/ai-capabilities-and-limitations [verified]
- Getting started with Claude (tutorial): https://academy.claude.com/tutorials/getting-started-with-claude-ai [verified]
- Academy home ("Free courses, tutorials, and use cases from Anthropic's education team"): https://academy.claude.com/ [verified]
- Terminal guide for new users: https://code.claude.com/docs/en/terminal-guide.md (link without `.md` for readers) [verified]
- Help Center pages above (usage best practices 9797557, incognito 12260368, privacy 12109829, hallucination 8525154) are suitable "더 알아보기" links. [verified]

## 일손 Box facts (from repo)

- Box folder defaults to `~/ilson` (`ILSON_HOME="${ILSON_HOME:-$HOME/ilson}"`). — ilson:35
- The installer auto-installs Claude Code (and Codex CLI); the human does the subscription login. — README.md:16-18
- Installer does not set API keys or paid API calls. — README.md:38
- First setup flow: `cd ~/ilson` → `claude /onboard` (로그인·폴더 신뢰·회사 인터뷰) → `ilson start`. — README.md:27-29
- Login check = `claude auth status` (10 s timeout, `ILSON_CHECK_TIMEOUT`) parsed with jq `.loggedIn == true`. — ilson:102-107
- `ilson doctor` shows "Claude 로그인" with fix hint "claude 실행 후 브라우저 로그인 필요 (조회 실패/시간 초과 포함)". — ilson:139
- Folder trust check reads `~/.claude.json` → `.projects[$ILSON_HOME].hasTrustDialogAccepted == true`. — ilson:256, ilson:553
- Setup summary tells the user "claude 실행 → 본인 구독 계정으로 로그인" and "이후 설치·설정·업무 요청은 ilson chat (관리용 자동 심사 모드)". — ilson:525, ilson:531
- `ilson chat` refuses in sandbox, needs `~/ilson/CLAUDE.md`, then runs settings.py `--chat`. — ilson:542-546
- settings.py `--chat`: changes to the box folder and runs `claude --permission-mode auto` (plus `--model X` only if a model is set). — template/lib/research/settings.py:40-44
- Default LLM settings: provider `claude`, model empty (= use Claude Code's configured default). — template/lib/research/settings.py:13
- `ilson llm [claude|codex] [모델명]` shows/changes the default chat/research LLM. — ilson:580, ilson:626-627
- `ilson start` requires login, folder trust, a company name in `vault/CONTEXT.md`, and gtimeout; error texts e.g. "Claude 로그인 확인 실패 — 로그인 후 다시 시도하세요", "박스 폴더에서 claude 를 열어 폴더 신뢰를 확인하세요", "회사 정보가 비어 있습니다 — 박스 폴더에서 claude /onboard 를 실행하세요". — ilson:548-566
- Help text: "chat — 설치·관리까지 가능한 대화 (auto 자동 심사)". — ilson:573
- `template/claude/` is copied to `~/ilson/.claude/` (project settings). — ilson:377
- Project default model alias: `"model": "sonnet"`. — template/claude/settings.json:3
- Env: `DISABLE_AUTOUPDATER=1`, `DISABLE_TELEMETRY=1` (Claude Code version on a box may lag behind docs). — template/claude/settings.json:4-7
- Permissions: allow Read/Glob/Grep/Edit/Write/WebSearch/WebFetch and a few git/date/search commands; ask for `sudo`, `rm`, `rmdir`; deny reading `pairing.json` and `.env`. — template/claude/settings.json:8-31
- README: `ilson chat` starts in Claude `auto` mode; auto review is not "allow everything"; it never falls back to bypass-permissions mode. — README.md:82
- Scheduled jobs run separately with `dontAsk`, explicit tool lists and safe-mode, using the subscription login. — README.md:83
- Confirmation remains for customer sending, payments, mass deletion, account/security changes (relies on rules + Claude review, not an OS gate). — README.md:84
- After a box install/update, end old Claude conversations and restart with `ilson chat`. — README.md:85
- Web admin also reads `loggedIn` from `claude auth status` for the live status card. — template/lib/web-admin-server.py:225-227
- Cross-check [inferred]: because `--permission-mode auto` is a flag, it overrides settings; if auto is unavailable the session starts in Manual (per permission-modes doc).

## Not confirmed / changes often

- Exact wording of the terminal folder-trust dialog (bug reports mention "Do you trust the files in this folder?", "Yes, proceed" / "No, exit"; older "Yes, I trust this folder"). Not in official docs — describe it generically. [unverified]
- Exact labels of the first-run Claude Code login menu (e.g. "Claude account with subscription"). Docs name the account types, not the menu text. [unverified]
- "Continue with Apple" on web/desktop: not on the official login page; may exist in the iOS app. [unverified]
- Korean prices in KRW and whether Korean prices include 부가세(VAT): not found. Say "결제 화면 금액 기준" and link claude.ai/upgrade. [unverified]
- App Store / Google Play price amounts: official page only says mobile pricing "may vary". [unverified]
- Fable on Pro "requires usage credits" and Max "50% of weekly limits": read from pricing table; likely to change. [verified but volatile]
- Upload size conflict: upload article says 500MB per chat file; file-creation article says 30MB per file for uploads and downloads. Safer to tell beginners "큰 파일은 나눠서" without a number, or cite both with dates. [conflict]
- Setting label drift: "Help Improve our AI models" (2026-08 page) vs "Model Improvement"; "Code execution and file creation" vs "Cloud code execution and file creation". Tell readers to look in Settings > Privacy / Capabilities. [conflict]
- Help article says use `/status` to see remaining Claude Code allowance; current docs say plan usage bars are in `/usage`. Prefer `/usage`, mention `/status` for account. [conflict]
- New Claude experience is a gradual rollout: some readers still see "Chat"/"Cowork" choices and the web search toggle. Screens differ by account. [verified, varies]
- Usage Policy page shows "Effective November 12, 2026" (after today) and was served in Korean; a "Previous Version" link exists. Cite generally, not by date. [verified, odd]
- Built-in auto default needs Claude Code v2.1.283+; boxes with auto-update off may run older versions (ilson chat passes the flag anyway). [inferred]
- Google Play listing URL for the Android app: not fetched. [unverified]
- Line-break key in the claude.ai message box (e.g. Shift+Enter): not found on an official page. Lessons say "줄 바꿈 없이 이어서 써도 괜찮아요" instead. [unverified]
- Korean menu labels shown after switching Language to Korean (e.g. what "Settings" or "Memory" become): not checked. Lessons give the English label plus a gloss and tell readers to look for that meaning. [unverified]
- Where the Consumer Terms "customer portal" is in the app (likely Settings > Billing, but not stated): lessons quote the terms and offer the support@anthropic.com route. [unverified]
- Weekly reset anchoring (fixed time vs rolling): official text says "fixed time assigned to your account" for Max; third-party reports differ. [verified for Max only]

## G. Added in the b11–b14 review round (fetched 2026-10-20)

Claude Code (terminal):
- Pasting more than 800 characters or more than three lines collapses the input to a placeholder such as `[Pasted text #1 +120 lines]`; the full content is still sent on submit. [verified] — https://code.claude.com/docs/en/terminal-config.md
- Apple Terminal: Shift+Enter inserts a newline without setup; Ctrl+J or `\` then Enter also work everywhere. [verified] — https://code.claude.com/docs/en/terminal-config.md
- Apple Terminal has a "first-run terminal setup prompt" that runs `/terminal-setup` (Option as Meta, audible bell off). [verified] — https://code.claude.com/docs/en/terminal-config.md
- `/logout` resets the first-launch setup state, so the next `claude` "walks you through login and setup again". [verified] — https://code.claude.com/docs/en/authentication.md
- The first-run setup may include a theme (text colour) choice. `/theme` exists, but a first-run theme question is not documented on the pages fetched. [unverified]
- The login prompt offers non-subscription routes such as **3rd-party platform** and a Console account choice. [verified] — https://code.claude.com/docs/en/authentication.md
- The subscription choice in the login menu contains "Pro", "Max" or "subscription": the docs name the account type "Claude Pro or Max subscription", but the menu labels are not documented. [inferred]
- Trust dialog: the accepting option usually starts with "Yes" (bug reports mention "Yes, proceed" / "Yes, I trust this folder"). [inferred]
- Started directly in the home directory, trust acceptance is held for the current session only and is not written to disk. [verified] — https://code.claude.com/docs/en/security.md
- The first time the built-in default starts a session in auto mode, a notice appears once at the top of a terminal session. On Pro, Max and Team plans Claude Code may also ask once whether to change the setting to auto mode; declining leaves the setting as it is. The exact question text is not documented. [verified] — https://code.claude.com/docs/en/permission-modes.md
- The `--permission-mode` flag has the highest precedence for the starting mode. If auto is selected but unavailable, the session starts in Manual. [verified] — https://code.claude.com/docs/en/permission-modes.md
- The built-in auto default needs v2.1.228+ on macOS; for terminal sessions the docs table says auto with v2.1.283 or later, and on earlier versions auto only on Pro/Max/Team sessions that fetch feature flags, otherwise `default`. [verified] — https://code.claude.com/docs/en/permission-modes.md
- The status bar shows a grey `⏸ manual mode on` for `default`. Whether older versions show a label at all is not documented, so the lessons say "no label is also fine". [inferred]
- Plan mode: when the plan is ready Claude asks how to proceed, with options "Yes, and use auto mode" (or "Yes, auto-accept edits"), "Yes, manually approve edits", "No, keep planning". Approving switches the permission mode, "so Claude starts editing". [verified] — https://code.claude.com/docs/en/permission-modes.md
- Auto mode decision order: allow/ask/deny rules resolve first ("Ask rules that match on a command's content, such as `Bash(git push *)`, fall back to a permission prompt"); then read-only actions and in-folder edits are auto-approved; everything else goes to the classifier. [verified] — https://code.claude.com/docs/en/permission-modes.md
- Manual mode asks before editing files, running tests or executing commands, but runs a built-in set of read-only commands without asking. Accept Edits auto-approves file edits and filesystem commands such as `mkdir`, `touch`, `rm`, `mv`, `cp`, `sed` inside the working directory. [verified] — https://code.claude.com/docs/en/security.md
- Quickstart: "If it asks before making the change, select **Yes** to approve." [verified] — https://code.claude.com/docs/en/quickstart.md
- Rewind: the menu "lists the prompts you sent during the session. Select the point you want to act on, then choose an action." [verified] — https://code.claude.com/docs/en/checkpointing.md
- "The two code restore options appear only when the selected checkpoint has tracked file changes to revert." Otherwise the menu offers only Restore conversation, the summarize options and Never mind. [verified] — https://code.claude.com/docs/en/checkpointing.md
- After Restore conversation (or Summarize from here), "the original prompt from the selected message is restored into the input field". [verified] — https://code.claude.com/docs/en/checkpointing.md
- "Never mind: return to the message list without making changes". Esc closes a dialog. [verified] — https://code.claude.com/docs/en/checkpointing.md , https://code.claude.com/docs/en/interactive-mode.md
- Double Esc with text in the input clears it (Up recalls it); on an empty input it opens the rewind menu. Checkpoints are saved with the conversation, so `/rewind` also works after `/resume`. [verified] — https://code.claude.com/docs/en/checkpointing.md
- Ctrl+C interrupts a running operation; if nothing is running, the first press clears the input and a second press exits. Ctrl+D: the first press shows a hint and a second press within 800 ms exits. [verified] — https://code.claude.com/docs/en/interactive-mode.md
- Lists and menus: pick a row with the arrow keys and Enter; rewind summarize rows are highlighted with the arrow keys and can also be chosen by number key. [verified] — https://code.claude.com/docs/en/interactive-mode.md , https://code.claude.com/docs/en/checkpointing.md

일손 Box (repo, read-only):
- Clicking 「서류함」 again reloads only the list (`loadVault`); an open document keeps its old text until the document row is clicked again (`vaultOpenDoc` fetches it). — template/web/current/shell.js:9, 12, 20
- Clicking 「Claude 배우기」 from another tab returns to the open lesson; clicking it again while on the learn tab goes to the catalog. — template/web/current/learn/learn.js:454-457
- Only the Claude login check is cached for 30 s; folder trust and company name are read fresh on each overview request. — template/lib/web-admin-server.py:221-238, 360-388
- `ilson llm codex` makes `ilson chat` start Codex instead of Claude; `ilson llm claude` switches back. — template/lib/research/settings.py:37-43, ilson:626-627
- Ask rules cover only `Bash(sudo *)`, `Bash(rm *)` and `Bash(rmdir *)`; project rules apply after folder trust; README.md:115 says real approval-prompt behaviour must still be confirmed on a new Mac. — template/claude/settings.json:22-26, ilson:253-255
- The macOS zsh prompt ends in `%` (general macOS knowledge, not a Claude fact).
