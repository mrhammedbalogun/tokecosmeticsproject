# Runbook — catalogue migration (Plan-21)

Moves the live WooCommerce catalogue into the platform. Every command here runs
on the VPS as root, from `/opt/tokecosmetics/repo`.

Three properties this runbook is built to preserve. Do not trade any of them for
convenience on a re-run:

1. **The WordPress database is only ever read**, by a user that cannot see
   anything but five `wp_` tables.
2. **The credential never lands in `.env.prod`, in a shell history, or in a
   `docker inspect`.** It is passed per-invocation from a `600` file.
3. **Hand-entered stock counts are never overwritten.** See section 6.

## 0. How the container reaches MariaDB — read this before changing hosts

MariaDB binds `127.0.0.1` only (`/etc/my.cnf`: `bind-address=127.0.0.1`), so a
container **cannot** reach it over TCP, and `WP_DB_HOST=172.17.0.1` will simply
fail to connect. It dials the unix socket instead, bind-mounted read-only for the
life of the one-off container:

```
-v /var/lib/mysql/mysql.sock:/run/wp-mysql/mysql.sock:ro
-e WP_DB_HOST=/run/wp-mysql/mysql.sock
```

`wp_reader.wp_connection()` treats a `WP_DB_HOST` starting with `/` as a socket
path. A read-only bind mount is fine for a socket — the mount flag gates writes
to regular files, while `connect()` is gated by the socket's own mode bits
(`srwxrwxrwx`); verified on this box 2026-07-26.

Do **not** "fix" this by rebinding MariaDB. That restarts the database behind the
live WordPress store and leaves it listening on a box where `ufw` is inactive and
Docker rewrites iptables, all to save a bind mount.

## 1. Create the scoped reader (once)

Socket connections authenticate as `@'localhost'` — that is why the grant is
`'wp_readonly'@'localhost'` and not `@'172.17.%'`.

```bash
PW=$(openssl rand -base64 24)
umask 077 && printf 'WP_DB_PASSWORD=%s\n' "$PW" > /root/wp-readonly.env
mysql -e "
CREATE USER IF NOT EXISTS 'wp_readonly'@'localhost' IDENTIFIED BY '$PW';
GRANT SELECT ON tokecosm_wp481.wp_posts TO 'wp_readonly'@'localhost';
GRANT SELECT ON tokecosm_wp481.wp_postmeta TO 'wp_readonly'@'localhost';
GRANT SELECT ON tokecosm_wp481.wp_terms TO 'wp_readonly'@'localhost';
GRANT SELECT ON tokecosm_wp481.wp_term_taxonomy TO 'wp_readonly'@'localhost';
GRANT SELECT ON tokecosm_wp481.wp_term_relationships TO 'wp_readonly'@'localhost';
FLUSH PRIVILEGES;"
unset PW
```

### Prove the grant is actually limited

This is the check that makes the whole credential argument real. Run both.

```bash
set -a; . /root/wp-readonly.env; set +a
mysql -u wp_readonly -p"$WP_DB_PASSWORD" tokecosm_wp481 -e "SELECT COUNT(*) FROM wp_users;"
```

Expected: `ERROR 1142 (42000): SELECT command denied to user 'wp_readonly'@'localhost' for table 'wp_users'`.
**If it returns a count instead, stop and fix the grant.**

```bash
mysql -u wp_readonly -p"$WP_DB_PASSWORD" tokecosm_wp481 -e "SELECT COUNT(*) FROM wp_posts WHERE post_type='product';"
```

Expected: **99**. That is the source-of-truth baseline, measured 2026-07-26:

| `post_type` | `post_status` | rows |
|---|---|---|
| product | publish | 69 |
| product | importing | 27 |
| product | draft | 2 |
| product | private | 1 |
| product_variation | publish | 71 |

The extract takes `publish` + `draft` only, so it emits **71 products, 71
variations, 222 terms** (40 `product_cat` + 137 `product_tag` + 45 `pa_*`). The 27
`importing` rows are a stalled WooCommerce importer's leftovers and are excluded
by design — confirm none of them is a product you expect to sell before signing
off the import.

