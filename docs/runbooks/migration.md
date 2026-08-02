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

---

# Runbook — customer migration (Plan-22)

Same box, same socket, same forwarding discipline as the catalogue above. Read §0 first if
you have not; nothing about how the container reaches MariaDB changes here.

**What is different, and why it deserves its own runbook:** the catalogue artifact is
product data. This one is ~977 real password hashes, names, emails and phone numbers, and
it is read by a credential that can see every user row on three stores. Everything below
that looks like ceremony is about that difference.

## 1. Create the migration credential — AT EXTRACT TIME, NOT BEFORE

`wp_migration`, **not** `wp_readonly`. Granting these tables to `wp_readonly` would hand
the recurring catalogue import permanent access to every password hash on the estate. The
two users exist precisely so that one of them can be short-lived.

Every day this credential exists unused is exposure on a box that is being actively
probed. Create it when you are about to extract; drop it in §6.

```bash
PW=$(openssl rand -base64 30)
umask 077 && printf 'WP_DB_PASSWORD=%s\n' "$PW" > /root/wp-migration.env
mysql -e "
CREATE USER IF NOT EXISTS 'wp_migration'@'localhost' IDENTIFIED BY '$PW';
$(for db_prefix in 'tokecosm_wp481 wp_' 'tokecosm_wp481 wp8n_' 'tokecosm_usawp100 wp8n_'; do
    set -- $db_prefix
    for t in users usermeta wc_orders wc_order_addresses wc_order_operational_data \
             woocommerce_order_items woocommerce_order_itemmeta; do
      echo "GRANT SELECT ON $1.$2$t TO 'wp_migration'@'localhost';"
    done
  done)
GRANT SELECT ON tokecosm_usawp100.wp8n_posts TO 'wp_migration'@'localhost';
GRANT SELECT ON tokecosm_usawp100.wp8n_postmeta TO 'wp_migration'@'localhost';
FLUSH PRIVILEGES;"
unset PW
```

23 tables: seven per store prefix, plus `posts`/`postmeta` on the intl prefix only — the
intl store has 13 orders from 2023 that HPOS never backfilled into `wc_orders`, and Plan-23
loses them silently without those two. `wc_order_operational_data` is in the list because
in HPOS `wc_orders` has **no `date_paid_gmt` column**; leaving it out fails Plan-23
partway through with `ERROR 1142`, not at approval time.

### Prove the grant is limited — run all three

The negative checks are the only part that proves the positive list was exhaustive. The
first must print numbers; the second and third **must** fail with `ERROR 1142`.

```bash
set -a; . /root/wp-migration.env; set +a
mysql -u wp_migration -p"$WP_DB_PASSWORD" -e \
  "SELECT COUNT(*) FROM tokecosm_wp481.wp_wc_order_operational_data;"
mysql -u wp_migration -p"$WP_DB_PASSWORD" -e \
  "SELECT COUNT(*) FROM tokecosm_usawp100.wpstg0_users;"   # MUST fail — WP-Staging copy
mysql -u wp_migration -p"$WP_DB_PASSWORD" -e \
  "SELECT COUNT(*) FROM tokecosm_wp481.wp_options;"        # MUST fail
```

`wpstg0_users` matters most: the WP-Staging copy shares the intl database, so "the grant
does not reach it" is an assumption until a query proves otherwise.

## 2. Extract — once per store

Three stores, three runs, three artifacts. `--store` labels the artifact and must match
the prefix being read; getting them out of step writes `LegacyIdentity` rows that point at
the wrong store and mislinks order history in Plan-23.

| `--store` | `WP_DB_NAME` | `WP_TABLE_PREFIX` |
|---|---|---|
| `legacy_ng` | `tokecosm_wp481` | `wp_` |
| `legacy_ng_old` | `tokecosm_wp481` | `wp8n_` |
| `legacy_intl` | `tokecosm_usawp100` | `wp8n_` |

```bash
cd /opt/tokecosmetics/repo
set -a; . /root/wp-migration.env; set +a
docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod \
  -f infra/docker-compose.prod.yml run --rm \
  -v /var/lib/mysql/mysql.sock:/run/wp-mysql/mysql.sock:ro \
  -e WP_DB_HOST=/run/wp-mysql/mysql.sock \
  -e WP_DB_NAME=tokecosm_wp481 \
  -e WP_TABLE_PREFIX=wp_ \
  -e WP_DB_USER=wp_migration \
  -e WP_DB_PASSWORD \
  web python manage.py extract_wp_customers --store legacy_ng \
      --out /mnt/exports/customers-legacy_ng.json
```

`-e WP_DB_PASSWORD` with **no value** again — never `-e WP_DB_PASSWORD=<secret>`.

The command writes the file `0600` before any content enters it and prints a warning
saying so. Expect roughly 695 / 285 / 13 customers. It reads only users with **at least
one order**: the stores are under an automated signup flood (intl went 51 → 3,284 users
between 14 July and 1 August, none of whom ever ordered), and that filter is what keeps
several thousand spam accounts out of the new platform.

## 3. Dry run, then import

Import order does not matter — cross-store precedence is decided by
`accounts.best_store`, not by which artifact ran first. Do all three dry runs before any
real one.

```bash
docker compose ... run --rm web python manage.py import_customers \
  /mnt/exports/customers-legacy_ng.json --dry-run
```

Read the counts. `attached_to_pre_existing` above zero is expected and correct — those are
staff or organic signups whose email matched a customer; they get a `LegacyIdentity` and
nothing else is touched. `skipped_no_usable_email` above a handful is worth investigating
before proceeding.

