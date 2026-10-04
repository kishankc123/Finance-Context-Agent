#!/usr/bin/env bash
# Start the local dev stack: Qdrant, the embedding service, and the Inference
# Gateway. Run this once before `python ingest.py ...` or the Agent API.
#
# Logs and PID files are written to .run/ (gitignored). Stop everything with
# scripts/dev_down.sh.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$REPO_ROOT/.run"
mkdir -p "$RUN_DIR"

wait_for_http() {
    local name="$1" url="$2" tries=30
    for ((i = 1; i <= tries; i++)); do
        if curl -s -o /dev/null --max-time 2 "$url"; then
            echo "  $name is up ($url)"
            return 0
        fi
        sleep 1
    done
    echo "  WARNING: $name did not respond at $url after ${tries}s" >&2
    return 1
}

start_service() {
    local name="$1" dir="$2" venv="$3" port="$4"
    local pid_file="$RUN_DIR/$name.pid"
    local log_file="$RUN_DIR/$name.log"

    if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
        echo "==> $name already running (pid $(cat "$pid_file"))"
        return 0
    fi

    echo "==> Starting $name on port $port"
    (
        cd "$REPO_ROOT/$dir"
        source "$REPO_ROOT/$venv/bin/activate"
        nohup uvicorn main:app --host 0.0.0.0 --port "$port" >"$log_file" 2>&1 &
        echo $! >"$pid_file"
    )
}

echo "==> Starting Qdrant (docker compose)"
docker compose -f "$REPO_ROOT/infra/docker-compose.yml" up -d qdrant
wait_for_http "Qdrant" "http://localhost:6333/healthz"

start_service "embedding-service" "services/embedding-service" ".venv-embeddings" 8002
wait_for_http "embedding-service" "http://localhost:8002/docs"

start_service "inference-gateway" "services/inference-gateway" ".venv-gateway" 8080
wait_for_http "inference-gateway" "http://localhost:8080/docs"

cat <<EOF

All services are up. Logs: $RUN_DIR/<service>.log

Now run ingestion, e.g.:
  cd services/ingestion-worker
  source ../../.venv-ingestion/bin/activate
  python ingest.py --tickers AMZN,META,GOOGL,TSLA --filing-types 10-K,10-Q --years 4

Stop everything with:
  scripts/dev_down.sh
EOF
