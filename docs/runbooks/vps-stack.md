# Runbook — the API stack on the VPS

Written for whoever is holding the pager, assuming no Django knowledge. Everything
here runs on the Namecheap VPS (`ssh tokecosmetics`, root). The live WordPress store
runs on the **same machine** — that is the reason for most of the caution below.

**Where things live**

| Thing | Path |
|---|---|
| Git clone the stack runs from | `/opt/tokecosmetics/repo` |
| Compose file | `/opt/tokecosmetics/repo/infra/docker-compose.prod.yml` |
| Secrets (`.env.prod`) | `/opt/tokecosmetics/.env.prod` — root-owned, `chmod 600`, **never in git** |
| Postgres data | `/opt/tokecosmetics/data/pg` |
| Uploaded media / static files | `/opt/tokecosmetics/data/{media,static}` |
| Apache vhost for the API | `/usr/local/apps/apache2/etc/conf.d/zz-api.conf` |
| Apache logs for the API | `/usr/local/apps/apache2/logs/api.tokecosmetics.com.{log,err}` |

Every command below assumes:

```bash
cd /opt/tokecosmetics/repo/infra
```

Compose is invoked as `docker compose -p tokecosmetics -f docker-compose.prod.yml`.
The `-p tokecosmetics` matters — run it from another directory without the project
name and Docker will think it is a different, empty stack.

**`infra/.env` is a symlink to `/opt/tokecosmetics/.env.prod`, and it is load-bearing.**
Docker Compose uses two different mechanisms in this file: `env_file:` (an absolute
path, used by `web`/`worker`/`beat`) and `${VAR}` interpolation (used by the
`postgres` service). Interpolation does *not* read `env_file:` — it reads the shell
and an `.env` sitting next to the compose file. Without that symlink, a plain
`docker compose up -d` recreates Postgres with a blank `POSTGRES_USER`, its
healthcheck (`pg_isready -U ""`) fails, and because `web` and `worker` wait on
`condition: service_healthy` **the whole stack refuses to start.** Existing data is
not harmed — the data directory is already initialised, so the blank credentials
are ignored by Postgres itself — but the deploy dies.

The symlink is untracked and `.env*` is gitignored, so `git checkout` during a
deploy or rollback will not remove it. If it ever goes missing, recreate it:

```bash
ln -s /opt/tokecosmetics/.env.prod /opt/tokecosmetics/repo/infra/.env
```

Belt and braces: pass `--env-file /opt/tokecosmetics/.env.prod` explicitly in
scripts and CI, which works from any directory. Whenever you run a compose command,
**a `variable is not set` warning means stop** — do not proceed to `up -d`.

---

## The five containers, in plain language

| Container | What it actually does | If it dies |
|---|---|---|
| `postgres` | The database. Every order, customer, product and payment record. | Everything stops. This is the only container holding data that cannot be rebuilt. |
| `redis` | Scratch memory: the job queue and a cache. Deliberately keeps nothing on disk (`--save ""`). | Background jobs stall; the site still serves pages. Safe to restart. |
| `web` | The API itself — gunicorn running Django, 3 workers. This is what `api.tokecosmetics.com` reaches. | The API returns 502 through Cloudflare. The WordPress store is unaffected. |
| `worker` | Runs background jobs the API hands off: sending email, generating invoices, stock updates. | Pages still load, but emails stop going out and jobs pile up in Redis until it is back. |
| `beat` | The clock. Nothing more — it just tells `worker` when scheduled jobs are due. | No error anywhere; scheduled jobs simply stop happening. **This is the failure you will not notice.** See "Watch beat" below. |

`beat`'s schedule (from `backend/config/settings/base.py`): expire unpaid pending
orders every 5 min, abandon stale carts every 30 min, low-stock digest hourly,
complete delivered orders and anonymise deleted accounts daily.

**There is no Meilisearch container, on purpose.** `apps/search/backends.py::get_backend()`
returns `PostgresSearchBackend()` unconditionally, so search runs on Postgres
`pg_trgm`. Meilisearch is parked for a "Plan-07b" that does not exist yet. If you
are reading the master guide and wondering where the sixth container went — that
is why. It saves 512 MB.

---

## Everyday commands

```bash
docker compose -p tokecosmetics -f docker-compose.prod.yml ps
```

Health check status is in the `STATUS` column. `(healthy)` means the container is
answering, not merely running.

```bash
docker compose -p tokecosmetics -f docker-compose.prod.yml logs -f --tail=100 web
```

Swap `web` for `worker`, `beat`, `postgres`, `redis`. Logs are capped at 10 MB × 3
files per container, so they cannot fill the disk.

Restart one service (safe, ~10 seconds of 502s for `web`):

```bash
docker compose -p tokecosmetics -f docker-compose.prod.yml restart web
```

Is the API alive, from the outside?

```bash
curl -s https://api.tokecosmetics.com/healthz/
```

Expected: `{"status":"ok","db":true,"redis":true}`.