If the count is not 99, you are pointed at the wrong database. Cross-check with
`product_type`: this store is 80 simple / 19 variable.

### Create the exports directory (once)

The container writes here as uid 10001, so the directory must be owned by it.
Letting Docker autocreate the mount point would leave it `root:root` and every
export would fail on permission.

```bash
install -d -o 10001 -g 10001 -m 755 /opt/tokecosmetics/exports
```

## 2. Extract

The uploads and exports mounts live in `docker-compose.prod.yml`, so the
containers must have been recreated since that change landed — i.e. after the
`backend-v0.2.0` deploy. `docker compose ps` showing a create time older than the
deploy means the mounts are not there.

```bash
cd /opt/tokecosmetics/repo
set -a; . /root/wp-readonly.env; set +a
docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod \
  -f infra/docker-compose.prod.yml run --rm \
  -v /var/lib/mysql/mysql.sock:/run/wp-mysql/mysql.sock:ro \
  -e WP_DB_HOST=/run/wp-mysql/mysql.sock \
  -e WP_DB_NAME=tokecosm_wp481 \
  -e WP_DB_USER=wp_readonly \
  -e WP_DB_PASSWORD \
  web python manage.py extract_wp_catalog --out /mnt/exports/catalog-export.json
```

`-e WP_DB_PASSWORD` with **no value** forwards the variable from the shell. Never
write `-e WP_DB_PASSWORD=<secret>`: that puts the credential in root's shell
history and in `docker inspect` on a box that has been compromised before.

Expected: `Wrote /mnt/exports/catalog-export.json: 71 products, 71 variations, 222 terms, ...`

## 3. Review, then dry run

Read `/opt/tokecosmetics/exports/catalog-export.json` before importing anything.
It is the reviewable artifact — the whole point of the extract/import split.

```bash
docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod \
  -f infra/docker-compose.prod.yml exec -T web \
  python manage.py import_catalog /mnt/exports/catalog-export.json --dry-run
```

`--dry-run` rolls back Postgres and skips S3 uploads. Any new non-database side
effect added later must check the flag itself — see the `import_catalog`
docstring.

## 4. Back up, then import

The backup is not optional. This is the first write of production catalogue data.

```bash
/opt/tokecosmetics/repo/infra/deploy/backup.sh
docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod \
  -f infra/docker-compose.prod.yml exec -T web \
  python manage.py import_catalog /mnt/exports/catalog-export.json
```

## 5. Verify

```bash
docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod \
  -f infra/docker-compose.prod.yml exec -T web \
  python manage.py verify_catalog /mnt/exports/catalog-export.json --out-dir /mnt/exports
```

Worklists land in `/opt/tokecosmetics/exports/`: `pricing-todo.csv`,
`stock-todo.csv`, `description-review.csv`. To hand them over, **copy** them —
do not `chown` the exports directory, or the next run cannot write to it:

```bash
install -d -o tokecosm -g tokecosm -m 750 /home/tokecosm/migration-worklists
cp /opt/tokecosmetics/exports/*.csv /home/tokecosm/migration-worklists/
chown tokecosm:tokecosm /home/tokecosm/migration-worklists/*.csv
```

That directory is outside `public_html` on purpose: the worklists carry cost and
pricing columns and must not be web-served.

## 6. THE STOCK RULE — read before any re-run

Once real Lagos/UK counts have been entered by hand, **every subsequent run must
pass `--skip-stock`**, including the Plan-27 cutover run:

```bash
... python manage.py import_catalog /mnt/exports/catalog-export.json --skip-stock
```

The importer also refuses on its own to touch any `StockItem` whose latest
movement is not `migration`, and prints `protected <sku>` for each. `--force-stock`
overrides that guard and will destroy hand-entered counts. Do not use it.

`--skip-prices` is the equivalent for pricing. NGN prices are delete-and-recreate
on every run; GBP/USD/CAD prices are a different currency and are never touched.

## 7. After cutover

```bash
mysql -e "DROP USER 'wp_readonly'@'localhost';"
shred -u /root/wp-readonly.env
```

Then remove the two migration-only mounts (`/mnt/wp-uploads-ng`, `/mnt/exports`)
from `infra/docker-compose.prod.yml`.
