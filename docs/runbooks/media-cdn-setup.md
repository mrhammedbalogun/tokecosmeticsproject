# Runbook — turn on product images in production (CloudFront + OAC)

**Who:** Hammed, in the AWS console — but see **Option B**, which reduces your part to one
policy attachment and moves the error-prone step to Claude.

Why it can't be fully automated today (verified 2026-07-27, not assumed):

| Identity | CloudFront | IAM |
| --- | --- | --- |
| `claude-access` (on the VPS, account `899805259502`) | **AccessDenied** | **AccessDenied** — so it cannot grant itself more |
| `cowva-dev-cli` (on Hammed's laptop) | **AccessDenied** | account **`120569621402`** — a different AWS account entirely, not TokeCosmetics |

---

## Option B (recommended) — one IAM attachment, then Claude does the rest

Attach a CloudFront-only policy to `claude-access` and tell Claude. Claude then creates the
OAC and the distribution, and hands you the **complete, final bucket policy JSON to paste
verbatim — no editing**, which removes the one step in Option A you could get wrong.

IAM console → Users → `claude-access` → Add permissions → Create inline policy → JSON:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "MediaCdnSetup",
      "Effect": "Allow",
      "Action": [
        "cloudfront:CreateOriginAccessControl",
        "cloudfront:GetOriginAccessControl",
        "cloudfront:ListOriginAccessControls",
        "cloudfront:CreateDistribution",
        "cloudfront:GetDistribution",
        "cloudfront:GetDistributionConfig",
        "cloudfront:ListDistributions",
        "cloudfront:TagResource"
      ],
      "Resource": "*"
    }
  ]
}
```

Two things stated plainly rather than buried:

- **`"Resource": "*"` is required** — CloudFront's create actions do not support
  resource-level restriction. So this grants distribution-creation across the account, not
  just for this bucket. It grants **no S3 write and no IAM**.
- **`s3:PutBucketPolicy` is deliberately NOT included.** The one action that could expose
  the backups stays with you: Claude generates the exact policy text, you paste it. Detach
  the inline policy afterwards if you like — it is only needed once.

Then skip to Step 4 and send Claude a message saying the policy is attached.

---

## Option A — do it all yourself

~15 minutes of clicking, then a few minutes for CloudFront to deploy.

**Why it's needed:** every product image on `next.tokecosmetics.com` is currently broken.
The images live in a private S3 bucket and nothing can read them. Full reasoning in
`docs/architecture.md` § "Production media serving".

**Why we are NOT just making the bucket public:** the nightly **database backups live in
the same bucket** (`backups/` next to `catalog/`). Making it publicly readable means
switching off the safety setting that guarantees those backups can never be exposed — on a
bucket that has no versioning. CloudFront gets us the images while the bucket stays locked.

Bucket: `tokecosmetics-assets-899805259502-eu-west-1-an` (region **eu-west-1**)

---

## Step 1 — Create the CloudFront distribution

1. AWS console → **CloudFront** → **Create distribution**.
2. **Origin domain:** start typing the bucket name and pick the **S3 bucket** entry. Make
   sure the value ends in **`.s3.eu-west-1.amazonaws.com`** (the *regional* endpoint). If it
   offers the plain `.s3.amazonaws.com` form, choose the regional one.
3. **Origin access:** choose **Origin access control settings (recommended)**.
   - Click **Create new OAC**, accept the defaults, **Create**.
   - Leave it selected.
4. **Viewer protocol policy:** **Redirect HTTP to HTTPS**.
5. **Cache policy:** **CachingOptimized**.
6. Leave everything else at defaults. **Create distribution.**
7. Copy the **Distribution domain name** — it looks like `d1a2b3c4d5e6f7.cloudfront.net`.
   **Send me this value.**

## Step 2 — Attach the bucket policy, with ONE edit

After creating the distribution, CloudFront shows a blue banner:
*"The S3 bucket policy needs to be updated"* with a **Copy policy** button.

1. Click **Copy policy**.
2. Click the link to go to the bucket's **Permissions** tab → **Bucket policy** → **Edit**.
3. Paste it, then **make this one change**: find the `"Resource"` line, which will end
   `.../*`, and change it so it ends **`/catalog/*`**:

   ```
   "Resource": "arn:aws:s3:::tokecosmetics-assets-899805259502-eu-west-1-an/catalog/*"
   ```

   **This edit is the point of the whole exercise.** Without it, the CDN could serve
   anything in the bucket — including the database backups. With it, CloudFront can reach
   product images only.
4. **Save changes.**

> Do **not** touch "Block public access" — all four settings must stay **On**. The policy
> above works with them on, because it grants access to CloudFront specifically rather than
> to the public.

## Step 3 — Optional but recommended, while you're in there

On the bucket → **Properties** → **Bucket Versioning** → **Enable**.

One checkbox. Production now holds real records (user #1 and order `TC-100001`), and
tonight's database dump goes into this bucket, which is currently unversioned and writable
*and deletable* by the key on the VPS. Versioning means a bad delete is recoverable. This
is the cheapest possible down-payment on a risk we parked earlier. Your call.

---

## Step 4 — Tell me the distribution hostname

Once you send it, I will:

1. Verify the CDN serves an image (`curl` returns **200**) **while the same object on the
   S3 hostname still returns 403** — proving the bucket stayed private.
2. Confirm all four Block Public Access flags are still on.
3. Set `NEXT_PUBLIC_MEDIA_HOST` in Vercel (you may need to add it — env vars need a
   redeploy to take effect).
4. Add `AWS_S3_CUSTOM_DOMAIN` to `/opt/tokecosmetics/.env.prod` and restart the API
   containers — I will back the file up and confirm with you first, as with any
   production write.
5. Re-check a production product page and the Open Graph / structured-data image URLs.

**Order matters:** the distribution has to be serving before the API starts emitting CDN
URLs, so please don't set anything yourself — just send me the hostname.

---

## Also fixed on this branch (ships with the next backend deploy)

`verify_email.subject.txt` was the only one of nine email subjects spelling the brand
"Toké" instead of "Toke". Spotted in a real delivered email during the production order
test.
