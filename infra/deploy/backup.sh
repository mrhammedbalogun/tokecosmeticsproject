#!/usr/bin/env bash
# Nightly Postgres dump -> local (14 days) -> S3. Run by cron as root.
#
# Deployed to /opt/tokecosmetics/repo/infra/deploy/backup.sh.
# Log:  /var/log/toke-backup.log
#
# Why the dump and the upload both go through containers:
#   - pg_dump must match the server version (16). The host has no postgres client.
#   - The host has no `aws` CLI, and installing one on a live production box for a
#     five-line upload is not worth the change. The `web` image already ships boto3
#     (django-storages needs it) and already has the AWS credentials via env_file,
#     so the dump is streamed into it over stdin and uploaded from there. No
#     credentials are ever read by, or visible to, this script.
set -euo pipefail

COMPOSE=(docker compose -p tokecosmetics
         --env-file /opt/tokecosmetics/.env.prod
         -f /opt/tokecosmetics/repo/infra/docker-compose.prod.yml)

BACKUP_DIR=/opt/tokecosmetics/backups
RETENTION_DAYS=14
STAMP=$(date +%Y%m%d-%H%M%S)
FILE="$BACKUP_DIR/toke-$STAMP.sql.gz"
KEY="backups/postgres/toke-$STAMP.sql.gz"

log() { echo "[$(date -Is)] $*"; }
fail() { log "FATAL: $*"; exit 1; }

mkdir -p "$BACKUP_DIR"

# Read the credentials from the running container rather than parsing .env.prod.
# Sourcing that file would execute it, and it holds a Django SECRET_KEY and API
# keys full of characters the shell would happily interpret.
PGUSER=$("${COMPOSE[@]}" exec -T postgres printenv POSTGRES_USER | tr -d '\r\n')
PGDB=$("${COMPOSE[@]}" exec -T postgres printenv POSTGRES_DB | tr -d '\r\n')
[ -n "$PGUSER" ] && [ -n "$PGDB" ] || fail "could not read POSTGRES_USER/POSTGRES_DB from the container"

log "dumping $PGDB as $PGUSER -> $FILE"
"${COMPOSE[@]}" exec -T postgres pg_dump -U "$PGUSER" -d "$PGDB" | gzip -9 > "$FILE"

# A dump that gzips to almost nothing is a failed dump, not a small database. The
# classic backup failure is a script that writes an empty file every night for six
# months and rotates the good copies away behind it.
SIZE=$(stat -c%s "$FILE")
[ "$SIZE" -ge 10000 ] || fail "dump is only ${SIZE} bytes — refusing to upload or rotate"

# pipefail catches a pg_dump that dies mid-stream, but not a corrupt gzip.
gzip -t "$FILE" || fail "dump failed its gzip integrity check"
log "dump ok: $SIZE bytes"

# Stream the file into the web container and upload from there. Compare the size
# S3 reports back against what we sent: a truncated upload is a silent disaster.
REMOTE_SIZE=$("${COMPOSE[@]}" exec -T -e S3_KEY="$KEY" web python -c '
import os, sys, boto3
bucket = os.environ["AWS_STORAGE_BUCKET_NAME"]
key = os.environ["S3_KEY"]
s3 = boto3.client("s3", region_name=os.environ.get("AWS_S3_REGION_NAME"))
s3.upload_fileobj(sys.stdin.buffer, bucket, key)
print(s3.head_object(Bucket=bucket, Key=key)["ContentLength"])
' < "$FILE" | tr -d '\r\n')

[ "$REMOTE_SIZE" = "$SIZE" ] || fail "S3 says ${REMOTE_SIZE} bytes, we sent ${SIZE} — upload is not intact"
log "uploaded s3://.../$KEY ($REMOTE_SIZE bytes)"

# Rotate local copies only after a verified upload, so a broken S3 never costs us
# the local history too.
DELETED=$(find "$BACKUP_DIR" -name 'toke-*.sql.gz' -mtime +"$RETENTION_DAYS" -print -delete | wc -l)
log "rotated $DELETED local dump(s) older than $RETENTION_DAYS days; $(find "$BACKUP_DIR" -name 'toke-*.sql.gz' | wc -l) kept"
log "backup ok: $FILE"
