#!/usr/bin/env bash
# Deploy a tag to the VPS. Runs ON the VPS.  Usage: deploy.sh backend-v1.2.3
set -euo pipefail

TAG=${1:?usage: deploy.sh <tag>}
REPO=/opt/tokecosmetics/repo
COMPOSE=(docker compose -p tokecosmetics
         --env-file /opt/tokecosmetics/.env.prod
         -f "$REPO/infra/docker-compose.prod.yml")

log() { echo "[$(date -Is)] $*"; }

cd "$REPO"

# Refuse to deploy over uncommitted changes. Someone editing files directly on the
# server is either debugging or has been compromised; either way, silently throwing
# their work away mid-deploy is the wrong response.
if [ -n "$(git status --porcelain)" ]; then
    log "FATAL: working tree at $REPO is dirty — refusing to deploy over it:"
    git status --short
    exit 1
fi

PREV=$(git rev-parse --abbrev-ref HEAD)
[ "$PREV" = "HEAD" ] && PREV=$(git describe --tags --exact-match 2>/dev/null || git rev-parse --short HEAD)
log "current ref: $PREV — deploying $TAG"

git fetch --tags --prune --quiet
git checkout --quiet "$TAG"

# Take a dump before migrating. Migrations are the one step in a deploy that can
# destroy data, and this is the last moment it is cheap to capture. A failing
# backup aborts the deploy on purpose — deploying with no way back is the thing
# this is here to prevent. DEPLOY_SKIP_BACKUP=1 for the rare deliberate exception.
if [ "${DEPLOY_SKIP_BACKUP:-0}" != "1" ]; then
    log "pre-deploy backup"
    "$REPO/infra/deploy/backup.sh"
else
    log "WARNING: pre-deploy backup skipped by DEPLOY_SKIP_BACKUP=1"
fi

# Compose's recreate renames the old container to "<hex>_tokecosmetics-web-1" and
# sometimes fails to remove it (hit on v0.6.1, v0.6.2 AND v0.7.0: "container name
# already in use", leaving web DOWN with the deploy half-done). Clear any such
# leftover from a previous run before recreating. The pattern is anchored to the
# 12-hex-digit rename prefix, so live containers (tokecosmetics-web-1) can't match.
docker ps -a --format '{{.Names}}' \
    | grep -E '^[0-9a-f]{12}_tokecosmetics-[a-z]+-[0-9]+$' \
    | xargs -r -n1 docker rm -f \
    || true

log "build and start"
# The rename collision can also form DURING this recreate (seen on v0.7.1: compose's
# own temp-rename hit a name that materialised mid-flight), which the pre-clean above
# cannot prevent. One clear-and-retry covers it; a second failure is a real problem
# that should stop the deploy.
if ! "${COMPOSE[@]}" up -d --build; then
    log "compose up failed — clearing renamed leftovers and retrying once"
    docker ps -a --format '{{.Names}}' \
        | grep -E '^[0-9a-f]{12}_tokecosmetics-[a-z]+-[0-9]+$' \
        | xargs -r -n1 docker rm -f \
        || true
    "${COMPOSE[@]}" up -d --build
fi

log "migrate"
# Migrations run as the schema OWNER, not the runtime role: DDL needs ownership, and
# the whole point of toke_app (create-app-role.sql, Plan-25 task 5) is that the running
# app cannot alter tables or triggers. MIGRATE_DATABASE_URL is set in .env.prod once
# the role split is applied; before that it is unset and this falls back unchanged.
"${COMPOSE[@]}" exec -T web sh -c 'DATABASE_URL="${MIGRATE_DATABASE_URL:-$DATABASE_URL}" python manage.py migrate --noinput'

log "collectstatic"
"${COMPOSE[@]}" exec -T web python manage.py collectstatic --noinput

# Both headers are required, and a bare `curl http://127.0.0.1:8001/healthz/` does
# NOT work — verified 2026-07-25, it returns 400.
#   Host:              ALLOWED_HOSTS is api.tokecosmetics.com, so a request arriving
#                      as 127.0.0.1 is rejected as DisallowedHost.
#   X-Forwarded-Proto: SECURE_SSL_REDIRECT is on, so plain HTTP answers 301.
# Without these this loop would time out on every single deploy, including the
# successful ones, and the pipeline would cry wolf until nobody read it.
log "waiting for healthz"
for _ in $(seq 1 30); do
    if curl -fsS -H 'Host: api.tokecosmetics.com' -H 'X-Forwarded-Proto: https' \
            http://127.0.0.1:8001/healthz/ > /dev/null; then
        log "deployed $TAG — healthz ok"
        exit 0
    fi
    sleep 2
done

# Deliberately not auto-rolling-back. An automatic rollback that itself fails at
# 3am leaves the box in a third state nobody has thought about, and the failure
# here might be a bad migration that a re-checkout would not undo anyway. Fail
# loudly, hand over the exact command, let a human decide.
log "FATAL: healthz did not come up after 60s. The API is DOWN."
log "  logs:     ${COMPOSE[*]} logs --tail=100 web"
log "  rollback: $REPO/infra/deploy/deploy.sh $PREV"
exit 1
