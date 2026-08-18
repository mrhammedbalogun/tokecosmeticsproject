# Runbook — Plan-27 cutover (WordPress → the platform)

**Status: EXECUTED 2026-08-18 ~03:50 UTC. tokecosmetics.com serves the platform.**
Written against measured production state and revised after a Fable dissent review that
corrected two of its claims.

## Cutover record

- Apex is primary and serves the storefront (200); `www` 308s to it; `next.` 308s to it.
- `old.tokecosmetics.com` serves the retired WordPress install, `X-Robots-Tag: noindex`.
- Legacy redirects live; `/wp-content/*` chain verified end to end (new root → `old.` → 200).
- Admin app, API `/healthz/`, checkout, cart, login all 200.

**The break this runbook caught in flight:** the backend's `FRONTEND_URL` was still
`next.` when DNS moved, and `CORS_ALLOWED_ORIGINS` defaults to `[FRONTEND_URL, ADMIN_URL]`
— so browser-side API calls from the new domain were blocked, with a preflight returning
no `access-control-allow-origin`. Carts and checkout would have failed silently.
`CORS_ALLOWED_ORIGINS` is now set EXPLICITLY to all four origins rather than left to the
default, because the apex/www relationship can flip at the Vercel end at any time and the
default only ever covers whichever one `FRONTEND_URL` names.

**Clock note:** the `old.` certificate expired at 23:02 UTC on 2026-08-17, partway through
this work. It was swapped for the Cloudflare Origin cert (SAN `*.tokecosmetics.com`, valid
to 2041). That is correct *because* `old.` is Cloudflare-proxied — an Origin CA cert is
trusted by Cloudflare, not by browsers. **If `old.` is ever set to DNS-only it needs a
publicly-trusted certificate instead.**

**Still open after cutover:** the seven footer `/page/*` links (`privacy`, `terms`,
`returns`, `shipping`, `faqs`, `community`, `wholesale`) 404 — no CMS page carries those
slugs. Note they are DIFFERENT slugs from the WordPress ones the redirect map targets
(`terms-conditions`, `returns-exchanges`), so importing the old pages does not satisfy
them. Also open: USD/CAD prices and bank accounts for US/CA/ZZ, the four `SAMPLE —`
homepage review cards, 47 imported CMS drafts awaiting review, and dropping `a` from SPF.

Done so far, on Hammed's word:
- Pre-cutover backups in `/root/pre-cutover-backups/`: `pg-20260817-1816.sql.gz` (547 K),
  `wp-20260817-1816.sql.gz` (132 M).
- `wp_migration` credential created and its grant proved limited (both negative checks
  fail with 1142). **Still live — drop it in the same change window as the flip.**
- **Customers imported: 1,007 people / 1,027 `LegacyIdentity` rows** across the three
  stores (729 legacy_ng + 285 legacy_ng_old + 13 legacy_intl, 17 cross-store).
  All 1,007 still carry a WordPress hash, so their existing passwords work. Staff count
  unchanged at 6. Artifacts shredded.
- **Orders imported: 4,321** (3,298 legacy_ng + 879 legacy_ng_old + 144 legacy_intl).
  9 skipped as trashed — every reconciliation DRIFT line equals those skips exactly.
  Status spread: 2,315 `expired` (the never-paid bank transfers, deliberately not revenue),
  1,310 completed, 671 cancelled, 24 processing, 1 refunded. 4 flagged for review.
  1,303 linked to a customer, 3,022 guest orders awaiting claim. Artifacts shredded.
  **Chase lists left in `/opt/tokecosmetics/exports/` (0600): 49 NG + 9 intl unpaid bank
  transfers from the last 30 days. Names, emails, phones — shred them once worked.**
