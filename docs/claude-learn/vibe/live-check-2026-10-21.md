# Live check on real accounts (2026-10-21)

The 바이브 코딩 심화 flow was run end to end on real accounts (Supabase free organization made for the test, Seoul region; private GitHub repo; Vercel project on a Pro team) with a fictional 햇살꽃집 practice site built from the verified files. All test resources were deleted afterwards.

## Result

| Step | Result |
|---|---|
| Supabase: new free organization | Form: **Name**, **Type** (Personal), **Plan** (Free - $0/month), **Create organization**. |
| Supabase: new project | Form: Organization, GitHub (optional), **Project name**, **Database password** + **Generate a password**, **Region**, Security checkboxes (**Enable Data API** on, **Automatically expose new tables** on with "We recommend disabling this…", **Enable automatic RLS** off), **Create new project**. Region default is the general region **Asia-Pacific**; Seoul is under "Specific regions" as **Northeast Asia (Seoul)** `ap-northeast-2` (Tokyo is marked Recommended). Project was ready within seconds. |
| Project home | Shows the project URL and a **Copy project URL and API keys** button. The left sidebar is icon-only; names appear on hover. |
| SQL Editor, schema.sql | First visit shows a dialog **Snippets no longer save automatically** → **Understood**. Pasting schema.sql and pressing **Run** gives **Success. No rows returned** with the default Security checkboxes. |
| API keys | Settings → **API Keys**: **Publishable key** ("This key is safe to use in a browser if you have enabled Row Level Security (RLS)…", **Copy API key**) and **Secret keys** (hidden; **Reveal API key**). |
| Sign-ups off | Authentication → **Sign In / Providers** → **User Signups** → switch **Allow new users to sign up** → **Save changes** (required) → toast **Successfully updated settings**. |
| Owner account | Authentication → **Users** → **Add user** menu: **Send invitation** / **Create new user**. Dialog **Create a new user**: **Email address**, **User Password**, **Auto confirm user?** (checked), note "A confirmation email will not be sent…", **Create user** → toast **Successfully created user: …**. The user panel shows **User UID** and "Confirmed at". |
| owner-policy.sql | **Run** opens a warning **Potential issue detected** ("This query includes destructive operations…") because of `drop policy if exists`; **Run query** continues. Result: 3 rows (규칙 이름 / 종류 / 누구에게). |
| cleanup.sql | Block 【1】 and block 【3】 run without a warning (【3】 deletes inside a CTE). |
| Local test server | `python3 -m http.server 8000 --bind 127.0.0.1 --directory public` → requests from `http://127.0.0.1:8000` reach hosted Supabase (CORS OK). |
| **Bug found and fixed** | reserve.js used `form.elements[name]`. In real browsers `form.elements['item']` returns the collection's built-in `item()` method, not the field named `item`, so sending stopped with `TypeError … reading 'trim'`. jsdom did not show this. Fixed to `form.elements.namedItem(name)` in client-snippets.md and files/v06-reserve-code.txt; re-tested live. |
| Customer / owner flow | Send → "예약 요청을 받았어요…"; consent unchecked → browser blocks; anon read → 42501; owner sign-in → list, status change "'확인함'(으)로 바꿨어요."; CSV `예약요청-YYYY-MM-DD.csv` with BOM, formula guard (`'- …`). |
| Vercel import | **New Project** → **Import Git Repository** list shows the new private repo → **Import**. Configure page: **Vercel Team**, **Project Name**, **Root Directory** `./`, **Application Preset** (auto **Other**; the old name "Framework Preset" is gone), **Build and Output Settings** (Build Command / **Output Directory** placeholder "`public` if it exists, or `.`" / Install Command, each locked until its **Override** toggle at the right end of the field is turned on), **Environment Variables**, **Deploy**. Success page: **Congratulations!**, **Visit Deployment**, **Continue to Project**. |
| Live site | `https://<project>.vercel.app/` 200; `/CLAUDE.md` 404; `/.gitignore` 404; the per-deployment URL redirects to Vercel login (302). Full customer/owner flow passed on the live address. |
