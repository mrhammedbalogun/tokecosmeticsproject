#!/usr/bin/env bash
# Forced command for the GitHub Actions deploy key. NOT run directly by humans.
#
# INSTALLED AT /opt/tokecosmetics/ci-deploy.sh — deliberately OUTSIDE the git
# checkout. deploy.sh does `git checkout <tag>`, so anything inside /opt/tokecosmetics/repo
# is whatever that tag says it is. A forced command that could be swapped by the
# thing it is restricting would restrict nothing. This copy is the source of truth;
# after editing it, reinstall:
#
#   cp /opt/tokecosmetics/repo/infra/deploy/ci-deploy.sh /opt/tokecosmetics/ci-deploy.sh
#   chmod 700 /opt/tokecosmetics/ci-deploy.sh
#
# root's authorized_keys pins this key to this command:
#   restrict,command="/opt/tokecosmetics/ci-deploy.sh" ssh-ed25519 AAAA... github-actions-deploy
#
# So a leaked VPS_SSH_KEY secret buys an attacker the ability to redeploy an
# existing, already-published tag — not a root shell on the live store. `restrict`
# additionally denies pty, port forwarding, agent forwarding and X11.
set -euo pipefail

CMD=${SSH_ORIGINAL_COMMAND:-}

# A tag and nothing else. No spaces, no semicolons, no path traversal — this string
# reaches `git checkout`, and the whole point of the forced command is that what
# arrives here is untrusted.
if ! printf '%s' "$CMD" | grep -qE '^backend-v[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "refused: expected a tag matching backend-vN.N.N, got: '${CMD}'" >&2
    exit 1
fi

exec /opt/tokecosmetics/repo/infra/deploy/deploy.sh "$CMD"