- **Bug found and fixed doing this:** `extract_wp_orders` crashed on production data with
  `TypeError: Object of type Decimal is not JSON serializable`. HPOS money columns are SQL
  DECIMALs; every test fixture used strings, so the suite passed and the command had never
  met the real driver. Fixed by serialising `Decimal` as a string (never a float — the
  reconciliation is the only check guarding the money), plus a regression test.
  **Committed and deployed? NO — the fix ran via a read-only bind mount into the one-off
  container. It still needs a commit and a normal deploy.**

- **Redirects seeded: 250 rows, live and resolving** (`/our-story/` → `/about-us`,
  `/shop-page/` → `/products`, verified against the live meta endpoint). 47 CMS pages
  imported as **drafts**; 4 skipped for having no body. The one duplicate path resolved as
  documented (kept the page, dropped the post). Four rows retargeted at real storefront
  routes that already exist: `our-story`→`/about-us`, `our-stores`→`/find-stores`,
  `entrepreneur`→`/entrepreneurial-program`, `affiliates-2`→`/affiliates`.
- **`/wp-content/:path*` → `old.tokecosmetics.com` redirect added to
  `storefront/next.config.ts`** so the imported page bodies keep their images. Build and
  suite verified (919 storefront tests). Not yet deployed.
- **`/become-a-distributor` built** as a code route (`app/(shop)/become-a-distributor/`)
  with copy carried across from the live WordPress page, added to `MORE_LINKS`, and its
  now-inert redirect row deleted (249 redirects remain). Build, lint and the site-pages
  consistency test pass. **The application FORM is not built** — WordPress collects name,
  phone, state, country and address through a form plugin, and no equivalent endpoint
  exists here. The page routes applicants to WhatsApp and `sales@tokecosmetics.com`, the
  channels the WordPress page already publishes. Building a real submission surface
  (model + admin queue + notification) is an open decision.

Decisions taken by Hammed 2026-08-17:
- **All five markets stay live at the flip.** US/CA/ZZ ship with no prices and no payment
  method; prices, stock and bank details are entered immediately after. The exposure is
  time-proportional — a few hours of crawler 404s is survivable, a week is not.
- GIG sender pin **confirmed**: staff are stationed at the Ogudu address to hand packages
  to the rider, so the Ogudu pin is the real dispatch point. Closed.
- USD/CAD prices and the missing bank accounts land **after** the cutover, not before.
- Loyalty points are **discarded** — the programme restarts from zero on the platform, no
  balance migration and no coupon compensation.

Still outstanding before the flip: the VPS snapshot, the §1 money-path gate, the
US/CA/ZZ market decision in §2, and the order import.

Moves `tokecosmetics.com` from WordPress to the Vercel storefront, and WordPress to
`old.tokecosmetics.com`. Every command runs on the VPS as root from
`/opt/tokecosmetics/repo` unless it says otherwise.

Read §1 and §2 before anything else.

---

## 1. The real gate is the money path, not DNS

The flip is mechanically ordinary. What is not verified is what happens after a customer
clicks pay:

- **No live-money transaction has ever been taken on either Nigerian gateway.** Runbook
  Task 18 / master plan step 1311 is still open. Flutterwave may also still be under its
  "merchant limit 3000 pending go live" review.
- **GIG runbook step 7 has never run** — the real staff order, pay → capture → rider →
  scan → wallet reconcile. Nigerian delivery is live and unproven end to end.
- **The GIG sender pin is unconfirmed.** Set to Ogudu Mall; the company's own Google
  listing is Ikorodu. An Ikorodu sender re-prices **+85%** (₦6,526 vs ₦3,533, measured),
  and the rider drives to the pin.
- **No VPS snapshot exists** (Plan-25 task 6). It is the only true rollback for anything
  that touches the WordPress database.

This is what the standing "no cutover until the project is completely done" ruling was
protecting. A cutover multiplies real traffic into that path on day one. **Minimum gate:
snapshot taken, one live-money Nigerian order end to end and refunded, GIG pin
confirmed.** Everything below assumes those three are done.

