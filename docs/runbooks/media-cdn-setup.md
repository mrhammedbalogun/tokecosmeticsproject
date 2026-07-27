# Runbook — turn on product images in production (CloudFront + OAC)

**Who:** Hammed, in the AWS console. ~15 minutes of clicking, then a few minutes for
CloudFront to deploy. This cannot be automated from the VPS: the `claude-access` IAM user
has S3 permissions but **no CloudFront permissions**.

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
