# Runbook — taking a VPS snapshot before the cutover

**Why this exists:** the cutover edits `wp-config.php` and an Apache vhost on a live,
revenue-generating server. A snapshot is the only rollback that covers "the box is wrong
and I do not know which change did it". Everything else in the cutover runbook rolls back
one change at a time.

**What I can and cannot do:** I have root on the server, so I can do everything in §2 and
§3. I **cannot** reach the Namecheap billing panel — §1 is yours, and it is the part that
actually produces the snapshot. I have deliberately not written click-by-click menu paths
for it, because Namecheap has changed that interface more than once and a confidently
wrong instruction is worse than none. What is below is what to look for.

---

## 1. The Namecheap snapshot — you, in the panel

The server is a Namecheap VPS on the **Quasar** plan, IP `203.161.38.201`, managed with
Webuzo.

1. Sign in at namecheap.com → **Dashboard** → find the VPS under your product list (it may
   be under *Hosting List*, *VPS*, or *Servers* depending on the current layout).
2. Open the server's management page. Namecheap fronts VPS management with a control
   panel — historically SolusVM, more recently their own interface. Look for a section
   named **Snapshots**, **Backups**, or **Rebuild/Restore**.
3. Take a **snapshot**, not a file backup. A snapshot captures the whole disk including
   MariaDB's on-disk state; a file backup of `/var/lib/mysql` taken while MariaDB is
   running can be inconsistent.
4. Label it something you will recognise in a hurry: `pre-cutover-2026-08-17`.
5. **Write down where the restore button is** before you need it. Finding it for the first
   time during an incident costs the minutes you were trying to save.

### Things worth knowing before you click

- **Most VPS plans keep only one or two snapshot slots.** Taking a new one may silently
  overwrite the previous. If an older snapshot matters, check before overwriting.
- **Ask how long it takes and whether the server pauses.** Some providers snapshot live,
  some suspend the VM for the duration. If it suspends, that is downtime on a live store —
  take it in a quiet window, and treat the snapshot itself as a change with a blast radius.
- **A snapshot restore is whole-disk.** Restoring to undo a `wp-config.php` edit also
  discards every order the new platform took after the snapshot. That is why the cutover
  runbook prefers reversible per-change rollbacks and keeps the snapshot as the last
  resort.
- If you cannot find a snapshot feature at all, the plan may not include one. Say so and
  we will lean harder on §2 and §3, which are already done and which cover the databases —
  the part that cannot be rebuilt from git.

---

## 2. What is already backed up (done 2026-08-17)

In `/root/pre-cutover-backups/`:

| File | Size | What it is |
| ---- | ---- | ---------- |
| `wp-20260817-1816.sql.gz` | 132 M | Full `tokecosm_wp481` dump — WordPress, WooCommerce, 4,318 orders, 1,676 users, and the loyalty-point balances |
| `pg-20260817-1816.sql.gz` | 547 K | Full platform Postgres dump, taken **before** the customer and order import |

To repeat either at any time:

```bash
cd /root/pre-cutover-backups
mysqldump --single-transaction --quick tokecosm_wp481 | gzip > wp-$(date +%Y%m%d-%H%M).sql.gz
docker exec tokecosmetics-postgres-1 sh -lc \
  'pg_dump -U $POSTGRES_USER $POSTGRES_DB' | gzip > pg-$(date +%Y%m%d-%H%M).sql.gz
```

`--single-transaction` is what makes the MariaDB dump consistent without locking the live
store. Do not drop it.

### Get them off the box

A backup that only exists on the machine it protects is not a backup. Copy both to S3
(the bucket already has a `Toke_LifeCycle` rule covering `backups/postgres/`):

```bash
aws s3 cp wp-20260817-1816.sql.gz  s3://<bucket>/backups/pre-cutover/ --profile toke
aws s3 cp pg-20260817-1816.sql.gz  s3://<bucket>/backups/pre-cutover/ --profile toke
```

**Careful with bucket lifecycle:** any lifecycle PUT replaces the whole configuration. If
you ever change it, include the existing `Toke_LifeCycle` rule or it is silently deleted.

---

## 3. Restoring, if it comes to that

**WordPress database:**

```bash
gunzip -c /root/pre-cutover-backups/wp-20260817-1816.sql.gz | mysql tokecosm_wp481
```

**Platform database** — stop the app first so nothing writes mid-restore:

```bash
cd /opt/tokecosmetics/repo
docker compose -p tokecosmetics -f infra/docker-compose.prod.yml stop web worker beat
gunzip -c /root/pre-cutover-backups/pg-20260817-1816.sql.gz | \
  docker exec -i tokecosmetics-postgres-1 sh -lc 'psql -U $POSTGRES_USER -d $POSTGRES_DB'
docker compose -p tokecosmetics -f infra/docker-compose.prod.yml start web worker beat
```

**Restoring the Postgres dump now would delete the 1,007 customers and 4,321 orders
imported today**, along with anything else since 18:16. There is a fuller treatment in
`docs/runbooks/restore.md`.

---

## 4. Checklist

- [ ] Snapshot taken in the Namecheap panel, labelled `pre-cutover-2026-08-17`
- [ ] You know where the restore button is
- [ ] You know whether restoring pauses the server
- [ ] Both `.sql.gz` files copied off the box to S3
- [ ] Only then: start the cutover runbook
