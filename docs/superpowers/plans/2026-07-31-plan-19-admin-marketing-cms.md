# Plan-19 — marketing and CMS

Master spec: `master-tokerebuild.md` §Plan-19-admin-marketing-cms. Branch off `main`
(`4ad46c6`).

**This stage is far larger than any before it** — the master spec asks for a whole new
backend app (four models, public endpoints, admin CRUD), seven admin surfaces, and a
storefront rewiring, in one line each. Plans 17 and 18 were both sliced after proving too
big; this one is bigger than either and is sliced here before a line is written.

---

## Grounding (measured in production 2026-07-31 — do not re-derive)

| | |
|---|---|
| `apps/cms/` | **does not exist**, in any form |
| Coupons | model exists (`checkout/models.py:8`) + redemption ledger · **0 coupons, 0 redemptions** |
| Coupon admin API | **none** — `checkout` has no `admin_urls.py` |
| Delivery options | 6, all active · **0 `DeliveryOptionRate` rows** (no weight tiers in use) |
| Regions | **811** — 37 `state`, 774 `area` |
| Delivery/region admin API | **none** |
| `CountryPaymentGateway` | 15 rows, 6 active · **no admin API** |
| `SiteSetting` | 0 rows · `Redirect` 0 rows |
| Storefront homepage | 11 hardcoded components, fed by `storefront/src/lib/home-content.ts` (89 lines) |
| Storefront `/page/{slug}` | a 3-line stub |

**Four facts shape the slicing, and they are not opinions:**

1. **The live storefront's footer has ELEVEN links into a stub.**
   `storefront/src/components/layout/Footer.tsx` links `/page/` for about, affiliates,
   blog, community, contact, faqs, privacy, returns, shipping, terms and wholesale. Every
   one of them renders
   `storefront/src/app/(shop)/page/[slug]/page.tsx`, whose entire body is the sentence
   **"CMS content arrives in Plan-19."** A shopper who clicks *Privacy policy* on a store
   taking real money is shown the name of an unbuilt internal plan. That is the single
   most embarrassing thing left in this codebase.

2. **A role exists whose whole job is this stage.** `cms.manage` is declared in
   `accounts/rbac.py:94` and held by `Owner` and `Content`; **no endpoint anywhere
   declares it** (only `core/admin_search.py` mentions it, to explain why a Content editor
   gets an empty result). `admin/src/lib/nav.ts:42` shows that person a "Content" link that
   404s. We shipped a role that can log in and do nothing.

3. **Turning card payments on currently needs a developer.** Plan-09's gateways are
   code-complete and deactivated; `CountryPaymentGateway` has no admin API, so the switch
   that makes Paystack live is a row edit in production Postgres.

4. **The homepage seam already exists.** `home-content.ts:1-4` says in its own docstring
   that it "IS the CMS until Plan-19 ships real content models — keep it typed and boring
   so Plan-19 can swap each export for an API call without touching the section
   components." Replacing fixtures with API calls is therefore cheap. **Building the
   builder UI that edits them is not**, and the two must not be conflated.

---

## Design rulings

### 1. Rich text: NO TipTap. The same textarea the product editor already ships

The master spec says "rich text — use TipTap". Declined, on three grounds:

- **The corpus is about eleven pages of policy prose**, written once and edited rarely.
  A block editor is a large client dependency and a new content format to store, migrate
  and render, bought for a job a textarea does.
- **The product editor already made this decision**, and this surface should not disagree
  with it: `DetailsPanel` ships a plain HTML textarea under the words "HTML is allowed and
  is rendered as-is". Two different authoring models for two kinds of stored HTML is a
  worse outcome than one plain one.
- **TipTap would not reduce the real risk, which is XSS.** Its output is still HTML, still
  stored, still rendered by the storefront.

If Hammed wants a WYSIWYG later, it can be added over the same field.

### 2. Sanitise on write, in THIS plan, not in Plan-25

Plan-25 lists "product descriptions/CMS bodies sanitized server-side with a `bleach`
allowlist — this is stored HTML rendered by the storefront!" among its hardening tasks.
Deferring it is wrong here for one specific reason: **Plan-19 is the stage that invalidates
the assumption the current code is written on.** The storefront renders stored HTML through
`dangerouslySetInnerHTML` at `components/product/PdpAccordions.tsx:23`, and the comment
four lines above it states the premise out loud: *"`description` is backend-authored rich
HTML (trusted admin content)."*

That is true today, when the only author is Hammed. This stage adds page bodies authored by
a `Content` role that is deliberately **not** trusted with orders or products — so the
sentence stops being true in the same release that adds the field. A lower-privileged
editor would gain script execution on the storefront's origin, which is where customers
type card details.

So the sanitiser lands with the model, applied on save, and the existing product
descriptions are backfilled through it. No new dependency is added blindly: `nh3`
(Rust `ammonia` bindings, maintained) is preferred over `bleach`, which the Python
community has deprecated.

### 3. A page is CONTENT, not a route

`Page.slug` addresses `/page/{slug}` on the storefront, and the eleven footer links are
already written. So the admin must not be able to orphan them: deleting or unpublishing a
page that a menu or the footer links to is a 404 on a live store. Publishing state is a
field, deletion is not offered in 19a, and the storefront renders a missing page as a
proper 404 rather than the current stub.

### 4. The gateway switch is not a CMS feature, and it is in this plan anyway

`CountryPaymentGateway` CRUD is in the master spec's Plan-19 list, which is where the
oddity comes from. It stays, because it is four fields and a toggle over an existing model,
it removes a production-Postgres edit from the launch runbook, and there is no other plan
that would claim it. It is NOT behind `cms.manage` — it is `orders.manage`, because
turning a payment method on is a money decision, not a content one.

---

## Sequencing

**19a — Pages, and the gateway switch.** The CMS app with `Page` only; sanitise-on-write;
public `GET /cms/pages/{slug}/`; admin CRUD behind `cms.manage`; the storefront route
wired and a real 404; the eleven footer slugs seeded as drafts so nothing 404s on cutover.
Plus `CountryPaymentGateway` CRUD behind `orders.manage`. **This is the slice with launch
consequences**: it clears the eleven stub links and gives the `Content` role its first
reason to exist.

**19b — Coupons.** Admin CRUD and usage stats over the existing model and its ledger. The
launch marketing lever; cheap, because the backend is done and only the API and UI are
missing.

**19c — Homepage, banners and menus.** `Banner`, `HomepageSection`, `MenuItem`, their
public endpoints, the builder UI, and the storefront swap at `home-content.ts`. Deliberately
after 19b: the homepage already looks right, so this buys editability rather than
capability.

**19d — Delivery manager and the regions browser.** Delivery options CRUD, weight tiers,
the 811-region coverage tree and the "test an address" widget. Last because the six options
work today and this is the largest single UI in the stage.

**Storefront revalidation** belongs with whichever slice first serves live content (19a),
and is scoped there rather than as a separate task.

---

## Risks

- **811 regions in one tree control** is the hardest UI in the plan and it is in the last
  slice. If 19d is ever cut for time, NG delivery still works — that is the point of
  putting it there.
- **Seeded draft pages are a promise.** Creating eleven empty pages so the footer resolves
  is only an improvement if somebody writes them; an empty "Privacy policy" is worse than a
  missing one, legally. 19a must ship them as real drafts with Hammed's text, or leave the
  links out of the footer.
- **`Content` is a role nobody has held yet.** Its first real use is this stage, and the
  role matrix test asserts a nav shape that will change.
