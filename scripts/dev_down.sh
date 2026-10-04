#!/usr/bin/env bash
# Stop services started by scripts/dev_up.sh. Qdrant is left running (it's a
# docker container, not a local process) — stop it separately with:
#   docker compose -f infra/docker-compose.yml stop qdrant
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$REPO_ROOT/.run"

for name in embedding-service inference-gateway; do
    pid_file="$RUN_DIR/$name.pid"
    if [[ -f "$pid_file" ]]; then
        pid="$(cat "$pid_file")"
        if kill -0 "$pid" 2>/dev/null; then
            echo "==> Stopping $name (pid $pid)"
            kill "$pid"
        else
            echo "==> $name not running (stale pid file)"
        fi
        rm -f "$pid_file"
    else
        echo "==> $name not running (no pid file)"
    fi
done
