#!/bin/bash
set -e

# Models to auto-load on startup (space-separated, override via env)
: "${AUTO_LOAD_MODELS:=}"

# Server configuration (override via env)
: "${LEMONADE_HOST:=0.0.0.0}"
: "${LEMONADE_PORT:=13305}"
: "${HEALTH_CHECK_TIMEOUT:=60}"

echo "[entrypoint] Starting Lemonade server on ${LEMONADE_HOST}:${LEMONADE_PORT}"

# Start the Lemonade server in the background
./lemonade-server serve --no-tray --host "${LEMONADE_HOST}" &
SERVER_PID=$!

echo "[entrypoint] Lemonade server started (PID: $SERVER_PID)"

# Wait for server to be ready
echo "[entrypoint] Waiting for server to be ready..."
for i in $(seq 1 "${HEALTH_CHECK_TIMEOUT}"); do
    if curl -sf "http://localhost:${LEMONADE_PORT}/health" > /dev/null 2>&1; then
        echo "[entrypoint] Server is ready after ${i}s"
        break
    fi
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo "[entrypoint] Server process exited unexpectedly"
        exit 1
    fi
    sleep 1
done

# Auto-load models if configured
if [ -n "${AUTO_LOAD_MODELS}" ]; then
    echo "[entrypoint] Auto-loading models..."
    for model in ${AUTO_LOAD_MODELS}; do
        echo "[entrypoint] Loading: ${model}"
        curl -sf -X POST "http://localhost:${LEMONADE_PORT}/api/v1/load" \
            -H "Content-Type: application/json" \
            -d "{\"model_name\": \"${model}\"}" \
            || echo "[entrypoint] Warning: Failed to load ${model} (may already be loaded)"
    done
    echo "[entrypoint] All models loaded. Server is ready."
else
    echo "[entrypoint] No models configured for auto-load (set AUTO_LOAD_MODELS env var)"
    echo "[entrypoint] Server is ready."
fi

# Wait for the server process
wait $SERVER_PID
