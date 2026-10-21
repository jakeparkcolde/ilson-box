# Claude 배우기 — Fact sheet for Track B (바이브 코딩 심화)

Checked: 2026-10-21

Scope: facts for the planned 예약·문의 page project (v01–v10 in SPEC.md §4, Track B). Same rules as FACTS.md.
Each line = fact · tag · source actually fetched on 2026-10-21.
Tags: [verified] seen on the page · [inferred] implied by the page · [unverified] not confirmed (search snippet only, or not found) · [tested] reproduced in the local Supabase test stack (docs/claude-learn/vibe/test-log.md).
Quotes in "double quotes" are the original wording. Pages were read through a page-summarising fetch tool, so long quotes may differ slightly in punctuation; short labels and numbers were checked.
Where a page showed its own date it is noted as (page date …). Prices are USD unless stated and change often.
Claude Code basics already in FACTS.md §E (login, trust, permission modes, checkpoints) are not repeated here.

## V1. Hosting: free tier, commercial use, custom domain, HTTPS

### Vercel
- Hobby is free ("$0/mo."); the pricing FAQ says "Our Hobby plan is for personal, non-commercial use." Pro is "$20/mo." [verified] — https://vercel.com/pricing
- "Hobby teams are restricted to non-commercial personal use only. All commercial usage of the platform requires either a Pro or Enterprise plan." [verified] (page date 2026-09-14) — https://vercel.com/docs/limits/fair-use-guidelines
- Commercial usage = a deployment "used for the purpose of financial gain of anyone involved in any part of the production of the project". Examples include "Any method of requesting or processing payment from visitors of the site", "Advertising the sale of a product or service", "The inclusion of advertisements". "Asking for Donations does not fall under commercial usage." [verified] — same URL
- So a real shop's 예약·문의 page (it advertises the shop's service) falls under Vercel's commercial definition and needs Pro. [inferred] — same URL
- Hobby included usage per month: Fast Data Transfer first 100 GB, Function Invocations first 1,000,000, Active CPU 4 CPU-hrs. Over the limit: "you will have to wait until 30 days have passed before you can use the feature again." [verified] (page date 2026-09-14) — https://vercel.com/docs/plans/hobby
- Hobby: 200 projects, 50 domains per project, 100 deployments per day, 1 hour of runtime logs. [verified] — same URL
- Upgrade to Pro: Settings → Billing → Upgrade, "Enter your card details". [verified] — same URL
- HTTPS: "HTTPS Certificates" and "TLS/SSL Encryption" listed as "Included" on Hobby and Pro. [verified] — https://vercel.com/pricing
- Every deployment gets a `vercel.app` URL; custom domains are added in Project → Settings → Domains. Apex domain (example.com) uses an A record; subdomain (www.example.com) uses a CNAME; both can instead use Vercel nameservers. "Hobby teams have a limit of 50 custom domains per project." [verified] (page date 2026-09-16) — https://vercel.com/docs/domains/working-with-domains/add-a-domain
- "DNS changes can take time to propagate." [verified] — same URL

### Netlify
- Free: "Free — $0 forever", "300 credit limit", "Add Custom domains with SSL". Personal $9/month (1,000 credits), Pro $20/month (3,000 credits). [verified] — https://www.netlify.com/pricing/
- The Self-Serve Subscription Agreement does not limit the Free Usage Tier to personal or non-commercial use (no "commercial" restriction found). Free tier: "made available by Netlify to allow users to experience Netlify's Services"; it "may be terminated by either Netlify or Customer". [verified] (agreement text "Last Updated September 8th, 2020") — https://www.netlify.com/legal/self-serve-subscription-agreement/
- Credits on Free: "300 credits/month", "Hard limit". Production deploy = "15 credits each"; failed deploys and rollbacks cost 0; Deploy Previews and branch deploys 0 credits; bandwidth 20 credits per GB; web requests 2 credits per 10,000. [verified] (page date 2026-08-12) — https://docs.netlify.com/manage/accounts-and-billing/billing/billing-for-credit-based-plans/how-credits-work/
- So 300 credits allow at most 20 production deploys a month if nothing else used credits. [inferred] — same URL
- When credits run out, "all of your web projects (sites/apps) are paused and visitors … will find a `Site not available` page"; paused sites get no "form submissions"; on Free you "wait till the start of your next billing cycle or upgrade". [verified] (page date 2026-10-07) — https://docs.netlify.com/manage/accounts-and-billing/billing/billing-for-credit-based-plans/billing-faq-for-credit-based-plans/
- A saved payment method is required "to keep your web projects active with the Personal or Pro" plans; the page does not say a card is needed for Free. [verified] — same URL
- Credit-card requirement for Free sign-up: not confirmed on a current official page. [unverified]

### Cloudflare Pages / Workers static assets
- Cloudflare's Pages docs now say "Start new projects with Workers"; Workers "supports most Pages use cases and offers a broader feature set". Pages is "Available on all plans", "500 deploys per month on the Free plan". [verified] — https://developers.cloudflare.com/pages/
- Pages Free limits: 500 builds/month, 1 build at a time, 20,000 files per site, 25 MiB per file, 100 custom domains per project, 100 projects per account. [verified] — https://developers.cloudflare.com/pages/platform/limits/
- Workers static assets: "Requests to static assets are free and unlimited." "There is no additional cost for storing Assets." Requests that run Worker code are billed as Workers. [verified] — https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/
- Workers Free: 100,000 requests per day (resets midnight UTC); over the limit Cloudflare returns "Error 1027". Static assets on Free: 20,000 files per version, 25 MiB per file. [verified] — https://developers.cloudflare.com/workers/platform/limits/
- Workers Paid: "a minimum charge of $5 USD per month for an account". [verified] — https://developers.cloudflare.com/workers/platform/pricing/
- Self-Serve Subscription Agreement: no "personal use" or "non-commercial" limit on Free Services found. It does bar using Free Services to "process or collect personal or business credit card information" (§2.2.1(h)), and says Cloudflare has "no liability for any harm or damage arising out of or in connection with any Free Services" (§2.6). [verified] ("Last Updated September 12, 2025") — https://www.cloudflare.com/terms/
- Custom domain on Pages: apex domain (example.com) must be a Cloudflare zone (point nameservers to Cloudflare); a subdomain (shop.example.com) can stay at another DNS provider with a CNAME to `<YOUR_SITE>.pages.dev`; add the domain in the Pages dashboard first or the CNAME can fail (522). [verified] — https://developers.cloudflare.com/pages/configuration/custom-domains/
- CAA records that don't allow Cloudflare's certificate authorities (e.g. letsencrypt.org, pki.goog, ssl.com) can block adding a domain. [verified] — same URL

### GitHub Pages
- "GitHub Pages is not intended for or allowed to be used as a free web hosting service to run your online business, e-commerce site, or any other website that is primarily directed at either facilitating commercial transactions or providing commercial software as a service (SaaS)." "Some monetization efforts are permitted on Pages, such as donation buttons and crowdfunding links." [verified] — https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features
- "GitHub Pages sites shouldn't be used for sensitive transactions like sending passwords or credit card numbers." Limits: 1 GB site, soft 100 GB/month bandwidth, soft 10 builds/hour. [verified] — https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
- GitHub Free for personal accounts lists "GitHub Pages in public repositories" only; Pages from private repositories is listed under GitHub Pro/Team. [verified] — https://docs.github.com/en/get-started/learning-about-github/githubs-plans
- Addresses: `<owner>.github.io` or `<owner>.github.io/<repositoryname>`; "You can host your site on GitHub's github.io domain or your own custom domain." [verified] — https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- "GitHub Pages sites created after June 15, 2016, and using github.io domains are served over HTTPS automatically." Custom domains support "Enforce HTTPS" (Settings → Pages); certificate requested from Let's Encrypt. [verified] — https://docs.github.com/en/pages/getting-started-with-github-pages/securing-your-github-pages-site-with-https

### Korean availability
- None of the hosting pages fetched (Vercel, Netlify, Cloudflare, GitHub) state a restriction for South Korea or Korean-language support. [unverified]

## V2. Collecting inquiries without running a server

### Google Forms + Google Sheets
- Embed a form: open the form → More menu (top right) → "Embed HTML" → "Copy" → paste into the website. Link: "Copy responder link" (Preview, Published or Share menu); "Shorten URL" option. [verified] — https://support.google.com/docs/answer/2839588
- Responses: "Responses" tab → Link to Sheets icon; email alerts: Responses → More → "Get email notifications for new responses". Stop: Published → turn off "Accepting responses" (or set a close date / response limit). [verified] — https://support.google.com/docs/answer/139706
- Warning on that page: "If you've shared a form with a collaborator, they may also have access to the form's linked spreadsheet." [verified] — same URL
- Limits: up to 500k responses per form; from September 2026 "Each form can have up to 1 GB of total storage"; Sheets syncing may stop above 100,000 responses. [verified] — same URL
- Google Terms of Service do not forbid business use; they have a section "Using Google services on behalf of an organization or business" and extra terms for business users. Service-specific terms for Forms were not checked. [verified] (South Korea version, effective 2026-07-30) — https://policies.google.com/terms?hl=en

### Netlify Forms (if the page is hosted on Netlify)
- Add `data-netlify="true"` (or `netlify`) and a `name` to the `<form>` tag; turn on Forms → "Enable form detection"; submissions show in the site admin; notifications: Forms → Submission notifications → "Add notification" (email or HTTP POST). [verified] (page date 2026-09-16) — https://docs.netlify.com/manage/forms/setup/
- "For credit-based plans, Forms are free and unlimited." [verified] (page date 2026-09-16) — https://docs.netlify.com/manage/forms/usage-and-billing/

