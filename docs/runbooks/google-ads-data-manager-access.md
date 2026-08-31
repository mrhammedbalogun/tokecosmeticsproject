# Getting Google Ads server-side conversions working (Data Manager API)

> **STATUS: DONE, 2026-08-30.** Hammed completed all seven steps. The whole chain was
> then verified against the live API with `validateOnly` — key, API enablement, Ads
> permission, customer id `3352855298`, conversion action id `7577766208`, and the
> customer-data terms all check out, and no manager account is involved. What remains is
> the key reaching `.env.prod`; see "After the handover" at the end.
>
> Two corrections were folded back into the steps below, both learned from the live API.

**Why we need it:** so a sale still reaches Google Ads when the customer never comes
back from the payment page. Payment is confirmed by a gateway *webhook*, and the
confirmation page gives up after five polls — a slow Paystack or Flutterwave settlement,
or a closed tab, means the browser tag never fires. Those purchases are invisible to
Google today, and they are the ones its bidding learns from.

**Who must do this:** you. Every step below needs either **Owner** on the
`tokecosmetics` Google Cloud project or **Admin** on the Google Ads account. None of it
can be done from the VPS, and none of it can be delegated to a key I already hold — the
Maps and Places keys are a different product entirely and cannot touch Ads data.

**Time:** ~30 minutes, all of it clicking. **No waiting on Google.** There is no
application and no approval queue — see the note below, because this is a change from
what I told you first.

---

## Read this first — the API changed under us

I originally said this needed the **Google Ads API**: an OAuth2 refresh token, a
developer token, and an access application Google reviews for up to 10 business days.

That path is now closed to us. On **15 June 2026** Google stopped accepting *new*
adopters of offline conversion imports through the Google Ads API — a developer token
that wasn't already importing between December 2025 and May 2026 simply gets an error.
Toke never has been, so that door was shut before we reached it.

The replacement is the **Data Manager API**, and it is genuinely lighter:

| | Google Ads API (closed to us) | Data Manager API |
|---|---|---|
| Developer token | Required, with an application | **None** |
| Access approval | 5-10 business days | **None** |
| Auth | OAuth2 refresh token + consent screen | **Service account key** |
| Google OAuth verification | Required for sensitive scopes | **Not required for service accounts** |

Google's full switchover is March 2027, so this is the path with a future, not a
workaround.

> **Confidence note.** The 15 June cutoff comes from three sources that agree (Search
> Engine Land, ppc.land, ALM Corp); Google's own announcement page would not render its
> body for me. It changes nothing about the steps below — Data Manager is the right
> target either way — but it is why I am not asking you to apply for anything.

---

## Before you start — have these open

| Thing | Value for Toke |
|---|---|
| Google Cloud project | **`tokecosmetics`** — the SAME project the Maps keys live in (`google-apis-setup.md`) |
| Google Ads account | the one running Toke's ads, signed in as **Admin** |
| Cloud console | <https://console.cloud.google.com/> |
| Ads console | <https://ads.google.com/> |

> Reuse the existing `tokecosmetics` project. A second project means a second billing
> story and a second set of credentials to lose track of, and buys nothing.

**One thing to check before anything else:** does the Ads account sit under a **manager
(MCC) account**? Look at the top of <https://ads.google.com/> — if you switch into Toke's
account from a manager account, it does. If it does, note the manager's ID too; step 6
needs both.

---

# Part A — Google Cloud (steps 1-3)

## Step 1 — Enable the Data Manager API

1. <https://console.cloud.google.com/> → top bar project picker → select
   **`tokecosmetics`**. Every step below happens inside this project.
2. **APIs & Services → Library** → search **"Data Manager API"** → **Enable**.

That is the whole step. Unlike the Business Profile API, it appears in the Library
immediately and needs no access request.

## Step 2 — Create the service account

A service account is a robot Google account. It is what the VPS will authenticate as,
which is why nothing here involves your personal login or a browser consent screen.

1. **IAM & Admin → Service Accounts** → **+ Create service account**.
2. **Name:** `toke-ads-conversions`
   **Description:** `Uploads purchase conversions to Google Ads (Plan-44)`