---

## Rolling back

The stack runs from a git checkout, so rolling back is a checkout plus a rebuild:

```bash
cd /opt/tokecosmetics/repo
git fetch --tags
git checkout <previous-tag>
cd infra
docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod \
    -f docker-compose.prod.yml up -d --build
```

**Database migrations do not roll back with the code.** If the version you are
leaving added or changed database tables, going back to older code may break
against the newer database. Read the release notes for what you are rolling back
*over*; if in doubt, restore from a backup (`docs/runbooks/restore.md`) rather than
guessing.

---

## Two things that will bite you

### 1. `zz-api.conf` — the filename is load-bearing

`httpd.conf` line 521 does `Include etc/conf.d/*.conf`, which globs
**alphabetically**, and Apache treats the *first* `<VirtualHost>` for an address as
that address's **default** — the vhost that serves every request whose `Host`
matches nothing else. A file named `api.conf` would sort before `webuzo.conf` and
`webuzoVH.conf`, silently become the default for `203.161.38.201:443`, and start
serving Django to WordPress shoppers.

So: **never rename it to anything that sorts before `w`.** After any edit, before
reloading Apache:

```bash
/usr/local/apps/apache2/bin/httpd -t
/usr/local/apps/apache2/bin/httpd -S | grep -A2 '203.161.38.201:443'
```

The `default server` line must still name a Webuzo vhost, not `api.tokecosmetics.com`.

Webuzo regenerates `webuzoVH.conf` on every panel save and its header says DO NOT
EDIT, which is exactly why the API vhost lives in its own file. **After any Webuzo
settings change, check `zz-api.conf` is still there** and re-run the two commands
above.

### 2. If the API starts returning 403 for no apparent reason

`zz-api.conf` only admits Cloudflare's published IP ranges (plus `127.0.0.1` and
the box's own `203.161.38.201`). Cloudflare changes those ranges rarely, but it
does change them. Before debugging anything else:

```bash
curl -s https://www.cloudflare.com/ips-v4
curl -s https://www.cloudflare.com/ips-v6
```

and diff them against the `<Location />` block. That is the most likely cause.

The lock exists because the origin IP is public knowledge — the WordPress stores
share it — so without it anyone could reach the API directly with
`curl --resolve api.tokecosmetics.com:443:203.161.38.201` and skip Cloudflare's
WAF and rate limiting entirely. That was verified exploitable on 2026-07-25 before
the block went in.

`/django-admin/` is deliberately `Require all denied`. It is not broken.

---

## Resource guardrail

The live store shares this RAM. If the box starts swapping, the store gets slow and
that costs real money. Measure with:

```bash
docker stats --no-stream
free -h
df -h /
```

Baseline, 2026-07-25, ~11 h uptime, idle traffic:

| Container | Memory | Limit | % |
|---|---|---|---|
| `web` | 272 MB | 768 MB | 35% |
| `worker` | 183 MB | 512 MB | 36% |
| `beat` | 98 MB | 128 MB | **77%** |
| `postgres` | 34 MB | 1 GB | 3% |
| `redis` | 9 MB | 256 MB | 3% |
| **Total** | **596 MB** | 2.66 GB | |

Host: 5.8 GB total, 3.3 GB available, 4 GB swap with 13 MB used. Disk 44% used,
63 GB free. Zero restarts, zero OOM kills on any container.

**596 MB against a ~2.6 GB budget and a 3 GB ceiling.** Nothing to do. Note this is
an *empty catalogue* — Postgres will grow once Plan-21 loads the real products, but
it has a 1 GB limit and 34 MB of headroom used, so there is a lot of room.

**Watch `beat`.** 98 MB of a 128 MB limit is the tightest number in the stack. It
has been flat all day, so it is not a leak, but if it ever crosses the limit Docker
kills the container — and because `restart: unless-stopped` brings it straight back,
you get no alarm, just a gap in scheduled jobs. If you see `beat` restarting,
raise `mem_limit` to `256m` in `docker-compose.prod.yml`; there is spare RAM for it.

If total container memory ever approaches 2.6 GB, or `free -h` shows `available`
under 1 GB, reduce before anything else: gunicorn to 2 workers (`backend/Dockerfile`
CMD) and Celery to `-c 1` (`worker` command in the compose file).

### Nothing new is publicly exposed

```bash
ss -tlnp | grep -E ':(5433|6380|8001) '
```

All three must begin `127.0.0.1:`. A `0.0.0.0:` here means Postgres or Redis is on
the public internet — fix the port binding in the compose file immediately and
restart that service. This is not cosmetic: **Docker writes its own iptables rules
that bypass the host firewall**, so a bare `"5433:5432"` is publicly reachable even
with `ufw` enabled (and `ufw` is currently inactive on this box — Plan-25).

Verified 2026-07-25: all three loopback-bound, and the only public listeners are
the pre-existing WordPress/mail/Webuzo/FTP/DNS ones.