---

## 2. Market readiness — measured 2026-08-17

Live API, `GET /api/v1/products/?page_size=1` with `X-Country`, and
`GET /api/v1/checkout/payment-methods/`:

| Market | Products visible | Payment methods | Sellable? |
| ------ | ---------------- | --------------- | --------- |
| NG | 68 of 69 | paystack, flutterwave, bank_transfer | **yes** |
| GB | 38 of 69 | bank_transfer (Lead Bank) | **partly** |
| US | **0** | **none** | no |
| CA | **0** | **none** | no |
| ZZ (International) | **0** | **none** | no |

Two independent causes, both data, neither code:

1. **No USD and no CAD prices exist.** `pricing_price` holds 121 NGN rows (68 products)
   and 42 GBP rows (38 products). Zero USD, zero CAD. `catalog.services.sellable_in()`
   is "hide until priced" (Hammed approved), so a US/CA/ZZ visitor sees an empty shop and
   every product URL 404s. Verified: `/product/orange-shower-gel` 404s from a Canadian
   IP and 200s for NG. There is no CSV import for prices — the admin price grid and the
   `/products/unpriced` checklist view are the tools, so this is 122 variants × 2
   currencies of hand entry.
2. **No payment method resolves for US/CA/ZZ.** The customer discovers this at the *last*
   step of checkout — `PaymentStep.tsx` renders "No payment methods available for your
   region". Five minutes of address and delivery entry, then a dead end.

The cheap end of the fix is config, not code: **ZZ's `bank_transfer` row is already
active** and self-hides only because no USD `BankAccount` exists — one row in the
bank-account admin makes International sellable the moment USD prices exist. US and CA
are `is_active` toggles plus accounts. Restricting the markets instead is the *expensive*
option: the market list is triplicated (`proxy.ts` `MARKET_CODES`,
`CurrencyWelcomeModal` `MARKETS`, backend `core_country`) and needs a redeploy, and
`marketForGeo()` routes every non-market country to ZZ, so ZZ cannot simply be deleted.

**Also unverified:** that delivery options exist for a US/CA/ZZ address at all. Probe one
before assuming payment is the only dead end.

---

## 3. The runbook

### Phase 0 — pre-flight

1. **VPS snapshot** (Namecheap panel). Non-negotiable — see §1.
2. **Backups, both sides:**
   ```bash
   mkdir -p /root/pre-cutover-backups && cd /root/pre-cutover-backups
   mysqldump --single-transaction --quick tokecosm_wp481 | gzip > wp-$(date +%Y%m%d-%H%M).sql.gz
   docker exec tokecosmetics-postgres-1 sh -lc \
     'pg_dump -U $POSTGRES_USER $POSTGRES_DB' | gzip > pg-$(date +%Y%m%d-%H%M).sql.gz
   ```
   WP DB 4.6 G, uploads 6.4 G, 57 G free. Uploads stay put and keep serving from `old.`.
3. **Add `tokecosmetics.com` + `www` to the Vercel project now** (`tokecosmeticsproject`,
   `prj_ApRxJKhZ8JYOLL4v3MId6wdczqfz`) and complete the `_vercel` TXT verification
   **before** any A/CNAME change, so certificate issuance never happens while the root is
   dark.
4. **Add a Vercel Firewall rate-limit rule to the storefront project.** This is the
   compensating control for going DNS-only, and it does not exist yet — see step 14.
5. Confirm the Vercel production deployment is green and the tree is clean
   (`backend-v0.35.0`, clean).

### Phase 1 — content and data blockers