3. **Create and continue.**
4. **Grant this service account access to project:** add the role
   **Service Usage Consumer**. *(That is the only Cloud role it needs. It does NOT need
   Owner, Editor, or anything touching Maps.)*
5. **Continue → Done.**
6. On the service account list, **copy its email**. It looks like:
   `toke-ads-conversions@tokecosmetics.iam.gserviceaccount.com`
   **You need this string in step 4.** Keep it somewhere for a moment.

## Step 3 — Create and download its key

1. Click the service account → **Keys** tab → **Add key → Create new key**.
2. Choose **JSON** → **Create**. Your browser downloads a `.json` file.

> ### This file is a credential. Treat it like the Paystack secret key.
>
> Anyone holding it can write conversion data into Toke's ad account. So:
>
> - **Do not paste its contents into chat, email or WhatsApp.**
> - **Do not commit it.** It must never land anywhere under the repo.
> - It goes onto the VPS only, in Part C.
>
> If it ever leaks, the fix is one click: delete the key on this same **Keys** tab and
> create a new one. Nothing else breaks.

---

# Part B — Google Ads (steps 4-7)

## Step 4 — Give the service account access to the Ads account

This is the actual grant, and it is the step people get stuck on. It happens in **Google
Ads**, not in Cloud — being an admin of the Cloud project gives you nothing in Ads.

1. <https://ads.google.com/> → sign in as an **Admin** of the Toke account.
2. **Admin → Access and security** → **Users** tab → the **+** button.
3. In **Email**, paste the service account address from step 2
   (`toke-ads-conversions@…gserviceaccount.com`).
4. Access level: **Standard**. *(Not Admin — it never needs to manage users or billing.
   If a conversion upload is later refused with a permission error, this is the first
   thing to raise, but start at Standard.)*
5. **Add account.**

> **It will not send an invitation, and that is correct.** A normal user gets an email
> they must accept; a service account has no inbox and cannot. Google grants service
> account access immediately on **Add account**. If the row shows as pending or the
> invite appears to hang, you have almost certainly typed a normal email rather than the
> `…gserviceaccount.com` one.
>
> If the account sits under a **manager (MCC)**, adding the service account to the
> **manager** instead is the tidier choice — it then reaches every account underneath.

## Step 5 — Accept the customer data terms

Without this, Google refuses any upload carrying hashed customer data — which is most of
the value, because it is what matches a purchase back to the person who clicked the ad.

1. In Google Ads: **Goals → Settings** → expand **Customer data use**.
2. Turn on **enhanced conversions** and **accept the customer data terms**.

> Since June 2026 this is a single on/off switch rather than the old split between web
> and leads. If you have accepted these terms before, you may find it already on and
> migrated — that is fine, just confirm it reads as enabled.
>
> Under an MCC the terms usually have to be accepted **per account**, not once at the
> manager. Check Toke's own account, not just the parent.

## Step 6 — Copy the Google Ads customer ID

1. It is the 10-digit number at the top right of the Ads console, formatted
   `123-456-7890`.
2. Note it **without the dashes** — `1234567890` — that is the form the API takes.
3. **If the account sits under a manager**, note the manager's ID the same way. The API
   needs both: the manager is the `loginAccount`, Toke's own account is the
   `operatingAccount`.

## Step 7 — Find the conversion action ID

This names *which* conversion the uploads land on.

1. **Goals → Conversions → Summary**.
2. Click the **purchase** conversion action — the one that already counts website
   purchases.
3. Look at the browser's address bar. It contains `ctId=`:
   `https://ads.google.com/aw/conversions/detail?ocid=…&ctId=576882000`
   The number after `ctId=` — `576882000` here — is the conversion action ID.

> **If no purchase conversion action exists yet**, create one first:
> **Goals → Conversions → + New conversion action → Website**, category **Purchase**,
> value **Use different values for each conversion**, count **Every**. Then come back
> and read its `ctId`.
>
> **Do not create a separate "server" conversion action.** One action, fed by both the
> browser tag and the server, deduplicated on the order number — the same shape Meta,
> TikTok and Snapchat already use. Two actions is how a sale gets counted twice.

