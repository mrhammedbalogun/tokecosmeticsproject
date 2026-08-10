# Presigned video uploads — bucket + CDN configuration

Feature: `docs/superpowers/specs/2026-08-09-presigned-video-uploads-design.md`.
The admin uploads video straight from the browser to S3 (`incoming/` quarantine prefix),
then the API verifies and copies it to `catalog/library/`. Three pieces of infrastructure
make that safe; all three live as JSON in `infra/aws/` and are applied with the `toke`
profile.

**⚠️ This bucket (`tokecosmetics-assets-899805259502-eu-west-1-an`) holds the only
off-box database backups under `backups/postgres/`. Every write below gets Hammed's
explicit go-ahead first, and every write is followed by a read-back.**

## 1. Bucket CORS — `infra/aws/bucket-cors.json`

The browser POSTs to the bucket origin directly, so the bucket must answer preflights
from the admin origin. The pre-2026-08-10 rule contained `https:tokecosmetics.com`
(missing `//`) which never matched any browser.

```bash
aws s3api put-bucket-cors --profile toke --bucket tokecosmetics-assets-899805259502-eu-west-1-an --cors-configuration file://infra/aws/bucket-cors.json
aws s3api get-bucket-cors --profile toke --bucket tokecosmetics-assets-899805259502-eu-west-1-an
```

Read-back must show every origin starting `https://` or `http://localhost`.

## 2. Lifecycle — `infra/aws/incoming-lifecycle.json`

Expires abandoned uploads in `incoming/` after 1 day.

**`put-bucket-lifecycle-configuration` REPLACES the whole configuration.** The bucket
already carries `Toke_LifeCycle` (scoped `backups/postgres/` — noncurrent-version and
delete-marker hygiene), so the JSON contains BOTH rules. Never apply a lifecycle JSON to
this bucket without the `Toke_LifeCycle` rule in it, and never a rule without a
`Filter.Prefix` — an unfiltered rule applies to the whole bucket, backups included.

```bash
aws s3api put-bucket-lifecycle-configuration --profile toke --bucket tokecosmetics-assets-899805259502-eu-west-1-an --lifecycle-configuration file://infra/aws/incoming-lifecycle.json
aws s3api get-bucket-lifecycle-configuration --profile toke --bucket tokecosmetics-assets-899805259502-eu-west-1-an
```

Read-back must show exactly two rules with prefixes `backups/postgres/` and `incoming/`.
**If any rule comes back without a prefix, `aws s3api delete-bucket-lifecycle` immediately
and stop.**

## 3. CloudFront `nosniff` — response headers policy

Distribution `E3RM3YPEKZS13G` shipped with `ResponseHeadersPolicyId: null`. Uploaded
media is served with a server-set Content-Type; `X-Content-Type-Options: nosniff` stops
a browser second-guessing it.

```bash
aws cloudfront create-response-headers-policy --profile toke --response-headers-policy-config '{
  "Name": "toke-media-security-headers",
  "SecurityHeadersConfig": {
    "ContentTypeOptions": { "Override": true },
    "StrictTransportSecurity": { "Override": true, "AccessControlMaxAgeSec": 31536000, "IncludeSubdomains": true }
  }
}'
```

Then `get-distribution-config` → set `DefaultCacheBehavior.ResponseHeadersPolicyId` to
the returned id → `update-distribution --if-match <ETag>`. Verify after the distribution
redeploys (a few minutes):

```bash
curl -sI https://dk4ivng9pnc2t.cloudfront.net/catalog/library/<any-key>
# expect: x-content-type-options: nosniff
```

## App-side env

- Admin (Vercel + `.env.local`): `NEXT_PUBLIC_UPLOAD_BUCKET_HOST=tokecosmetics-assets-899805259502-eu-west-1-an.s3.eu-west-1.amazonaws.com`
  (goes into the CSP `connect-src`; without it the browser blocks its own upload).
