#!/usr/bin/env bash
set -e

# If AlloyDB parameters are specified, start the AlloyDB Auth Proxy
if [ -n "${ALLOYDB_CLUSTER:-}" ] || [ -n "${CLUSTER:-}" ]; then
  PROJECT_ID="${PROJECT_ID:-returniq-511821}"
  REGION="${REGION:-asia-south1}"
  CLUSTER="${ALLOYDB_CLUSTER:-${CLUSTER:-free-return-iq-cluster}}"
  INSTANCE="${ALLOYDB_INSTANCE:-${INSTANCE:-primary}}"
  PROXY_PORT="${DB_PORT:-5433}"
  INSTANCE_URI="projects/$PROJECT_ID/locations/$REGION/clusters/$CLUSTER/instances/$INSTANCE"

  echo "==> Starting AlloyDB Auth Proxy for $INSTANCE_URI on port $PROXY_PORT"
  /usr/local/bin/alloydb-auth-proxy "$INSTANCE_URI" --public-ip --address 127.0.0.1 --port "$PROXY_PORT" &
  PROXY_PID=$!

  echo "==> Waiting for AlloyDB Auth Proxy to accept connections on 127.0.0.1:$PROXY_PORT..."
  READY=0
  for i in $(seq 1 45); do
    if nc -z 127.0.0.1 "$PROXY_PORT" 2>/dev/null; then
      READY=1
      echo "==> AlloyDB Auth Proxy is ready."
      break
    fi
    if ! kill -0 "$PROXY_PID" 2>/dev/null; then
      echo "==> ERROR: AlloyDB Auth Proxy process exited prematurely!"
      wait "$PROXY_PID" || true
      break
    fi
    sleep 1
  done

  if [ "$READY" -ne 1 ]; then
    echo "==> WARNING: Proxy did not open port in time, continuing anyway..."
  fi
fi

PORT="${PORT:-8080}"
echo "==> Starting ReturnIQ FastAPI server on port $PORT"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
