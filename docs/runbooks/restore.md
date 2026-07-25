# Runbook — restoring the database

Read this **before** you need it. The steps that promote a restore to live stop the
API, and doing that for the first time while the store is down is the wrong moment
to be reading documentation.

Everything runs as root on the VPS (`ssh tokecosmetics`). Throughout:

```bash
COMPOSE="docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod -f /opt/tokecosmetics/repo/infra/docker-compose.prod.yml"
```

---

## Where the backups are

| | |
|---|---|
| On the box | `/opt/tokecosmetics/backups/toke-YYYYmmdd-HHMMSS.sql.gz` — last 14 days |
| In S3 | `s3://tokecosmetics-assets-899805259502-eu-west-1-an/backups/postgres/` (eu-west-1) |
| Schedule | 02:30 UTC nightly, root's crontab |
| Log | `/var/log/toke-backup.log` |
| Scripts | `infra/deploy/backup.sh`, `infra/deploy/restore.sh` |

**A file named `*.sql.gz.rejected`** is a dump that failed its own safety checks and
was deliberately parked. It is evidence, not a backup. Do not restore from one
without reading `/var/log/toke-backup.log` to find out why it was rejected — and
note that once a dump is rejected, **every subsequent night will also fail** until
someone intervenes. That is by design; silence after one alert would be worse.

### Is the backup actually running?

```bash
tail -20 /var/log/toke-backup.log
ls -la /opt/tokecosmetics/backups/
```

The last line of a good run reads `backup ok:`. A failure also emails
billztechnologiesofficial@gmail.com — treat that email as best-effort (it leaves a
shared mail server and may be filtered), so check the log periodically rather than
trusting silence to mean success.

---

## Getting a dump back from S3

The host has no `aws` CLI on purpose. Download through the `web` container, which
already has boto3 and the credentials:

```bash
# list what is in S3
$COMPOSE exec -T web python -c "
import os, boto3
b = os.environ['AWS_STORAGE_BUCKET_NAME']
s3 = boto3.client('s3', region_name=os.environ.get('AWS_S3_REGION_NAME'))
for o in sorted(s3.list_objects_v2(Bucket=b, Prefix='backups/postgres/').get('Contents', []),
                key=lambda o: o['LastModified']):
    print(o['LastModified'].isoformat(), o['Size'], o['Key'])
"

# pull one down to /opt/tokecosmetics/backups/
KEY=backups/postgres/toke-20260725-183932.sql.gz
$COMPOSE exec -T -e S3_KEY="$KEY" web python -c "
import os, sys, boto3
b = os.environ['AWS_STORAGE_BUCKET_NAME']
s3 = boto3.client('s3', region_name=os.environ.get('AWS_S3_REGION_NAME'))
s3.download_fileobj(b, os.environ['S3_KEY'], sys.stdout.buffer)
" > "/opt/tokecosmetics/backups/$(basename $KEY)"
```

Check the size matches what S3 listed before you trust it.

---

## Step 1 — restore into a scratch database (always do this first)

This never touches the live database. It is safe to run any time, including right
now, and it is the only thing that proves a backup is real.

```bash
/opt/tokecosmetics/repo/infra/deploy/restore.sh /opt/tokecosmetics/backups/toke-20260725-183932.sql.gz
```

It creates `toke_restore_test`, restores with `ON_ERROR_STOP=1` (so a restore that
throws errors *fails* rather than quietly finishing half-done), and prints row
counts:

```
tables|58
django_migrations|68
users|0
orders|0
products|0
regions|811
```

**Judge those numbers against what you expect.** As of 2026-07-25 the production
database is a fresh schema plus reference seed data — 811 regions, no products, no
orders — because the catalogue arrives in Plan-21. Once real orders exist, an
`orders` count of 0 in a restore means the restore is wrong, not that business was
slow.

Drop the scratch database when you're done:

```bash
$COMPOSE exec -T postgres psql -U toke -d postgres -c 'DROP DATABASE "toke_restore_test";'
```

Note the credentials are `toke` / `toke` — **not** `tokecosmetics`. Guessing that
gets you `role does not exist`.

---

## Step 2 — promoting a restore to live

Only after Step 1 succeeded and the row counts looked right. **This is a real
outage**: the API returns 502 for its duration, a couple of minutes. The store on
WordPress is a separate stack and stays up throughout.

```bash
# 1. Stop everything that writes. Postgres stays up — we need it to run the swap.
$COMPOSE stop web worker beat

# 2. Take a dump of the CURRENT broken database anyway. You may need to pick
#    records out of it later, and this is your last chance.
$COMPOSE exec -T postgres pg_dump -U toke -d toke | gzip > /opt/tokecosmetics/backups/pre-restore-$(date +%Y%m%d-%H%M%S).sql.gz

# 3. Restore the good dump into a fresh database under a new name.
/opt/tokecosmetics/repo/infra/deploy/restore.sh /opt/tokecosmetics/backups/<good-dump>.sql.gz toke_new

# 4. Swap the names. Renaming requires no other session to be connected to `toke`;
#    step 1 is what makes that true.
$COMPOSE exec -T postgres psql -U toke -d postgres \
    -c 'ALTER DATABASE "toke" RENAME TO "toke_broken";' \
    -c 'ALTER DATABASE "toke_new" RENAME TO "toke";'

# 5. Bring the app back.
$COMPOSE start web worker beat

# 6. Prove it.
curl -s https://api.tokecosmetics.com/healthz/
```

**Keep `toke_broken`.** Do not drop it the same day. It costs a little disk and it
is the only copy of whatever was in the database at the moment things went wrong.
Drop it once you are certain, days later:

```bash
$COMPOSE exec -T postgres psql -U toke -d postgres -c 'DROP DATABASE "toke_broken";'
```

If step 4 fails with *"database is being accessed by other users"*, something
reconnected. Find it and stop it:

```bash
$COMPOSE ps
$COMPOSE exec -T postgres psql -U toke -d postgres -c \
  "SELECT pid, usename, application_name, state FROM pg_stat_activity WHERE datname='toke';"
```

---

## What this procedure does not cover

- **Uploaded media** (product images) lives in `/opt/tokecosmetics/data/media` and in
  S3, not in the database dump. A database restore does not bring images back.
- **Point-in-time recovery.** These are nightly snapshots, so the worst case is
  losing up to 24 hours of orders. If that becomes unacceptable once real revenue
  is flowing, the answer is WAL archiving, not more frequent dumps.
- **The dump is schema + data for one database.** Roles and cluster-level settings
  are not included; they are recreated by the compose file and the migrations.

## Restore test log

Keep this current. A backup nobody has restored is a hope, not a backup.

| Date | Dump | Result |
|---|---|---|
| 2026-07-25 | `toke-20260725-183932.sql.gz` | Restored clean into scratch. 58 tables, 68 migrations, 811 regions, 0 users/orders/products — matching live. Schema-and-seed only; **this has not yet been tested against a database with real order data.** Re-run after Plan-21. |