### Tally and Formspree
- Tally Free: unlimited forms and submissions within "fair usage guidelines"; "Self email notifications"; Tally branding shown; custom domain is Pro only; Pro $24/month. [verified] — https://tally.so/pricing
- Tally fair-use page gives no number: "We expect the usage of most of our users to fall within the range of our free plan." [verified] — https://tally.so/help/fair-use-policy
- Tally terms: no commercial or personal-use limit on free use; "Although the Tool is available for free use, you must subscribe to the paid version" for full features. [verified] (Version 2.0, 09/09/2024) — https://tally.so/terms
- Formspree Free: "limited to 50 submissions/mo.", unlimited forms, email per submission (2 linked emails), basic spam filtering. Paid: Personal $10, Professional $20, Business $60 per month (billed annually). [verified] — https://formspree.io/plans
- Formspree terms: no free-plan commercial restriction found. [verified] (last updated 2022-12-20) — https://formspree.io/legal/terms-of-service

### Naver Form
- No official Naver Form help page could be fetched (naver.com is not reachable by the research tool). Do not write steps for it. [unverified]

### KakaoTalk channel chat
- Kakao developer docs: to open a 1:1 chat with a channel from a web page, use `Kakao.Channel.createChatButton()` (Kakao's button) or `Kakao.Channel.chat()` (your own button), with the channel ID in `channelPublicId`; needs a "JavaScript 키" and registered "JavaScript SDK 도메인"; if the user is not logged in, Kakao login runs first. [verified] — https://developers.kakao.com/docs/ko/kakaotalk-channel/js
- A plain link of the form `https://pf.kakao.com/{id}/chat` is not documented on that page. [verified] — same URL
- Kakao Business guide: in 채널 정보, "채널의 URL과 채팅방으로 가는 URL을 확인할 수 있습니다." [verified] — https://kakaobusiness.gitbook.io/main/channel/run/mychannel
- Exact menu path and copy button for the chat URL in the admin center: not confirmed. [unverified]

## V3. Small database with owner login

### Supabase
- Free ($0/month): 2 active projects, 500 MB database, 1 GB file storage, 5 GB egress (+5 GB cached), 50,000 monthly active users for Auth, no automatic backups; "Free projects are paused after 1 week of inactivity." Pro from $25/month. [verified] — https://supabase.com/pricing
- "You are entitled to two active free projects." "We accept credit card payments only." No statement that a card is required for Free. [verified] — https://supabase.com/docs/guides/platform/billing-faq
- Pausing: "Supabase pauses Free Plan projects that show low activity over a 7-day period"; "a few user requests to the database each day over the previous week is enough"; warning email "roughly one week before the pause"; restore with "Resume project"; "You can restore a paused project for up to 1 year after it was paused." Paid projects are not paused for inactivity. [verified] — https://supabase.com/docs/guides/platform/free-project-pausing
- Terms of Service: no Free-plan or non-commercial restriction found; §2(a) limits use to internal business purposes for all customers. No date shown on the page. [verified] — https://supabase.com/terms
- Region list includes "Northeast Asia (Seoul), ap-northeast-2"; "Each Supabase project is deployed to one primary region". [verified] — https://supabase.com/docs/guides/platform/regions
- Auth supports "password, magic link, one-time password (OTP), social login, and single sign-on (SSO)"; "The Auth Token scopes database access on a row-by-row level when used along with RLS policies." [verified] — https://supabase.com/docs/guides/auth
- Built-in email: "Supabase Auth will refuse to deliver messages to addresses that are not part of the project's team"; rate limit "2 messages per hour"; "not meant for production use". [verified] — https://supabase.com/docs/guides/auth/auth-smtp
- For one owner who is a project team member, the built-in email can still send that owner's login mail. [inferred] — same URL

### Row Level Security (RLS) and keys
- RLS "gives you granular authorization rules that run inside the database." "Enable RLS on every table in an exposed schema." "A table in an exposed schema without RLS is readable and writable by any role with a grant on it." [verified] — https://supabase.com/docs/guides/database/postgres/row-level-security
- "Once RLS is enabled, no data is accessible through the API when using a publishable key, until you create policies." Roles: "anon: an unauthenticated request (the user is not signed in)"; "authenticated: an authenticated request (the user is signed in)". [verified] — same URL
- A policy `to anon` exposes data to every unauthenticated visitor: "Use it only for data that is meant to be public." "Always name the role a policy applies to, using the to clause." Example policy uses `to authenticated using ( (select auth.uid()) = user_id )`. [verified] — same URL
- `service_role` has "Full access. It bypasses RLS, so keep it server-side." "Never use a secret key in the browser or expose it to customers." [verified] — same URL
- Publishable key: "Safe to expose online: web page, mobile or desktop app…"; "Anyone can read it, so it only reaches what Row Level Security allows." Secret key: "Exposing a secret key puts all of your project's data at risk." "Never put one in a browser, a shipped application, or source control." [verified] — https://supabase.com/docs/guides/api/api-keys
- "Supabase is deprecating the anon and service_role keys by the end of 2026." Writers should use the names "publishable key" and "secret key". [verified] — same URL
- A ready-made policy that lets anonymous visitors only INSERT (not read) is not shown on the RLS page; Claude would have to write and the reader would have to test it. [verified] (absence) — https://supabase.com/docs/guides/database/postgres/row-level-security

### Firebase Spark (brief)
- Spark: "No payment method needed." Firestore: 1 GiB stored, 50K reads/day, 20K writes/day, 20K deletes/day. Authentication: 50K MAUs. Hosting: 10 GB storage, 360 MB/day transfer, custom domain & SSL included. [verified] — https://firebase.google.com/pricing
- Firebase commercial-use terms were not checked. [unverified]

## V4. Domains and DNS

- .kr: "국제표준(ISO-3166-410)에 의해 대한민국 국민이 등록할 수 있는 영문 국가 최상위 도메인입니다." "신청인 및 등록인은 대한민국에 주소지가 있어야 합니다." [verified] — https://krnic.kisa.or.kr/jsp/resources/domainInfo/krDomainInfo.jsp
- .kr types: 2단계 (도메인.kr, no middle part) and 3단계 (e.g. kisa.or.kr). Middle-part eligibility: co.kr "법인 또는 개인", or.kr "비영리 법인·단체", pe.kr "개인". [verified] — same URL
- Exact character rules for 2단계 .kr (Hangul vs English, length): the page table could not be read reliably. [unverified]
- You register a .kr domain through a 등록대행자: "등록대행자는 인터넷주소자원에 관한 법률에 근거하여 한국인터넷진흥원과 등록대행계약을 맺은 업체입니다." Fees and services differ by registrar, so compare first. [verified] — https://krnic.or.kr/jsp/business/management/domain/regAgencyInfo.jsp
- Registration details other than the domain name are changed through the domain's 등록대행자; individuals and sole proprietors can hide address and phone in WHOIS. [verified] — https://krnic.kisa.or.kr/jsp/infoboard/faq/domainModifyList.jsp
- Current list of .kr registrars and prices: not fetched (popup page). KRNIC statistics mention 15 registrars as of 2026-09. [unverified]
- .com (generic domains) "may be registered with one of more than two thousand ICANN-accredited registrars, or their resellers"; country domains "can be made through the ccTLD operators". [verified] — https://www.icann.org/resources/pages/register-domain-name-2017-06-20-en
- Typical DNS step at the host: add the domain in the host's dashboard, then at the registrar set an A record (apex) or CNAME (subdomain) to the value the host shows, or switch nameservers to the host; wait for propagation. [verified for Vercel and Cloudflare] — https://vercel.com/docs/domains/working-with-domains/add-a-domain , https://developers.cloudflare.com/pages/configuration/custom-domains/
- Before switching nameservers, copy existing DNS records "including MX records for email"; changing only the A or CNAME does not move other records. [verified] — https://vercel.com/docs/domains/working-with-domains/add-a-domain

## V5. Claude Code features for this track

- Project CLAUDE.md lives in `./CLAUDE.md` or `./.claude/CLAUDE.md`; it is for "Team-shared instructions for the project" and is shared "through version control". `CLAUDE.local.md` is for personal notes; add it to `.gitignore`. [verified] — https://code.claude.com/docs/en/memory.md
- "Run /init to generate a starting CLAUDE.md automatically"; if one exists, `/init` suggests improvements instead of overwriting. Size: "target under 200 lines per CLAUDE.md file." Run `/context` to confirm it loaded. [verified] — same URL
- `/memory`: "Edit CLAUDE.md files, enable or disable auto memory, and view auto memory entries". [verified] — https://code.claude.com/docs/en/commands.md
- CLAUDE.md is context, not enforced configuration; to block an action regardless, use a hook. [verified] — https://code.claude.com/docs/en/memory.md
- Git by conversation (quickstart examples): "what files have I changed?", "commit my changes with a descriptive message", "create a new branch called feature/quickstart", "show me the last 5 commits". [verified] — https://code.claude.com/docs/en/quickstart.md
- Recommended flow: Explore → Plan → Implement → Commit ("commit with a descriptive message and open a PR"). Plan mode: press Shift+Tab until `⏸ plan mode on`, or `claude --permission-mode plan`; Ctrl+G opens the plan in a text editor. "If you could describe the diff in one sentence, skip the plan." [verified] — https://code.claude.com/docs/en/best-practices.md
- Checkpoints "only track changes made through Claude's file editing tools. Changes made through Bash commands or external processes are not captured. This isn't a replacement for git." [verified] — same URL
- "Give Claude a check it can run: tests, a build, a screenshot to compare." "If you can't verify it, don't ship it." [verified] — same URL
- Use CLI tools: "If you use GitHub, install the gh CLI. Claude knows how to use it for creating issues, opening pull requests, and reading comments." [verified] — same URL
- Shell mode: start input with `!` to "Run shell commands directly without going through Claude" (e.g. `! git status`); output is added to the conversation; leave with Escape, Backspace or Ctrl+U on an empty prompt. [verified] — https://code.claude.com/docs/en/interactive-mode.md
- Block `.env` reads: add `"deny": ["Read(./.env)", "Read(./.env.*)"]` under `permissions` in a settings file. [verified] — https://code.claude.com/docs/en/settings.md
- Read/Edit deny rules apply to Claude's file tools and to Bash file commands such as `cat`, `head`, `tail`, `sed`, `tee`, but not to a script that opens files itself; for full blocking enable the sandbox. A `.claudeignore` file "has no effect". [verified] — https://code.claude.com/docs/en/permissions.md
- "Never commit API keys or OAuth tokens directly to your repository. Always store them as GitHub Secrets" (GitHub Actions page). [verified] — https://code.claude.com/docs/en/github-actions.md
- `/install-github-app` sets up the Claude GitHub App and Actions; works only with github.com; needs the GitHub CLI authenticated with `gh auth login` and repo admin access. Optional for this track. [verified] — same URL
- `/security-review`: "Analyze the changes on your current branch for security vulnerabilities"; needs an `origin` remote. [verified] — https://code.claude.com/docs/en/commands.md
- "You're responsible for reviewing proposed code and commands for safety before approval." [verified] — https://code.claude.com/docs/en/security.md
- Auto mode blocks production deploys by default, so a deploy command may need the reader's approval. [verified 2026-10-20, not re-fetched; see FACTS.md §E] — https://code.claude.com/docs/en/permission-modes.md
- No Claude Code doc page found that says "never paste an API key into the chat". Use the Supabase and GitHub Actions lines above as the official basis for secret handling. [unverified]
- No dedicated Claude Code "deploy a website" guide was found. [unverified]

## V6. Korean privacy law must-knows (개인정보 보호법)

- Current text checked: 개인정보 보호법, 법률 제21445호 (2026. 3. 10. 일부개정), 시행 2026. 9. 11. [verified] — https://www.law.go.kr/LSW/lsLawLinkInfo.do?lsJoLnkSeq=900078940&lsId=011357&chrClsCd=010202&print=print
- 제15조① lets a 개인정보처리자 collect personal information on listed grounds (동의, 법령, 공공기관 업무, 계약 이행, 급박한 생명·신체·재산 보호, 정당한 이익, 공공의 안전) and use it within the purpose. [verified] — same URL
- 제15조②: "개인정보처리자는 제1항제1호에 따른 동의를 받을 때에는 다음 각 호의 사항을 정보주체에게 알려야 한다." The four items: 수집·이용 목적, 수집 항목, 보유·이용 기간, 동의 거부권과 거부에 따른 불이익. Changes need new notice and consent. [verified] — same URL
- 제16조①: collect only the minimum needed; "이 경우 최소한의 개인정보 수집이라는 입증책임은 개인정보처리자가 부담한다." [verified] — https://www.law.go.kr/LSW//lsLawLinkInfo.do?chrClsCd=010202&lsJoLnkSeq=900078586&lsId=011357&print=print
- 제16조② (tell people they may refuse anything beyond the minimum) and ③ (no refusing service for that): seen only in a law.go.kr search snippet. [unverified]
- 제21조①: "개인정보처리자는 보유기간의 경과, 개인정보의 처리 목적 달성 … 그 개인정보가 불필요하게 되었을 때에는 지체 없이 그 개인정보를 파기하여야 한다." [verified] — same URL
- 제22조①: consent items must be separated "정보주체가 이를 명확하게 인지할 수 있도록 알리고 동의를 받아야 한다." 제22조③: information processed without consent must be shown separately with its legal basis; "동의 없이 처리할 수 있는 개인정보라는 입증책임은 개인정보처리자가 부담한다." [verified] — same URL
- 제22조의2 (children under 14, guardian consent): text not fetched. [unverified]
- 제30조① privacy policy (개인정보 처리방침) must cover, among others: "개인정보의 처리 목적", "개인정보의 처리 및 보유 기간", "개인정보의 파기절차 및 파기방법", "개인정보처리의 위탁에 관한 사항(해당되는 경우에만 정한다)", rights of data subjects, and the 개인정보 보호책임자 or the department's contact. ②: publish it "정보주체가 쉽게 확인할 수 있도록". [verified] — https://www.law.go.kr/LSW/lsLawLinkInfo.do?chrClsCd=010202&lsJoLnkSeq=900078922
- PIPC portal: "개인정보를 수집 할 때는 정보주체의 동의를 받아야 하며, 수집・이용 목적, 수집 항목, 보유 및 이용 기간, 동의 거부권 등을 알려야 함." "개인정보를 수집할 때는 필요 최소한으로 수집해야 함." [verified] — https://www.privacy.go.kr/front/contents/cntntsView.do?contsNo=36
- PIPC rules for small shops (고객관리 프로그램 이용 시): "업무 목적에 필요한 최소한의 고객정보만 수집하고, 보유기간이 만료된 개인정보는 삭제하세요." "회원가입서 등에 개인정보를 받을 때에는 수집항목, 보유기간, 수집목적, 동의거부가 가능함을 알려주고 동의를 받으세요." "개인정보처리방침을 만들고, 홈페이지(또는 사업장)에 게시하세요." Passwords: at least 8 characters with mixed types (10 with one type); give each employee their own ID. [verified] — https://www.privacy.go.kr/front/contents/cntntsView.do?contsNo=82
- PIPC 2024-09-12 press release 「개인정보 필수동의 관행 개선한다」: "개인정보처리자는 서비스 이용 등 계약과 관련하여 필요한 개인정보는 정보주체에게 동의를 요구할 필요가 없다." The processor bears the burden of proof (법 §22③) and must show consent-based and non-consent items separately. [verified] — https://www.pipc.go.kr/np/cop/bbs/selectBoardArticle.do?bbsId=BS074&mCode=C020010000&nttId=10566
- Whether a shop's reservation request counts as "계약 관련 필요 정보" (no consent needed) is a legal judgment; the manual should not decide it. The simple safe pattern the PIPC small-shop page describes is a consent notice with items, purpose, retention and the right to refuse. [inferred] — https://www.privacy.go.kr/front/contents/cntntsView.do?contsNo=82
- Current PIPC guides include 「개인정보 처리방침 작성지침(2026.4. 개정)」 (posted 2026-04-23) and 「개인정보 처리방침 표준(안)(2026.2.)」. [verified] — https://pipc.go.kr/np/cop/bbs/selectBoardList.do?bbsId=BS217&mCode=D010030000
- 「알기쉬운 개인정보 처리 동의 안내서」 (PIPC, 2022.3.) replaced the 2020 minimum-collection and online-processing guidelines; the page shows no newer version. [verified] — https://www.privacy.go.kr/front/bbs/bbsView.do?bbsNo=BBSMSTR_000000000049&bbscttNo=13156
- Storing Korean customers' data with overseas services (Google, Netlify, Supabase outside Seoul) may raise 처리 위탁 / 국외 이전 duties (e.g. 제28조의8); those articles were not fetched. [unverified]

## V7. Git and GitHub basics

- "Version control is a system that records changes to a file or set of files over time so that you can recall specific versions later." It lets you "revert the entire project back to a previous state, compare changes over time". [verified] — https://git-scm.com/book/en/v2/Getting-Started-About-Version-Control
- "Similar to saving a file that's been edited, a commit records changes to one or more files in your branch." "When you make a commit, you must include a commit message that briefly describes the changes." [verified] — https://docs.github.com/en/pull-requests/committing-changes-to-your-project/creating-and-editing-commits/about-commits
- "A repository is the most basic element of GitHub." "Public repositories are accessible to everyone on the internet." "Private repositories are only accessible to you, people you explicitly share access with" (and certain org members). [verified] — https://docs.github.com/en/repositories/creating-and-managing-repositories/about-repositories
- GitHub Free: "unlimited public repositories with a full feature set" and "unlimited private repositories with a limited feature set". [verified] — https://docs.github.com/en/get-started/learning-about-github/githubs-plans

## Not confirmed / changes often

- All prices, credit counts and free limits above (Vercel, Netlify, Cloudflare, Supabase, Firebase, Tally, Formspree) change often; recheck on the publish date.
- Naver Form steps; KakaoTalk chat-URL copy location; .kr registrar list and prices; Netlify Free sign-up without a card; Firebase commercial terms; 개인정보 보호법 제16조②③, 제22조의2, 국외 이전 rules.

## Recommendation inputs (only from the facts above)

Allowed for commercial use on the free tier (no commercial restriction found in the official terms fetched):
- Netlify Free · Cloudflare Pages / Workers Free · Google Forms (Google ToS covers business use) · Tally Free · Formspree Free · Supabase Free.
Not allowed or poor fit on the free tier:
- Vercel Hobby: explicitly non-commercial; a shop page "advertising the sale of a product or service" needs Pro ($20/mo).
- GitHub Pages: not allowed "to run your online business"; on GitHub Free it needs a public repository, so all page code is public.

Simplest beginner combinations:
1. Netlify Free + Netlify Forms. One service hosts the page, stores inquiries (forms free and unlimited), emails the owner, and the Netlify dashboard acts as the owner-only view. No secret keys in the page. Trade-offs: 300 credits/month hard limit, 15 credits per production deploy (about 20 deploys a month at most), and the whole site shows "Site not available" if credits run out. The owner view is Netlify's dashboard, not a page we build.
2. Cloudflare (Workers static assets or Pages) + embedded Google Form → Google Sheet. Static hosting is free and unlimited; the owner reads the Sheet behind a Google login; email alert per response. No secret keys. Trade-offs: the form looks like Google Forms; an apex custom domain needs nameservers moved to Cloudflare; Free Services carry no liability or support promise.
3. For lessons v04–v06 (save data, secret keys, owner login): Netlify or Cloudflare + Supabase Free (Auth + RLS, Seoul region available). Teaches a real database and login. Trade-offs: Supabase Free pauses after 7 days of low activity (a quiet shop could be paused; warning email first; resume within 1 year; Pro $25/mo avoids it); no automatic backups on Free; RLS must be enabled and tested or the table is open; only the publishable key may go in the page, never the secret key; built-in login email reaches team members only, 2 per hour.
- Formspree Free (50 submissions/month) and Tally Free (Tally branding) are fallbacks if the reader does not want Google or Netlify.
- Whatever the combination: the inquiry form must show 수집 항목·목적·보유 기간·동의 거부권 (제15조②), collect the minimum (제16조①), have a 개인정보 처리방침 (제30조), and delete data when the retention period ends (제21조①).

## V8. Round 2 — Vercel + Supabase (2026-10-21)

Owner decision (Jake, 2026-10-21): Vercel hosts the page; Supabase stores requests and handles the owner login; plain HTML/CSS/JS (no framework) built by Claude Code on the 일손 Box Mac; code in a private GitHub repository. Customers leave a 예약·문의 request; the owner signs in to a private page to read them.
Same line format and tags as above. Exact English UI labels are in **bold** with a Korean gloss in (괄호). Lines in V1/V3/V5/V7 are not repeated unless re-quoted here.

### V8.1 Vercel — plans and commercial use (re-quoted)
- "**Hobby teams** are restricted to non-commercial personal use only. All commercial usage of the platform requires either a Pro or Enterprise plan." [verified] (page date 2026-09-14) — https://vercel.com/docs/limits/fair-use-guidelines
- Commercial usage = "any Deployment that is used for the purpose of financial gain of **anyone** involved in **any part of the production** of the project, including a paid employee or consultant writing the code." Examples: "Any method of requesting or processing payment from visitors of the site", "Advertising the sale of a product or service", "Receiving payment to create, update, or host the site", "Affiliate linking is the primary purpose of the site", "The inclusion of advertisements…". "Asking for Donations **does not** fall under commercial usage." If unsure, "contact the Vercel Support team". [verified] — same URL
- A real shop's 예약·문의 page advertises the shop's service, so it is commercial usage → Pro or Enterprise. A practice page for the fictional 햇살꽃집 that no real business uses stays personal, non-commercial. [inferred] — same URL
- Pricing page: Hobby "$0/mo." ("The perfect starting place for your web app or personal project."); Pro "$20/mo." ("Everything you need to build and scale your app."). FAQ: "Our Hobby plan is for personal, non-commercial use."; "If you have a free Hobby account, you are limited to the usage caps and cannot purchase additional usage."; "Pro plans have a $20 included credit to use across resources." [verified] — https://vercel.com/pricing
- Pro = "$20/month Pro platform fee" with "1 deploying team seat included" and "$20/month in usage credit"; extra deploying seats $20/month each; Viewer seats free; unused credit "expires at the end of the month"; email at 75% of the credit; spend notifications on by default at "$200 per billing cycle"; prices "exclude value-added tax (VAT)". [verified] (page date 2026-09-15) — https://vercel.com/docs/plans/pro
- Paid Pro teams get "one free first-year domain" on `.app`, `.dev`, `.online`, `.site`, `.space`, `.store`, `.tech` or `.website`; not during a Pro trial; renews at the standard rate. [verified] — same URL
- Pro trial: "14 days of Pro premium features and collaboration for free". [verified] (page date 2026-09-21) — https://vercel.com/docs/accounts
- Upgrade: **Settings**(설정) → **Billing**(결제) → **Upgrade**(업그레이드) → "Enter your card details" → **Confirm and Upgrade**(확인 후 업그레이드). Downgrade: Settings → Billing → **Downgrade Plan**(플랜 낮추기). [verified] — https://vercel.com/docs/plans/hobby , https://vercel.com/docs/plans/pro
- Hobby vs Pro: projects 200 vs Unlimited; deployments per day 100 vs 6,000; domains per project 50 vs Unlimited; runtime logs 1 hour vs 1 day; Email support "-" vs "Yes"; Password Protection not on Hobby, "$20 per month per protected project" on Pro. [verified] (page date 2026-09-14) — https://vercel.com/docs/plans/hobby
- Hobby allowances that matter for a tiny static site: Fast Data Transfer "First 100 GB", CDN Requests "First 1,000,000" per month; over a limit "you will have to wait until 30 days have passed before you can use the feature again." [verified] — same URL
- Conflict: the pricing page shows Pro CDN Requests "10M / month included"; the Pro plan doc says Flat Rate CDN gives "1 million CDN requests and 1 TB of data transfer each month". Lessons should not quote a Pro request number. [verified, conflicting] — https://vercel.com/pricing , https://vercel.com/docs/plans/pro

### V8.2 Vercel — sign up, connect GitHub, deploy plain HTML
- Sign-up page buttons: **Continue with Google**, **Continue with GitHub**(GitHub로 계속하기), **Continue with ChatGPT**, **Continue with Apple**, **Show other options**, **Continue with Email →**. No plan choice is shown on that page. [verified] — https://vercel.com/signup
- "When signing up for Vercel, you can choose to sign up with an email address or a Git provider." Git provider: "Authorize Vercel to access your Git provider account. This will be the default login connection on your account." Email sign-up with no Git provider connected: "you will be asked to verify your account on every login attempt." [verified] — https://vercel.com/docs/accounts
- Dashboard deploy: "Go to the New Project page, connect your GitHub, GitLab, or Bitbucket account, select a repo, and click **Deploy**. Every push to your connected branch triggers a new deployment automatically." [verified] (page date 2026-08-11) — https://vercel.com/docs/getting-started-with-vercel
- Import flow: **New Project**(새 프로젝트) → list of repositories from connected Git providers → set project name, **Framework Preset**(프레임워크 프리셋), root directory, Build Output Settings, Environment Variables → **Deploy**(배포). [verified] (page date 2026-09-18) — https://vercel.com/docs/git
- Repository missing from the list: click **Configure GitHub App** on the import screen (or GitHub Settings → Applications); if "Only select repositories" was chosen, add the repository and save. [verified] (updated 2026-10-16) — https://vercel.com/kb/guide/unable-to-find-github-repository
- Private repos on Hobby: "You cannot deploy to a Hobby team from a private repository in a GitHub organization, GitLab group, or Bitbucket workspace." The private-repo author check "does not apply to collaborators on personal Git accounts." [verified] — https://vercel.com/docs/git
- So a private repository owned by the reader's personal GitHub account deploys on Hobby; one owned by a GitHub organization needs Pro. [inferred] — same URL
- Importing a personal-account repository requires being its **Owner**; "A Collaborator on a personal repository cannot create new Vercel projects from that repository". [verified] (page date 2026-09-17) — https://vercel.com/docs/git/vercel-for-github
- "For static websites (HTML, CSS, and client-side JavaScript only), no build step is required." Steps: set **Framework Preset** to **Other**(기타), leave the build command blank, optionally override **Output Directory**. [verified] (page date 2026-09-03) — https://vercel.com/docs/builds
- "Other" serves `public` if it exists, otherwise `.` (the repository root). "If no framework is detected, "Other" will be selected", with the Build Command **Override** toggle switched on. [verified] (page date 2026-08-28) — https://vercel.com/docs/deployments/configure-a-build
- The CLI route (`npm i -g vercel`, `vercel login`, `vercel --prod`) lists "Node.js 18+" as a prerequisite. [verified] — https://vercel.com/docs/getting-started-with-vercel

### V8.3 Vercel — automatic deploys, preview vs production, rollback
- "Vercel for GitHub will **deploy every push by default**. This includes pushes and pull requests made to branches." [verified] — https://vercel.com/docs/git/vercel-for-github
- Production branch is chosen in order: `main`, else `master`, else the repository's default branch; change it at Settings → **Environments** → **Production** → **Branch Tracking**. [verified] — https://vercel.com/docs/git
- Default environments: **Local**, **Preview** ("deploying for further testing, QA, or collaboration without impacting your live site"), **Production** ("deploying the final changes to your user-facing site with the production domain"). A preview is made when you push to a non-production branch, open a pull request, or run `vercel` without `--prod`. [verified] (page date 2026-09-17) — https://vercel.com/docs/deployments/environments
- "The first deployment of a new project is always a **production** deployment." [verified] — same URL
- Instant Rollback: production deployment tile → **Instant Rollback**(즉시 되돌리기) → pick a deployment → **Continue** → **Confirm Rollback**. "Hobby users can roll back to the immediately previous deployment"; Pro and Enterprise can use **Choose another deployment**. [verified] (page date 2026-07-07) — https://vercel.com/docs/instant-rollback
- "After a rollback, Vercel turns off auto-assignment of production domains. This means new pushes to your production branch won't replace the rolled-back deployment." Restore with **Undo Rollback**(되돌리기 취소) → select a deployment → **Confirm**. [verified] — same URL
- "If you decide to revert a commit that has already been deployed to production, the previous Production Deployment from a commit will automatically be made available at the Custom Domain instantly". [verified] — https://vercel.com/docs/git/vercel-for-github

### V8.4 Vercel — environment variables and the browser
- Env vars are "key-value pairs configured outside your source code"; "Your source code can read these values to change behavior during the Build Step or during Function execution." Changes apply only to new deployments. Each is **Config** or **Secret** (Secret is write-only after saving). [verified] (page date 2026-09-17) — https://vercel.com/docs/environment-variables
- "Environment variables remain private within the build environment." [verified] (page date 2026-09-03) — https://vercel.com/docs/builds
- "Frameworks typically use a prefix to expose environment variables to the browser" (`NEXT_PUBLIC_` for Next.js, `PUBLIC_` for SvelteKit); prefixed variables are "available during the **build step**, based on the project's selected framework preset." [verified] (page date 2026-09-16) — https://vercel.com/docs/environment-variables/framework-environment-variables
- A plain HTML site with Framework Preset "Other" and no build command has no step that writes values into the page, so browser JavaScript cannot read Vercel env vars. No Vercel page says this for "Other" in one sentence. [inferred] — https://vercel.com/docs/builds , same URL
- That is fine here: the Supabase URL and publishable key may sit in the page source (V8.9), and the track never needs a secret key. [inferred]

### V8.5 Vercel — Deployment Protection
- "Deployment Protection is now enabled by default for all new projects"; "For all new deployments, Deployment Protection with Vercel Authentication is now enabled by default." [verified] (changelog 2023-11-02) — https://vercel.com/changelog/deployment-protection-is-now-enabled-by-default-for-new-projects
- Scopes: "**Standard Protection**: Protects all deployments **except** production domains" (all plans; "the recommended option for most projects"); "**All Deployments**: Protects **all** URLs, including production domains" (all plans). Password Protection: "Not available on Hobby". Path: **Settings** → **Deployment Protection**(배포 보호). [verified] (page date 2026-09-15) — https://vercel.com/docs/deployment-protection
- Visitors to a protected URL "encounter a Vercel login redirect"; access is for logged-in team or project members, granted users, holders of a Shareable Link. Hobby: "only have one external user per account". [verified] — https://vercel.com/docs/deployment-protection/methods-to-protect-deployments/vercel-authentication
- Vercel guide: "By default, Vercel Authentication is automatically enabled for all deployments with the exception of the most recent production deployment." [verified] (updated 2026-10-16) — https://vercel.com/kb/guide/locking-down-deployments
- So customers can open the production address, but a preview link or an older deployment URL asks for a Vercel login. Share only the production address; check the project's Deployment Protection page because the two pages above word the default differently. [inferred] — same URLs
- Protection is set per project, so **All Deployments** would also lock the customer page. The owner page's data must be protected by Supabase login + RLS, not by Vercel. [inferred] — https://vercel.com/docs/deployment-protection

### V8.6 Vercel — custom domain
- Project → **Settings** → **Domains**(도메인) → **Add Domain**(도메인 추가) → type the domain. Adding an apex (example.com) prompts you to add the `www` subdomain too. [verified] (page date 2026-09-16) — https://vercel.com/docs/domains/working-with-domains/add-a-domain
- Apex → **A** record; subdomain → **CNAME** ("Each project has a unique CNAME record e.g. `d1d4fc829fe7bc7c.vercel-dns-017.com`"); or the **Nameservers** method. A domain used by another Vercel account is verified with a **TXT** record at `_vercel`. [verified] — same URL
- The page's related-guide summary: "Point your apex domain to Vercel with an A record (76.76.21.21 or your domain card's value)". Lessons should say "copy the value shown on your domain card". [verified] — same URL
- "DNS changes can take time to propagate." Before changing nameservers, copy existing records "including MX records for email and any verification TXT records". [verified] — same URL