Then drop `--dry-run`, one store at a time, checking counts between each.

## 4. Verify

```bash
docker compose ... run --rm web python manage.py shell -c "
from django.db.models import Count
from apps.accounts.models import User, LegacyIdentity
print('customers:', User.objects.exclude(legacy_source='').count())
for row in LegacyIdentity.objects.values('store').annotate(n=Count('id')).order_by('store'):
    print(' ', row['store'], row['n'])
print('cross-store people:', User.objects.annotate(n=Count('legacy_identities')).filter(n__gt=1).count())
print('still on a WordPress hash:', User.objects.filter(password__startswith='wordpress').count())
"
```

Then log in as a real customer with a known password on staging. That is the only check
that matters; every count above can be right while the passwords are wrong.

## 5. DELETE THE ARTIFACTS

```bash
shred -u /mnt/exports/customers-legacy_*.json
```

A file of ~977 password hashes that outlives its purpose is a breach waiting for an
unrelated mistake. Do this even if you expect to re-run — extracting again is cheap.

## 6. After the Plan-27 cutover — DROP the credential

Not "later". The same change window.

```bash
mysql -e "DROP USER 'wp_migration'@'localhost';"
shred -u /root/wp-migration.env
```

The cutover delta run (`import_customers --since <rehearsal date>`) happens **before**
this step. `--since` filters on registration date, so it catches customers who signed up
after the rehearsal; customers who already existed are handled by the importer's
idempotency, which deliberately leaves an imported account alone rather than reverting a
password the customer has since changed.

---

# Runbook — order migration (Plan-23)

Same credential as Plan-22 (`wp_migration`, created in that runbook's §1) — the 23-table
grant already covers the order tables. **Run Plan-22 first**: orders link to customers
through `LegacyIdentity`, and importing orders into an empty customer table turns every
registered order into a guest one.

## 1. Extract — once per store

```bash
cd /opt/tokecosmetics/repo
set -a; . /root/wp-migration.env; set +a
docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod \
  -f infra/docker-compose.prod.yml run --rm \
  -v /var/lib/mysql/mysql.sock:/run/wp-mysql/mysql.sock:ro \
  -e WP_DB_HOST=/run/wp-mysql/mysql.sock \
  -e WP_DB_NAME=tokecosm_wp481 \
  -e WP_TABLE_PREFIX=wp_ \
  -e WP_DB_USER=wp_migration \
  -e WP_DB_PASSWORD \
  web python manage.py extract_wp_orders --store legacy_ng \
      --out /mnt/exports/orders-legacy_ng.json
```

Store/database/prefix table is the same as Plan-22 §2. Expect ~3,093 / 879 / 124 orders.

**`legacy_intl` needs `--include-legacy-posts`.** That store has 13 orders from 2023 that
HPOS never backfilled — they exist only in `wp8n_posts`/`wp8n_postmeta` and `wc_orders`
cannot see them. Without the flag the import succeeds, reports 124 orders, and loses 13.

## 2. Dry run and read the reconciliation

```bash
docker compose ... run --rm web python manage.py import_orders \
  /mnt/exports/orders-legacy_ng.json --dry-run
```

The reconciliation block compares the artifact's own totals against what landed, per
currency. **A `DRIFT` line means money changed shape between WooCommerce and here** — stop
and find out why before doing a real run.

Counts that are expected and correct:

- `skipped_trashed` — WooCommerce's recycle bin. Somebody deleted these on purpose.
- `line_items_without_a_variant` — ~106 on NG. The line is kept with its name and price;
  only the catalogue link is missing.
- `guest_orders` — ~69% of everything. Guests land `user=None` with their email so they
  can claim the order after verifying it.
- `flagged_for_review` — orders where WooCommerce's status and its payment date disagree.
  Each one gets a `review_reason` and shows in the admin's needs-attention queue.

## 3. Import, plus the chase list

```bash
docker compose ... run --rm web python manage.py import_orders \
  /mnt/exports/orders-legacy_ng.json \
  --chase-csv /mnt/exports/chase-legacy_ng.csv
```

**About the 2,277 unpaid bank transfers.** They import as `expired`, not `on_hold` and not
`pending_payment` — decided 2026-08-01. In WooCommerce `wc-on-hold` means *chose bank
transfer, never paid*; in this platform `on_hold` means *money in hand* and counts toward
revenue. Mapping the word to the word would have put ₦34.2M of never-collected money on
the dashboard. `--chase-csv` writes the last 30 days' worth — the ones that might still
pay — as a short list somebody can actually work.

## 4. Verify

```bash
docker compose ... run --rm web python manage.py shell -c "
from django.db.models import Count, Sum
from apps.orders.models import Order
for r in Order.objects.exclude(source='web').values('source','status').annotate(n=Count('id')).order_by('source','status'):
    print(r)
print('revenue-status orders with no review flag:',
      Order.objects.filter(status__in=['completed','processing','on_hold','refunded'], review_reason='').count())
print('needing attention:', Order.objects.exclude(review_reason='').count())
"
```

Then open the admin dashboard and check the revenue figure against what you know the
business actually took. That is the number this whole stage was measured to protect.

## 5. Delete the artifacts

```bash
shred -u /mnt/exports/orders-legacy_*.json /mnt/exports/chase-*.csv
```

The chase CSV especially: it is a list of customers who owe you money, with their names,
emails and phone numbers.