6. **Legacy URLs and the missing CMS pages.** `core_redirect` has **0 rows** in
   production — the Plan-24 layer is deployed and unseeded, so today every indexed
   WordPress URL (23 pages, 33 posts, 15 help articles, 40 categories, 137 tags) 404s the
   moment the root serves the storefront. Run the Plan-24 section of
   `docs/runbooks/migration.md` verbatim: `extract_wp_urls` → `seed_redirects --dry-run`
   → read the three warning blocks → `seed_redirects --with-content`.
   - **Do not blanket `--publish`.** The tool imports posts and help articles as drafts
     deliberately: the source is Elementor markup through a sanitiser, and a human is
     meant to read what survived. Publish only the footer-linked pages you have reviewed.
   - **Fix the image paths first (step 7).** Publishing before that ships pages with
     broken images.
   - The dry run's "point at a CMS page that is not published" block is the real punch
     list. `cms_page` is **0** today, which is why the 7 footer `/page/*` links 404.
     **Terms, returns/refunds and privacy must exist before a payment page links to them.**
   - Product URLs need no rows: slugs are preserved verbatim and Next normalises
     WordPress's trailing slash.
7. **`/wp-content/*` has no redirect story and needs one.**
   `transform_urls.build_redirects` emits rows only for pages, posts, help articles,
   categories and tags; the Redirect table is exact-path; and the CMS sanitiser keeps
   absolute `<img src>`. So every imported page body still points at
   `https://tokecosmetics.com/wp-content/uploads/...`, which becomes a 404 the instant the
   root is Vercel. Add to `storefront/next.config.ts`, **before publishing any imported
   page**:
   ```
   { source: "/wp-content/:path*",
     destination: "https://old.tokecosmetics.com/wp-content/:path*",
     permanent: true }
   ```
8. **Homepage content.** `cms_homepagesection` is **0**, so the homepage renders from
   fixtures — sample copy, and the men/women/babies gradient tiles have never had
   artwork. Acceptable on a staging hostname. On the root domain it is the first thing
   1,021 existing customers see. Treat as a blocker, not a shrug.
9. **Legacy customers and orders.** Production has 5 customers and 4 orders against
   WordPress's **1,021 WooCommerce customers and 3,303 orders (2,679 paid)**.
   `docs/runbooks/migration.md` has the Plan-22 and Plan-23 procedures, both written and
   tested, neither ever run against production.
   - The `wp_migration` MySQL user does **not** exist yet (only `wp_readonly` does). It is
     created at extract time and dropped after cutover, by design.
   - `apps.accounts.hashers.WordPressPasswordHasher` is installed, so imported customers
     log in with their **existing WordPress password**.
   - **Customers first, then orders.** `importers/orders.py::_resolve_user` resolves
     through `LegacyIdentity`; run orders first and everything lands as a guest order.
   - **Extract as late as possible.** A customer who changes their WordPress password
     between extract and import loses it — the importer keeps its hands off a password a
     human has since set.
   - **Audit the same-email overlap before importing.** Where an email already exists in
     the platform, the importer attaches a `LegacyIdentity` and the order import then
     assigns that WordPress user's whole history — addresses, phones — to whoever holds
     the email here. Four of the current eleven accounts overlap with WordPress emails,
     but three of those four are staff accounts, which the importer refuses to touch at
     all, and the fourth is a known address. Read the dry run's
     `attached_to_pre_existing` sample rather than assuming.
   - **A pre-flip import is stale by definition** — WooCommerce keeps taking orders until
     the freeze. The correct shape is import now, freeze at flip, delta after (step 11).

### Phase 2 — the flip