### V8.7 Supabase — project, editors, and the 2026 "tables not exposed" change
- Official quickstart: create a project "from the Dashboard of any organization you belong to", then open the **SQL Editor**, paste the snippet and run it. [verified] — https://supabase.com/docs/guides/getting-started/quickstarts/reactjs
- Exact new-project form labels (organization, project name, database password, region, create button) are not on any official page fetched; third-party guides agree on name / database password / region. [unverified]
- Seoul region: "Northeast Asia (Seoul), `ap-northeast-2`"; "Choose the location closest to your users for the best performance." The page does not say the region can be changed later. [verified] — https://supabase.com/docs/guides/platform/regions
- Table Editor = "Visually using the Table Editor section of the Dashboard"; SQL Editor = "With query syntax using the SQL Editor section", for "ad-hoc queries and saved snippets". [verified] — https://supabase.com/docs/guides/database/overview
- Table Editor: **New table**(새 테이블) → **Name** → **Add column** → **Save**. "The Table Editor enables row level security for you when you create a table in the Dashboard." "When you create a table with SQL, enable it yourself." [verified] — https://supabase.com/docs/guides/database/tables
- Breaking change (post dated 2026-04-28): new projects can be created where `public` tables "are not exposed" to the Data API; "On **May 30, 2026** this setting starts to become the default for all new projects"; "On **October 30, 2026** the setting will be applied it to all existing projects" (sic). Creation checkbox: "**Automatically expose new tables**"(새 테이블 자동 공개). [verified] — https://supabase.com/changelog/45329-breaking-change-tables-not-exposed-to-data-and-graphql-api-automatically
- Without a grant the Data API returns "42501" "permission denied for table your_table", with a hint showing the GRANT to run. Recommended order: grant → enable RLS → add a policy. [verified] — same URL
- "Grants decide whether a role can reach a table or view at all. RLS policies decide which rows that role can read or modify"; use both. Existing tables keep their grants. [verified] — https://supabase.com/docs/guides/api/securing-your-api
- The official quickstart SQL now runs `grant select on public.instruments to anon;` before `alter table instruments enable row level security;` and a `for select to anon using (true)` policy. [verified] — https://supabase.com/docs/guides/getting-started/quickstarts/reactjs
- So every table in this track needs explicit GRANT lines; SQL from older tutorials (no GRANT) fails with 42501 on a project created now. [inferred] — same URLs

