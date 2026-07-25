#!/usr/bin/env bash
# Restore a dump into a SCRATCH database. Never touches the live one.
#
# Usage: restore.sh /opt/tokecosmetics/backups/toke-YYYYmmdd-HHMMSS.sql.gz [scratch_db]
#
# This only ever proves a dump is restorable. Promoting a restored database to live
# is a separate, deliberate procedure — see docs/runbooks/restore.md.
set -euo pipefail

COMPOSE=(docker compose -p tokecosmetics
         --env-file /opt/tokecosmetics/.env.prod
         -f /opt/tokecosmetics/repo/infra/docker-compose.prod.yml)

DUMP=${1:?usage: restore.sh <dump.sql.gz> [scratch_db]}
SCRATCH=${2:-toke_restore_test}

log() { echo "[$(date -Is)] $*"; }
fail() { log "FATAL: $*"; exit 1; }

[ -f "$DUMP" ] || fail "no such dump: $DUMP"

PGUSER=$("${COMPOSE[@]}" exec -T postgres printenv POSTGRES_USER | tr -d '\r\n')
PGDB=$("${COMPOSE[@]}" exec -T postgres printenv POSTGRES_DB | tr -d '\r\n')

# The guard that matters. Everything else in this script is convenience.
[ "$SCRATCH" != "$PGDB" ] || fail "refusing to restore over the live database ($PGDB)"

log "restoring $DUMP into scratch database '$SCRATCH' (live database '$PGDB' untouched)"

"${COMPOSE[@]}" exec -T postgres psql -U "$PGUSER" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"$SCRATCH\";" \
    -c "CREATE DATABASE \"$SCRATCH\" OWNER \"$PGUSER\";"

# ON_ERROR_STOP is what turns "restored with 400 errors" into a failed restore.
gunzip -c "$DUMP" | "${COMPOSE[@]}" exec -T postgres \
    psql -U "$PGUSER" -d "$SCRATCH" -v ON_ERROR_STOP=1 --quiet > /dev/null

log "restore completed without errors — now checking it actually contains data"

"${COMPOSE[@]}" exec -T postgres psql -U "$PGUSER" -d "$SCRATCH" -At -c "
SELECT 'tables', count(*) FROM information_schema.tables WHERE table_schema='public'
UNION ALL SELECT 'django_migrations', count(*) FROM django_migrations
UNION ALL SELECT 'users', count(*) FROM accounts_user
UNION ALL SELECT 'orders', count(*) FROM orders_order
UNION ALL SELECT 'products', count(*) FROM catalog_product
UNION ALL SELECT 'regions', count(*) FROM core_region;"

log "scratch database '$SCRATCH' left in place for inspection. Drop it with:"
log "  docker compose -p tokecosmetics -f /opt/tokecosmetics/repo/infra/docker-compose.prod.yml exec -T postgres psql -U $PGUSER -d postgres -c 'DROP DATABASE \"$SCRATCH\";'"