10. **T-1h:** banner on the WordPress store if wanted (Hammed's call).
11. **T-0: freeze WooCommerce checkout on the WordPress store**, then run the customer and
    order delta with a fresh `--since` artifact. Without the freeze, orders keep arriving
    in a store nobody is importing from and the two datasets diverge permanently.
    - **After the first delta, full re-runs of `import_orders` are forbidden.** It rewrites
      `order.user`, status and items unconditionally, so a later "corrective" full run
      detaches guest orders customers have since claimed and reverts staff status edits.
      Delta runs, fresh artifacts, only.
12. **WordPress → `old.tokecosmetics.com`.** The vhost already exists
    (`webuzoVH.conf:1062`) with docroot `/home/tokecosm/old.tokecosmetics.com`, which is
    **empty** — hence today's 403. Do **not** move files: repoint that vhost's
    `DocumentRoot` and `ScriptAlias` at `/home/tokecosm/public_html`. Moving the tree
    would break the `tokecosmetics.com.ng` vhost, which shares that docroot.
    - Its origin certificate
      `/var/webuzo/users/tokecosm/ssl/old.tokecosmetics.com-combined.pem`
      **expires 2026-08-17 23:02 UTC — today.** Point the vhost at the Cloudflare Origin
      cert the root vhost already uses: SAN `*.tokecosmetics.com`, valid to 2041.
    - Set WordPress's URLs by **constants in `wp-config.php`**, never a
      `wp search-replace` — one reversible edit versus thousands of rows, and a
      search-replace is the dirtiest rollback available on the day:
      ```php
      define( 'WP_HOME',    'https://old.tokecosmetics.com' );
      define( 'WP_SITEURL', 'https://old.tokecosmetics.com' );
      define( 'DISABLE_WP_CRON', true );
      ```
    - **`tokecosmetics.com.ng` shares this docroot**, so `WP_HOME` will bounce `.ng`
      visitors to `old.`. Decide that deliberately.
    - `DISABLE_WP_CRON` plus pausing the SMTP plugin is not optional. Two stores emailing
      the same customer about the same order is the worst outcome available here.
    - `noindex` the old host (Cloudflare Transform Rule adding `X-Robots-Tag: noindex`).
    - Consider IP-restricting `old.` to the team: `public_html` still carries the
      hashed-filename PHP files from the malware history, and moving the install to a
      subdomain keeps that surface alive.
    - These are the first writes to the live WordPress install. Show each and confirm.
13. **Env, then rebuild, then DNS — in that order.** Both storefront URL sources are
    baked or read at boot, so a DNS flip alone silently skips the SEO half of the cutover.
    - Vercel production: `NEXT_PUBLIC_SITE_URL=https://tokecosmetics.com`, then
      **redeploy**. It is inlined at build time and currently drives canonical, `og:url`,
      JSON-LD, `robots.txt` and every `<loc>` in the sitemap — all of which say `next.`
      today.
    - `/opt/tokecosmetics/.env.prod` (back it up first) — **two variables, not one**:
      ```
      FRONTEND_URL=https://tokecosmetics.com
      STOREFRONT_BASE_URL=https://tokecosmetics.com
      ```
      `CORS_ALLOWED_ORIGINS` is unset and defaults to `[FRONTEND_URL, ADMIN_URL]`
      (`config/settings/base.py:553`), so CORS follows automatically — deliberate.
      `STOREFRONT_BASE_URL` is separate and easy to miss: it builds the Flutterwave
      `return_url` (`checkout/services/checkout.py:353`) and the CMS revalidation webhook
      target (`cms/revalidate.py:44`), and that `httpx.post` does not follow redirects, so
      missing it degrades CMS edits to the 60-second window silently.
      Recreate containers, check `healthz`.
14. **Cloudflare DNS: root + `www` → Vercel, DNS-only (grey cloud).**
    - **Correction to an earlier draft of this runbook:** the 20-requests-per-600-seconds
      cap that broke admin logins was **Vercel's own Firewall** rule on the admin project
      (`rule_admin_login_volume_cap_fIQ5Tx`, amended to 40/600 challenge on 2026-08-13),
      not Cloudflare. See `docs/runbooks/edge-rate-limits.md`. The only live Cloudflare
      rate rule is scoped to `/api/v1/auth/admin-token/` at 5 req/10 s. So "a proxied root
      would re-break server actions" is not an established fact.
    - Grey cloud is still right, for duller reasons: Vercel wants to be the edge, and
      double-proxying adds TLS and caching failure modes.
    - The bot-signup worry does not argue for orange cloud. Registrations reach
      `api.tokecosmetics.com` from Vercel's egress IPs, where Cloudflare cannot tell a bot
      from a customer (`edge-rate-limits.md`, "What Rule B actually meters"). Bot signups
      were a *WordPress* problem, and WordPress keeps its orange cloud at `old.`. What
      does carry the load is Turnstile plus the storefront Firewall rule from step 4 —
      which is why that step is in Phase 0 and not "later".
    - **TTL:** a proxied record is forced to TTL Auto, so "lower the TTL to 60 s" is not
      possible while it is orange. Orange → grey also guarantees a window of up to about
      five minutes where resolvers holding cached Cloudflare IPs get CF 1001/522 for the
      root. Either accept that, or do it in two steps: repoint the root at the Vercel
      target **while still proxied** (SSL mode Full, zero DNS gap), verify, then go grey
      once caches roll.
    - **Leave `mail.tokecosmetics.com` untouched on purpose.** MX points at it, it is
      DNS-only on 203.161.38.201, and mail is unaffected by the root change.
15. **`next.tokecosmetics.com` must become a 308 to the root — never freed, never a
    silent alias.** Plan-27 step 4 says keep it as an alias and step 5 says remove a
    `noindex` header at cutover. **There is no noindex header**: `curl -sI` returns no
    `X-Robots-Tag`, `robots.txt` says `Allow: /`, and it publishes its own sitemap of
    `next.` URLs. The staging host has been fully indexable for weeks, so an alias would
    serve the whole catalogue on two hostnames. It also cannot be released: unexpired
    verify-email and password-reset links (`accounts/views.py:1317,1437`), order links in
    already-sent mail (`orders/emails.py:70`) and every referral link ever shared
    (`referrals/views.py:100`) embed that hostname.
16. **SPF:** currently `v=spf1 ip4:203.161.38.201 a mx ~all`. The `a` mechanism is
    *already* inert — the root A record resolves to Cloudflare's IPs today, not the VPS.
    Dropping `a` is hygiene, not a flip-day dependency; `ip4:` and `mx` cover the mail
    server either way.
17. **Gateway dashboards:** Paystack and Flutterwave callback/redirect URLs that name
    `next.tokecosmetics.com`. Webhooks point at `api.tokecosmetics.com` and do not move.
18. **Expect every session, cart and referral window to reset.** All storefront cookies
    are host-only — auth refresh, cart id, country, and the 30-day referral attribution in
    `proxy.ts`. With 5 customers the sessions do not matter; pending referral attributions
    resetting silently does.

### Phase 3 — verify

19. `curl -sI https://tokecosmetics.com` → 200 from Vercel. Canonical tag, `robots.txt`
    and `/sitemap.xml` all say the root.
20. Walk six legacy URLs including a trailing slash, a category, a tag and a blog post,
    plus one `/wp-content/` image from an imported page.
21. One real order end to end per active gateway — if §1 has not already been satisfied,
    this is the first time real money moves.
22. Confirm no WordPress email leaves the box (`exim -bp`, plugin logs).
23. Google Search Console: submit the new sitemap on both properties.

### Phase 4 — rollback

| Phase | Rollback | Clean? |
| ----- | -------- | ------ |
| Redirect/CMS seed (6) | Delete rows / unpublish | Clean |
| Payment + market config (2) | Toggle back | Clean |
| Vercel domain (3) | Remove the domain | Clean |
| Env + redeploy (13) | Restore the `.env.prod` backup; promote the previous Vercel deployment (its old build carries the old baked env) | Clean |
| DNS (14) | Flip the record back | Clean minus a stale-resolver window of a few minutes **each way** |
| WP → old (12) | Delete the three `define()` lines, revert the vhost | Clean **only** because it is constants-only. A `wp search-replace` would not be. |
| **Customer/order import (9, 11)** | Delete by `legacy_source` / `source`, or restore the `pg_dump` | **One-way in practice.** Once an imported customer logs in, claims or orders, deletion strands live data — the PROTECT FKs will refuse. Rehearse with `--dry-run`; snapshot immediately before. |
| **The first real order placed on the root domain** | — | **The true point of no return.** No infra step is the commitment; this is. Rolling the root back to WordPress after real orders exist strands them. |

---

## 4. Open items that are cutover risk but not cutover steps

- **789 legacy customers hold loyalty points** (`wps_wpr_points`; 355,454 points total,
  largest holder 98,038). **DECIDED 2026-08-17: discarded.** The programme restarts from
  zero. Nothing to build; the balances simply stop existing when WordPress stops being the
  storefront. For the record, the aggregate was small — roughly ₦8.9 k at the plugin's own
  cart rate (200 points = 5 currency units), largest single holder about ₦2.5 k — and 7
  customers had already redeemed, so expect a handful of support questions rather than
  none. The data survives in `wp-20260817-1816.sql.gz` and on `old.` if you ever want to
  honour one by hand.
- **Legacy referral relationships** (91 users with `wps_points_referral`) do not carry
  into the new referral programme.
- **Google Merchant Center / Facebook catalogue feeds** are generated by WordPress
  plugins (`google-listings-and-ads`, `official-facebook-pixel`, `klaviyo`). After the
  flip they either stop or keep advertising `old.` URLs.
- **WordPress admin password rotation** from the rogue-email incident is still pending.
- Affiliates page hero image still missing.

---

## 5. Locking down `old.tokecosmetics.com` (2026-08-18)

The retired store is publicly reachable, runs an install with a malware history, and its
WordPress admin password has not been rotated since the rogue-email incident. A crawler
directive only persuades well-behaved bots, so the control is access, not a hint.

Config lives in `/var/webuzo-data/apache2/custom/domains/old.tokecosmetics.com.conf`
(the Webuzo-regeneration-proof include), and is three things:

1. **`X-Robots-Tag: noindex, nofollow`** on every response, including the 401s.
   **Not** a `robots.txt Disallow` as the primary control — `Disallow` blocks the *fetch*,
   so a crawler can never read the `noindex`, and any URL it already discovered lingers in
   the index as a bare listing. Disallow governs crawl budget; noindex governs presence.
2. **HTTP basic auth** on `/`, credentials in `/etc/httpd-old-tokecosmetics.htpasswd`
   (`0640 root:nobody`, apr1). Anonymous requests get 401.
3. **Two carve-outs**, because a more specific `<Location>` replaces the parent's
   `Require`:
   - `/wp-content/` — the live site 308s legacy image URLs here, so auth would break every
     image inside the 47 imported CMS pages. Verified end to end: live root → `old.` → 200.
   - `/robots.txt` — served by `Alias` from `/var/webuzo-data/apache2/custom/old-public/`,
     leaving the on-disk file alone (it is shared with the `.com.ng` vhost). The on-disk
     one is a **malware-era leftover**: dated Dec 2023, read-only, `Allow: /`, advertising
     seven sitemaps including `goods.php?sitemap322.xml` — the classic spam-sitemap
     injection pattern, pointed at the NEW domain. `goods.php` no longer exists, so it is
     inert, but it should never have been what this host tells crawlers.

The replacement keeps `/wp-content/` crawlable on purpose: pages on the live site
reference images here, and blocking them would make those pages render image-less to a
crawler. Nothing is indexable regardless, because of (1).

**Cloudflare caches `robots.txt`.** After changing it, purge that URL in the dashboard or
expect the stale copy to be served until the TTL lapses — verified with a cache-buster.

**When `old.` is retired for good**, the whole block can be deleted along with the vhost;
see the T+90d step. The credential file and `old-public/` should go with it.