### V8.8 Supabase — RLS for "customers send, owner reads"
- Enable RLS: `alter table public.reports enable row level security;` — "Run the following SQL using the SQL Editor in the Supabase Dashboard". [verified] — https://supabase.com/docs/guides/database/postgres/row-level-security
- Official policy shapes: insert `for insert to authenticated with check ( (select auth.uid()) = user_id )`; select `for select to authenticated using ( … )`; update `for update to authenticated using ( … ) with check ( … )` ("checks the existing row" / "checks the resulting row"); public read `to anon, authenticated using ( true )` with "Use it only for data that is meant to be public." [verified] — same URL
- No official example lets `anon` insert without reading. [verified, absence] — same URL
- Composed from official pieces (test before teaching; not official text): `grant insert on public.requests to anon;` plus `create policy "customers can send" on public.requests for insert to anon with check ( true );`; `grant select, update on public.requests to authenticated;` plus select and update policies `to authenticated`. [inferred] — https://supabase.com/docs/guides/api/securing-your-api , same URL
- `to authenticated using ( true )` lets any signed-in user read. With public sign-ups off (V8.11) that is only the owner, but checking the owner's user id (`(select auth.uid()) = '<owner id>'`) is stricter. [inferred] — same URL
- "By default, inserted rows are not returned. To return it, chain the call with `.select()`." Example: `supabase.from('countries').insert({ id: 1, name: 'Mordor' })`. [verified] — https://supabase.com/docs/reference/javascript/insert
- The customer form must not chain `.select()`, because `anon` has no read policy. [inferred] — same URL