---

# Part C — Handing it over

## The five values I need

Paste these straight into chat — none of them is a secret. They are all readable by
anyone who can open the ad account, and they end up in the admin screen anyway.

| # | What | Looks like |
|---|---|---|
| 1 | Service account email | `toke-ads-conversions@tokecosmetics.iam.gserviceaccount.com` |
| 2 | Google Ads customer ID (no dashes) | `1234567890` |
| 3 | Manager (MCC) ID, **if there is one** | `9876543210`, or "none" |
| 4 | Conversion action ID | `576882000` |
| 5 | Confirmation | "customer data terms accepted" |

## The one thing that must not go in chat

The **JSON key file** from step 3.

> **CORRECTED 2026-08-30.** This section originally said to `scp` the file to
> `/opt/tokecosmetics/secrets/` and point an env var at the path. That was wrong for this
> deployment: the API container takes its whole configuration from
> `env_file: /opt/tokecosmetics/.env.prod` and mounts only static, media and the
> migration paths, so a key file would need a **new volume mount** — a compose edit, a
> deploy, and a second place a secret lives.
>
> Base64 into `.env.prod` instead. That file is already mode 0600, already holds every
> gateway key, and is already in the backup rotation.

```bash
# on your machine — one line, no newlines in the output
base64 -w0 ~/Downloads/tokecosmetics-website-xxxxx.json
```

Copy that string, then on the server append one line to `/opt/tokecosmetics/.env.prod`:

```
GOOGLE_ADS_DM_CREDENTIALS_B64=<the base64 string>
```

Back the env file up first, as every change to it does:

```bash
ssh tokecosmetics 'cp -a /opt/tokecosmetics/.env.prod \
  /opt/tokecosmetics/.env.prod.bak-$(date +%Y%m%d)-pre-googleads'
```

Then restart the API container so it picks the variable up.

> **Tell me when it is in place; do not tell me what is in it.** I never need to read it,
> and the moment it appears in a transcript it has to be rotated.
>
> **Then delete the JSON.** It has done its job. Since the 2026-08-30 workspace move it
> lives at `~/projects/TokeCosmeticsDev/GoogleAds/` (WSL), with the original still on the
> old `C:\Users\Hammed\Desktop\TokeCosmeticsDev\GoogleAds\` copy until that is cleaned up.
> Both are outside any git repo, so neither was ever at risk of being committed — but an
> unencrypted credential sitting on disk is still an unencrypted credential.

---

## What can go wrong

| Symptom | Cause |
|---|---|
| Service account row looks like a pending invite | You typed a normal email, not the `…gserviceaccount.com` one |
| Uploads refused, permission error | Service account is Read-only in Ads — raise it to Standard, then Admin |
| Uploads accepted, no conversions appear | Wrong `ctId`, or it was read from a *different* conversion action |
| Uploads refused mentioning terms | Step 5 not done, or done at the manager rather than on Toke's own account |
| Gmail customers never match | Ours, not yours — Google strips dots and `+tags` from gmail addresses before hashing, unlike Meta/TikTok/Snap. Handled in the adapter |
| A whole batch 400s on `postal_code` | Ours — `address.postalCode` is REQUIRED, not optional as the docs imply, and most Nigerian addresses have none. The adapter now omits the address entirely rather than sending it incomplete |
| Conversions counted twice | A second "server" conversion action was created. There must be exactly one |

## What happens after you send me the five values

1. I build the Data Manager adapter as a fifth channel, tested against the documented
   schema with fixtures — the same shape as the four already shipped.
2. It goes live **dark**, like the others: nothing sends until the channel is switched on
   in **admin.tokecosmetics.com/settings/marketing**.
3. First real proof is the **Send test event** button on that screen, then a real order.
4. Google Ads conversions take up to ~3 hours to surface in the UI, so the outbox at
   `/admin/marketing/events/` is the faster read on day one.

## What this does NOT change

The browser-side Google Ads tag stays exactly as it is. This is additive: the server
covers the purchases the browser misses, and the order number keeps them from being
counted twice.