### V8.9 Supabase — API keys today
- Names: **publishable key** `sb_publishable_...` and **secret key** `sb_secret_...` ("short strings, not JWTs"); legacy `anon` and `service_role` are long JWTs starting `eyJ`. "Supabase is deprecating the `anon` and `service_role` keys by the end of 2026." [verified] — https://supabase.com/docs/guides/api/api-keys
- Publishable: "Safe to expose online: web page, mobile or desktop app, GitHub actions, CLIs, source code." Secret: "Never put one in a browser, a shipped application, or source control." [verified] — same URL
- Where: **Settings** → **API Keys**(API 키) (there is "no separate Settings > API page"), or the **Connect**(연결) dialog for the project URL and publishable key; if a project has none, create them on API Keys. [verified] — same URL
- Leak: "Delete a leaked key immediately" (deletion can't be undone); create a new key, replace it everywhere, then delete the old one; a legacy key is deactivated instead. [verified] — same URL
- This track needs only the project URL + publishable key; customer insert and owner login both work through RLS. [inferred]

### V8.10 Supabase — supabase-js in a plain HTML page
- CDN: `<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>` (or the unpkg URL). Tables must be exposed (Data API settings or SQL grants) before queries work. [verified] — https://supabase.com/docs/reference/javascript/installing
- Global: `const { createClient } = supabase` then `createClient('https://xyzcompany.supabase.co', 'your-publishable-key')`. ESM: `import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm'` in `<script type="module">`. [verified] — https://github.com/supabase/supabase-js/blob/master/packages/core/supabase-js/README.md
- Reference: "Create a new client for use in the browser." Example key placeholder is `'your-publishable-key'`. [verified] — https://supabase.com/docs/reference/javascript/initializing
- `@2` always loads the newest 2.x; pinning an exact version keeps a finished page from changing under the owner. [inferred]

### V8.11 Supabase — owner login
- Password: `supabase.auth.signInWithPassword({ email, password })`; `signUp` exists too. Confirm email: "On hosted Supabase projects, this is true by default." [verified] — https://supabase.com/docs/guides/auth/passwords
- Magic link: `supabase.auth.signInWithOtp({ email, options: { shouldCreateUser: false, emailRedirectTo: '…' } })`; "a user can only request a magic link once every 60 seconds and they expire after 1 hour"; only the Site URL and Redirect URLs on the URL Configuration page are allowed after the click. [verified] — https://supabase.com/docs/guides/auth/auth-email-passwordless
- **Allow new users to sign up**(새 사용자 가입 허용): "If this config is disabled, only existing users can sign in." On the Auth general configuration page. [verified] — https://supabase.com/docs/guides/auth/general-configuration
- Add the owner: **Authentication** → **Users** → **Add user**(사용자 추가) → **Send invitation**(초대 보내기) → email → **Invite user**. A "Create new user" / auto-confirm option is not on that page. [verified; other option unverified] — https://supabase.com/docs/guides/auth/users (the dashboard does offer **Create new user** with **Auto confirm user?**: see V8.17)
- Sign out: `const { error } = await supabase.auth.signOut()` (all sessions by default; `{ scope: 'local' }` for this browser only). [verified] — https://supabase.com/docs/reference/javascript/auth-signout
- Built-in email: "Supabase Auth will refuse to deliver messages to addresses that are not part of the project's team"; "2 messages per hour"; "not meant for production use"; "No SLA guarantee". [verified] — https://supabase.com/docs/guides/auth/auth-smtp
- Rate limits: "2 emails per hour with the built-in email provider"; OTP/magic link "60 seconds window" per user; sign-up/sign-in "30 requests per 5 minutes" per IP; change at **Authentication** → **Rate Limits**. [verified] — https://supabase.com/docs/guides/auth/rate-limits
- The owner who created the Supabase project is on its team, so the invite and magic links reach them; 2 emails per hour is easy to hit while testing, so after the first invite the owner sets a password and uses password login. [inferred] — same URLs

### V8.12 Supabase — free plan pause, backups
- Pricing: "Free projects are paused after 1 week of inactivity."; "Limit of 2 active projects."; Automatic backups "Not included"; log retention "1 day". Pro "from $25/month" with "$10/month in compute credits"; "Projects on paid plans are not paused for inactivity."; "Daily backups stored for 7 days". [verified] — https://supabase.com/pricing
- Pausing: low activity "over a 7-day period"; "Typically a few user requests to the database each day over the previous week is enough"; warning email "roughly one week before the pause takes effect"; restore: Dashboard → paused project → **Resume project**(프로젝트 재개). "You can restore a paused project for up to 1 year after it was paused" (a heading on the same page says "90-day window"). [verified, page inconsistent] — https://supabase.com/docs/guides/platform/free-project-pausing
- "We automatically back up all Pro, Team, and Enterprise Plan projects on a daily basis." "We recommend that free tier plan projects regularly export their data using the Supabase CLI db dump command and maintain off-site backups." [verified] — https://supabase.com/docs/guides/platform/backups
- The database overview says daily backups are included on every project, which conflicts with the pricing and backups pages; follow the backups page. [verified, conflicting] — https://supabase.com/docs/guides/database/overview
- Beginner-sized backup on Free: a "CSV로 내려받기" button on the owner page (Claude builds it) instead of installing the Supabase CLI. [inferred]

### V8.13 GitHub — private repo, git sign-in, commit and push
- New repository: **+** ("Create something new") → **New repository**(새 저장소) → **Owner** → name (can "only contain ASCII letters, digits, and the characters `.`, `-`, and `_`", max 100) → visibility → optional README, .gitignore, license → **Create repository**(저장소 만들기). Skip those optional files when importing an existing repository. [verified] — https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository
- So a Hangul name like 햇살꽃집 is not allowed; use e.g. `haetsal-booking`. [inferred] — same URL
- GitHub Free: "unlimited private repositories with a limited feature set". [verified in V7] — https://docs.github.com/en/get-started/learning-about-github/githubs-plans
- macOS install: "brew install gh" (official, with "brew upgrade gh"); the releases-page `.pkg` installers are unsigned. [verified] — https://github.com/cli/cli/blob/trunk/docs/install_macos.md
- `gh auth login`: "The default authentication mode is a web-based browser flow." The token is "stored securely in the system credential store". `gh auth login --web --clipboard` copies the one-time code. [verified] — https://cli.github.com/manual/gh_auth_login
- Quickstart: select **GitHub.com**, follow the prompts; "GitHub CLI automatically stores your Git credentials for you when you choose HTTPS". [verified] — https://docs.github.com/en/github-cli/github-cli/quickstart
- "we recommend you use GitHub CLI or Git Credential Manager (GCM) to remember your credentials"; choose HTTPS; "When asked if you would like to authenticate to Git with your GitHub credentials, enter `Y`." [verified] — https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git
- `gh repo create my-project --private --source=. --remote=upstream` ("Create a remote repository from the current directory"); `--push` = "Push local commits to the new repository"; no arguments = interactive. [verified] — https://cli.github.com/manual/gh_repo_create
- GitHub Desktop: download from desktop.github.com and sign in; **Create a New Repository on your Hard Drive...**; commit with **Summary** + **Commit to BRANCH**; **Publish repository** with **Keep this code private**(코드 비공개 유지); **Push origin**. [verified] — https://docs.github.com/en/desktop/installing-and-authenticating-to-github-desktop/setting-up-github-desktop , https://docs.github.com/en/desktop/overview/creating-your-first-repository-using-github-desktop
- Push: "Use git push to push commits made on your local branch to a remote repository"; "you usually run `git push origin main`". Remote: "a remote URL that tells Git where to fetch and push updates." (Commit wording: V7.) [verified] — https://docs.github.com/en/get-started/using-git/pushing-commits-to-a-remote-repository
- Identity: `git config --global user.name "Mona Lisa"` ("Git uses a username to associate commits with an identity"); `git config --global user.email "YOUR_EMAIL"`; GitHub "uses the email address set in your local Git configuration to associate commits". Privacy: Settings → **Emails** → "Keep my email addresses private" (GitHub noreply address). [verified] — https://docs.github.com/en/get-started/git-basics/setting-your-username-in-git , https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address
- Git on macOS: running `git --version` the first time prompts to install the Xcode Command Line Tools. [verified] — https://git-scm.com/book/en/v2/Getting-Started-Installing-Git
- (added 2026-10-21, v01–v04 review) `gh auth login` browser flow, from the GitHub CLI source: without clipboard copy it prints "! First copy your one-time code: <code>" (`cs.Bold(code)`), then "**Press Enter** to open <auth URL> in your browser... " and, in an interactive terminal, opens the browser only after Enter (`waitForEnter` before `Browse`). With `--clipboard` it prints "One-time code (<code>) copied to clipboard" instead. The success-line text is not in that file. [verified] — https://github.com/cli/cli/blob/trunk/internal/authflow/flow.go
- Sign-up: go to "https://github.com/signup" (or "Continue with Google"), "Follow the prompts to create your personal account." "During sign up, you'll be asked to verify your email address." "Without a verified email address, you won't be able to complete some basic GitHub tasks, such as creating a repository." 2FA is "strongly recommend[ed]". [verified] — https://docs.github.com/en/get-started/start-your-journey/creating-an-account-on-github
- "If you do not verify your email address, you cannot:" … "Create or fork repositories", "Authorize OAuth app applications", "Generate personal access tokens", "Receive email notifications" (and more). [verified] — https://docs.github.com/en/account-and-profile/reference/email-addresses-reference
- So both the `gh auth login` approval (an OAuth authorization) and `gh repo create` need a verified GitHub email. [inferred] — same URLs
- noreply address: for accounts created after July 18, 2017 it is "ID+USERNAME@users.noreply.github.com"; selecting "Keep my email address private" in email settings gives the ID-based address. [verified] — https://docs.github.com/en/account-and-profile/reference/email-addresses-reference
- Email settings path: "In the upper-right corner of any page on GitHub, click your profile picture, then click **Settings**." "In the "Access" section of the sidebar, click **Emails**." Option **Keep my email addresses private**. Confirm in Git with `git config --global user.email` (prints the address). [verified] — https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address
- Mandatory 2FA: "As of March 2023, GitHub required all users who contribute code on GitHub.com to enable one or more forms of two-factor authentication (2FA)"; selected users get "a notification email"; "a 45-day 2FA enrollment period", then a 7-day grace period; after it "you will not be able to access GitHub.com until you enable 2FA". [verified] (no page date beyond "As of March 2023") — https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication-2fa/about-mandatory-two-factor-authentication

### V8.14 Claude Code — new project folder, trust, permissions, git
- Start: "Open your terminal in any project directory": `cd /path/to/your/project` then `claude`. [verified] — https://code.claude.com/docs/en/quickstart.md
- "In a repository, Claude Code keys the trust on the git repository root, so the trust covers the whole repository apart from any git repository nested inside it". "Outside a repository, Claude Code keys the trust on the directory you started it from, and the trust covers any subdirectory of that directory apart from a git repository nested inside it". Home directory: current session only. [verified] — https://code.claude.com/docs/en/permissions.md
- Nested repository: "in an interactive session Claude Code shows the trust dialog for it". With only a parent trusted, the project's `.claude/settings.json` allow rules are "Not used until you accept the trust dialog, which appears again listing them", while settings hooks and `env` are "Used". [verified] — same URL
- "Start Claude Code from a project subdirectory instead, where trust acceptance is saved per directory"; for the home directory "There is no setting to persist it." [verified] — https://code.claude.com/docs/en/security.md
- Trust decisions are kept in `~/.claude.json` ("per-project state such as trust decisions"). [verified] — https://code.claude.com/docs/en/settings.md
- Manual mode: Bash asks "except a built-in set of read-only commands" (which include "read-only forms of `git`"); "Yes, and don't ask again" lasts "Permanently per repository and command" for Bash, per repository and domain for WebFetch, until session end for file edits. [verified] — https://code.claude.com/docs/en/permissions.md
- Terminal sessions start in `auto` by default with v2.1.283 or later. The reviewing mode is now called **Manual** (config value `default`; status bar `⏸ manual mode on`); Shift+Tab cycles modes. [verified] — https://code.claude.com/docs/en/permission-modes.md
- Auto mode blocks by default: "Production deploys and migrations", "Force push", "Printing a live credential or token into the transcript or a file", "Changing where pushes go with `git remote set-url` or `git remote add`, unless you named the new remote". Allowed: "Pushing to any branch of the repository you're working in, including the default branch"; "Reading `.env` and sending credentials to their matching API". It trusts "the remotes that were configured for it when the session started". [verified] — same URL
- Whether auto mode treats `git push origin main` to a Vercel-connected repo as a "production deploy" is not stated. [unverified] — same URL
- (added 2026-10-21, v04) A remote added from another terminal while a Claude session is already open was not "configured for it when the session started"; reopening Claude afterwards (`/exit`, then `claude -c` = continue the latest conversation in this folder, FACTS.md §E) should make it a start-time remote. The docs do not describe this case. [inferred] — https://code.claude.com/docs/en/permission-modes.md , https://code.claude.com/docs/en/commands.md
- Checkpoints track Claude's file edits; `/rewind` or Esc twice; "Not a replacement for version control … continue using version control, such as Git". [verified] — https://code.claude.com/docs/en/checkpointing.md
- Git by conversation: "what files have I changed?", "commit my changes with a descriptive message". [verified] — https://code.claude.com/docs/en/quickstart.md
- The official security-reviewer example checks for "Secrets or credentials in code"; still no doc line about keys pasted into chat (see V5). [verified] — https://code.claude.com/docs/en/best-practices.md

### V8.15 일손 Box (repo) — what setup already installs
- `ilson setup` installs Homebrew when missing (needs an interactive terminal; asks for the admin password). — 일손 Box (repo) ilson:450-457, install.sh:7
- It then runs `brew install` for git, jq, gh, coreutils and python when missing. — 일손 Box (repo) ilson:460-466, README.md:17
- Claude Code (claude.ai/install.sh) and Codex are installed by script. — 일손 Box (repo) ilson:467-481
- Node.js / npm are not installed by setup; only `ilson motion --check` looks for `node` and `npx`. — 일손 Box (repo) ilson:614
- No `gh auth login` step and no git `user.name` / `user.email` setup. The box's own backup commits pass a fixed identity (`Ilson Box`, `ilson@localhost`) so they "work before a person configures their Git identity". — 일손 Box (repo) template/lib/snapshot.sh:34-36 (grep found no `gh auth` in ilson)
- `~/ilson` is itself a git repository: snapshot.sh runs `git init`, commits only `vault state .gitignore`, "never pushes". — 일손 Box (repo) template/lib/snapshot.sh:4, 9, 32
- `ilson chat` opens `claude --permission-mode auto` inside `~/ilson`. — 일손 Box (repo) template/lib/research/settings.py:42-44
- The box's permission rules (allow Edit/Write/WebFetch/`git status`/`git log`, ask `sudo`/`rm`, deny `.env` reads) are copied to `~/ilson/.claude/`; a project folder elsewhere does not get them. — 일손 Box (repo) ilson:377, template/claude/settings.json:8-30 [inferred for "does not get them"]

### V8.16 Not confirmed (round 2)
- Supabase: new-project form labels; whether the region can change later; exact Auth settings menu path; the SQL Editor run-button label.
- Vercel: the exact default Deployment Protection scope for a project made today; the button label on each repository row of the New Project list.
- Auto mode's judgment of a `git push` that triggers a Vercel production deploy.

### V8.17 Supabase — making the owner account (round 3, 2026-10-21)
- Users page, **Add user**(사용자 추가) menu: **Send invitation**(초대 보내기), shown only when the feature flag `authentication:show_send_invitation` is on, and **Create new user**(새 사용자 만들기), always shown. Without permission an item is disabled with "You need additional permissions to create users" (or "…to invite users"). [verified] (dashboard source, master branch, 2026-10-21) — https://github.com/supabase/supabase/blob/master/apps/studio/components/interfaces/Auth/Users/AddUserDropdown.tsx
- **Create new user** opens "Create a new user" with **Email address**(이메일 주소, placeholder "user@example.com"), **User Password**(비밀번호), the checkbox **Auto confirm user?**(사용자 자동 확인, checked by default), the note "A confirmation email will not be sent when creating a user via this form.", and the button **Create user**(사용자 만들기). Success toast: "Successfully created user: " + email. [verified] (file last changed 2026-10-14, commit 09a1f43) — https://github.com/supabase/supabase/blob/master/apps/studio/components/interfaces/Auth/Users/CreateUserModal.tsx
- The form sends `email`, `password` and `email_confirm` (= the checkbox) to `/platform/auth/{ref}/users`. [verified] — https://github.com/supabase/supabase/blob/master/apps/studio/data/auth/user-create-mutation.ts
- **Send invitation** opens "Invite a new user" with **User email** and **Invite user**; it passes no redirect URL. Toast: "Sent invite email to " + email. [verified] — https://github.com/supabase/supabase/blob/master/apps/studio/components/interfaces/Auth/Users/InviteUserModal.tsx
- User panel: **Reset password** → **Send password recovery** ("Send a password recovery email to the user."), **Send magic link** / **Send confirmation email**, **Remove MFA factors**, **Ban user**, **Delete user** ("User will no longer have access to the project."). No action sets a password directly. The first detail row is **User UID** with a copy button that appears on hover. [verified] — https://github.com/supabase/supabase/blob/master/apps/studio/components/interfaces/Auth/Users/UserOverview.tsx
- Auth server: neither the admin create-user handler nor the invite handler checks the sign-ups setting (`DisableSignup` appears in neither file). [verified] — https://github.com/supabase/auth/blob/master/internal/api/admin.go , https://github.com/supabase/auth/blob/master/internal/api/invite.go
- The docs page still describes only **Add user** → **Send invitation** → **Invite user** ("a new unconfirmed user is created"); it does not mention **Create new user**. [verified] — https://supabase.com/docs/guides/auth/users
- Site URL "defines the default redirect URL when no redirectTo is specified in the code"; "This setting is critical for email confirmations and password resets"; change it "from `http://localhost:3000` to your production URL" on the URL Configuration page. [verified] — https://supabase.com/docs/guides/auth/redirect-urls
- So a dashboard invite or password-recovery link lands on the Site URL, `http://localhost:3000` until the owner changes it, and the owner page has no screen to set a password. [inferred] — same URLs
- Local run with Auth v2.188.1, sign-ups off, email confirmation on: email + password + `email_confirm: true` → user created and can sign in; `email_confirm: false` → sign-in refused with `email_not_confirmed`; invite → mail sent, link `…/auth/v1/verify?token=…&type=invite&redirect_to=http://localhost:3000` → 303 to the Site URL with `#access_token=…`; the invited user has no password they know; Delete user + Create new user with the same email gives a new UID, requests stay, and the owner sees them again after owner-policy.sql is re-run with the new UID. [tested] — docs/claude-learn/vibe/test-log.md (U1, U2, U4, U5)

### V8.18 Supabase — rows per request
- "By default, Supabase projects will return a maximum of 1,000 rows." "This setting can be changed in Project API Settings." "You can use `range()` queries to paginate through your data." [verified] — https://supabase.com/docs/reference/csharp/select
- The JS select reference fetched today does not show that note; the field name "Max rows" comes from a search snippet of a GitHub discussion only. [unverified] — https://supabase.com/docs/reference/javascript/select , https://github.com/orgs/supabase/discussions/3765
- The CSV export pages with `range()` until an empty page arrives, so it also works when the limit is lower than 1,000 (tested with 300). [tested] — docs/claude-learn/vibe/test-log.md (X1, X5)

### V8.19 Supabase — CORS for the Data API and Auth
- No official page found that states CORS or allowed origins for the hosted Data API (REST) or Auth. The Edge Functions CORS guide covers functions only; its manual example sets `'Access-Control-Allow-Origin': '*'`. [unverified] (absence) — https://supabase.com/docs/guides/functions/cors
- Self-hosting gateway config: the `/rest/v1` and `/auth/v1` routes enable Kong's `cors` plugin with no `config` block (no origins list). [verified] — https://github.com/supabase/supabase/blob/master/docker/volumes/api/kong.yml
- Kong cors plugin: "NOTE: If you don't specify any allowed domains, all origins are allowed." [verified] — https://developer.konghq.com/plugins/cors/reference/
- So the self-hosted stack accepts any origin, but nothing official says whether a hosted project accepts a page opened as `file://` (Origin `null`). Test the pages from a local web server (for example `python3 -m http.server` in the project folder, then `http://localhost:8000`) or from the Vercel address instead of double-clicking the HTML file. [inferred]

### V8.20 What a static site exposes (2026-10-21)
Setting: private personal GitHub repo, dashboard import, **Framework Preset** **Other**, no build command; repo root also holds CLAUDE.md and .gitignore.
- "Only the contents of this **Output Directory** will be served statically by Vercel." [verified] (page date 2026-08-28) — https://vercel.com/docs/builds/configure-a-build
- No-build projects: "Choose "Other" as the Framework Preset. This sets the output directory as `public` if it exists or `.` (root directory of the project) otherwise"; "If your project doesn't have a `public` directory, it will serve the files from the root directory". [verified] — same URL
- So with no `public` folder, every committed root file (CLAUDE.md, .gitignore, notes) is in the served output, e.g. `https://<project>.vercel.app/CLAUDE.md`. [inferred] — same URL
- Static sites: "Set **Framework Preset** to **Other**." "Leave the build command blank." "(Optionally) override the **Output Directory** if you want to serve a folder other than `public` or `.`." [verified] (page date 2026-09-03) — https://vercel.com/docs/builds
- Where: project → **Settings** → **Build and Deployment**(빌드 및 배포) → **Framework Preset**, **Build Command**, **Output Directory**, **Install Command**, each with an **Override**(직접 지정) toggle; "If you update the **Override** setting, it will be applied on your next deployment." The same page also calls this block "**Build & Development Settings**"; the import screen calls it "Build Output Settings". [verified] — https://vercel.com/docs/builds/configure-a-build , https://vercel.com/docs/git
- **Root Directory** (same page): "Your app will not be able to access files outside of that directory"; path **Build and Deployment** → **Root Directory** → enter path → **Save**. [verified] — https://vercel.com/docs/builds/configure-a-build
- File option: `vercel.json` `"outputDirectory": "build"` overrides the dashboard value "for a given deployment"; "To select "Other" as the Framework Preset, use `null`." [verified] (page date 2026-08-14) — https://vercel.com/docs/project-configuration/vercel-json
- "The build step will result in an error if the output directory is missing, empty, or invalid". [verified] (page date 2026-09-16) — https://vercel.com/docs/errors/error-list
- So an explicit Output Directory override stops the deploy if the folder is missing, while the Other default quietly falls back to `.`. [inferred] — same URLs
- `.vercelignore`: "should be placed in the root directory of your project and should contain a list of files and directories, one per line, that should be excluded from deployment"; "works similarly to a `.gitignore` file"; example lines `image` and `private.html`. Allowlist: "Add a wildcard `/*` as the first line", then lines that "start with a `!`" (example `/*`, `!api`, `!vercel.json`, `!*.html`). [verified] (page date 2025-03-12) — https://vercel.com/docs/deployments/vercel-ignore
- Same page, "Served Files": "Non-targeted files are prevented from being deployed and served on Vercel." (wording as published; the intent is that listed files are not deployed). [verified] — same URL
- The page speaks of files "uploaded to Vercel" and never says whether Git-integration deployments read `.vercelignore`; no official page fetched confirms or denies it. [unverified] — same URL
- Default ignore list (`.git`, `.gitignore`, `.DS_Store`, `.env.local`, `.env.*.local`, `node_modules` and others): "These ignored files are only relevant when using Vercel CLI." [verified] (page date 2026-09-16) — https://vercel.com/docs/builds/build-features
- "However, these files are *not* ignored for deployments created using Git and a warning is printed instead. This is because `.gitignore` determines which files should be ignored." [verified] — https://vercel.com/docs/errors/error-list
- Dotfiles: no official page says Vercel hides dotfiles. With the output at `.`, a committed `.gitignore` is part of a Git deployment (line above) and so is presumably reachable at `/.gitignore`. Not tested. [inferred] — same URLs
- Whether the build clone's `.git` folder lands in a `.` output is not stated. [unverified]
- Directory Listing: when enabled, a folder path with no index file lists its files; "When disabled, a "Not Found" error will be displayed with status code `404`." Toggle: **Advanced** in project settings. Default state not stated. [verified; default unverified] (page date 2026-02-26) — https://vercel.com/docs/directory-listing
- `/_src` ("Displays the source code and build output") and `/_logs` are by default open only to "you and authenticated members of your Vercel team"; "Disabling **Build Logs and Source Protection** will make your source code and logs publicly accessible." [verified] (page date 2026-08-25) — https://vercel.com/docs/project-configuration/security-settings
- So CLAUDE.md stays visible to the team through `/_src` even when it is not served; never turn that protection off. [inferred] — same URL
- Recommended beginner setup (from the lines above only): Claude puts every site file in a `public/` folder (`public/index.html`, css, js); CLAUDE.md, .gitignore and notes stay at the repo root. Import screen: **Framework Preset** = **Other**, Build Command empty, Build Output Settings → **Output Directory** → **Override** on → `public`. Two layers: the Other default already picks `public`, and the explicit value stops the deploy instead of falling back to the root if the folder is ever missing. Check after the first deploy: `https://<project>.vercel.app/CLAUDE.md` and `/.gitignore` should show 404. [inferred] — URLs above
- `.vercelignore` (e.g. `CLAUDE.md`) is at most a third layer, since Git-deploy support is not stated; never rely on it alone. [inferred] — https://vercel.com/docs/deployments/vercel-ignore

### Implications for the lessons (V8)
- Hobby vs Pro: say plainly "연습용 가짜 가게는 Hobby(무료)로 충분, 실제 가게 손님이 쓰면 Vercel 규정상 상업적 사용 → Pro 월 $20(부가세 별도)". Quote the "Advertising the sale of a product or service" example and the 14-day trial; never call a real shop page "free on Vercel".
- Which key goes where: the page (customer form + owner page) holds only the Supabase project URL and the **publishable key**, written straight into the JS file and committed to the private repo. The **secret key**, database password and legacy `service_role` never go into the page, the repo, Vercel env vars or the chat. No Vercel env vars are needed for this plain-HTML design.
- Simplest GitHub auth: 일손 Box already installed git and gh. Reader runs `gh auth login` → GitHub.com → HTTPS → `Y` → browser login, then sets `git config --global user.name` / `user.email` (GitHub noreply address). Create the private repo with `gh repo create <name> --private --source=. --push` (or on github.com). GitHub Desktop is a fallback, not the main path.
- Safest SQL path: Claude writes the SQL into a file in the project (e.g. `supabase/setup.sql`) and explains each line; the owner pastes it into the Supabase **SQL Editor** and runs it. No Supabase CLI, MCP or secret key on the Mac. Every table script must include GRANT lines (2026 change), `enable row level security`, and policies; then test from a private browser window that a customer can send but cannot read.
- Trust guidance: make the project folder outside `~/ilson` and outside the home folder itself (e.g. `~/Projects/haetsal-booking`), `cd` there and run `claude` (not `ilson chat`, which opens `~/ilson`). Expect the folder-trust question and answer yes; it is saved for that folder. A folder inside `~/ilson` would be a nested git repo (still asks) and sits next to the box's own backups, so avoid it.
- Blocker 1: Supabase projects created after 2026-05-30 don't expose new tables automatically; older copy-paste SQL without GRANT fails with 42501. Lessons v04–v06 must teach grant + RLS + policy together.
- Blocker 2: git identity is not set on box Macs, so the first `git commit` will stop until user.name/email are set; put this in the lesson before the first commit.
- Blocker 3: no Node.js on box Macs → skip the Vercel CLI; use the dashboard Git import (push = deploy). Rollback on Hobby goes back one deployment only; teach `git revert` + push as the main undo.
- Blocker 4: Supabase Free pauses after a quiet week; a shop with few inquiries can be paused (warning email first, **Resume project**). Tell the owner to open the owner page at least every few days, or plan Pro ($25/mo). No automatic backups on Free.
- Blocker 5: built-in auth email sends 2 per hour and only to project team members — fine for one owner, but lessons must not promise customer emails from Supabase.
- Watch: Claude Code auto mode won't add or repoint a git remote unless the reader names it, and may treat a deploy as production; the lesson prompt should name the GitHub URL and the reader should approve pushes knowingly.
- Owner account (V8.17): use **Add user** → **Create new user** with email + password and **Auto confirm user?** left on; it works with sign-ups off and needs no email or Site URL. Avoid **Send invitation** (no password the owner set; the link lands on the Site URL). Forgotten password: **Delete user**, **Create new user** again, re-run owner-policy.sql with the new **User UID**.

## V9. Live check 2026-10-21

The whole 심화 flow was run once on real accounts (a free Supabase organization in Seoul, a private GitHub repository, a Vercel project on a Pro team) with the fictional 햇살꽃집 practice site built from the verified files; every test resource was deleted afterwards. Same line format. Tag [tested-live] = seen on the real dashboard or site during that run; the labels below may be quoted verbatim in lessons. Screens change, so lessons still say "화면 모양은 바뀔 수 있어요".

### V9.1 Supabase
- New organization form: **Name**, **Type** (Personal), **Plan** (**Free - $0/month**), **Create organization**. [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- New project form: Organization, GitHub (optional), **Project name**, **Database password** with **Generate a password**, **Region**, Security checkboxes (**Enable Data API** on; **Automatically expose new tables** on, with "We recommend disabling this…"; **Enable automatic RLS** off), **Create new project**. The project was ready within seconds. [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- Region: the default is the general region **Asia-Pacific**; Seoul is under "Specific regions" as **Northeast Asia (Seoul)** `ap-northeast-2`; Tokyo is marked "Recommended". [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- Project home shows the project URL and a **Copy project URL and API keys** button. The left sidebar shows icons only; names appear on hover. What that copy button puts on the clipboard was not recorded. [tested-live; clipboard content unverified] — docs/claude-learn/vibe/live-check-2026-10-21.md
- SQL Editor: the first visit shows **Snippets no longer save automatically** → **Understood**. schema.sql pasted and **Run** → **Success. No rows returned**, with the default Security checkboxes. [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- Settings → **API Keys**: **Publishable key** ("This key is safe to use in a browser if you have enabled Row Level Security (RLS)…", **Copy API key**); **Secret keys** hidden behind **Reveal API key**. [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- Sign-ups off: Authentication → **Sign In / Providers** → **User Signups** → switch **Allow new users to sign up** → **Save changes** (required) → toast **Successfully updated settings**. [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- Owner account: Authentication → **Users** → **Add user** menu (**Send invitation** / **Create new user**) → dialog **Create a new user** (**Email address**, **User Password**, **Auto confirm user?** checked, note "A confirmation email will not be sent…") → **Create user** → toast **Successfully created user: …**. The user panel shows **User UID** and "Confirmed at". [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- owner-policy.sql: **Run** opens **Potential issue detected** ("This query includes destructive operations…") because of `drop policy if exists`; **Run query** continues; the result shows 3 rows (규칙 이름 / 종류 / 누구에게). [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- cleanup.sql: blocks 【1】 and 【3】 ran without a warning dialog (【3】 deletes inside a CTE). [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md

### V9.2 Local test server and client code
- `python3 -m http.server 8000 --bind 127.0.0.1 --directory public`: pages opened from `http://127.0.0.1:8000` reached hosted Supabase (Data API and Auth; CORS OK). [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- Bug found: reserve.js used `form.elements[name]`; in real browsers `form.elements['item']` returns the collection's built-in `item()` method instead of the field named `item`, so sending stopped with `TypeError … reading 'trim'`. jsdom did not show it. Fixed to `form.elements.namedItem(name)` in client-snippets.md and files/v06-reserve-code.txt and re-tested live. [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- Customer and owner flow on the real project: send → "예약 요청을 받았어요…"; consent unchecked → the browser blocks sending; anonymous read → 42501; owner sign-in → list; status change → "'확인함'(으)로 바꿨어요."; CSV `예약요청-YYYY-MM-DD.csv` with BOM and the formula guard (`'- …`). [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md

### V9.3 Vercel
- Import: **New Project** → **Import Git Repository** list shows the new private repository → **Import**. [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- Configure page: **Vercel Team**, **Project Name**, **Root Directory** `./`, **Application Preset** (picked **Other** automatically; the name "Framework Preset" is no longer shown), **Build and Output Settings** (Build Command, **Output Directory** with placeholder "`public` if it exists, or `.`", Install Command; each locked until its **Override** toggle at the right end of the field is turned on), **Environment Variables**, **Deploy**. [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- After deploying: **Congratulations!**, **Visit Deployment**, **Continue to Project**. [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- Live site: `https://<project>.vercel.app/` → 200; `/CLAUDE.md` → 404; `/.gitignore` → 404; the per-deployment URL redirects to the Vercel login (302). The full customer/owner flow passed on the live address. [tested-live] — docs/claude-learn/vibe/live-check-2026-10-21.md
- The run used a Pro team, so Hobby-only screens were not seen. [tested-live, scope note] — docs/claude-learn/vibe/live-check-2026-10-21.md

### Implications for the lessons (V9)
- Quote the live labels above verbatim (v05 forms and success line, v07 sign-ups path, **Save changes**, the owner-policy warning, v09 **Application Preset** and **Build and Output Settings**). Older names in V8 ("Framework Preset", "Build Output Settings") stay only in source labels that quote the docs.
- The owner-policy warning is expected for that file only; other track SQL showed no warning.
- Lessons may say the local test server works with hosted Supabase; keep the Vercel-address fallback.
- Client code must be checked in a real browser as well as jsdom.
