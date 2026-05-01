#!/bin/bash
set -e

# Models to auto-load on startup (space-separated)
AUTO_LOAD_MODELS="Qwen3.6-35B-A3B-GGUF Qwen3.6-27B-GGUF Qwen3.5-2B-GGUF Gemma-4-26B-A4B-it-GGUF"

# Start the Lemonade server in the background
./lemonade-server serve --no-tray --host 0.0.0.0 &
SERVER_PID=$!

echo "[entrypoint] Lemonade server started (PID: $SERVER_PID)"

# Wait for server to be ready
echo "[entrypoint] Waiting for server to be ready..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:13305/health > /dev/null 2>&1; then
        echo "[entrypoint] Server is ready after ${i}s"
        break
    fi
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo "[entrypoint] Server process exited unexpectedly"
        exit 1
    fi
    sleep 1
done

# Auto-load models
echo "[entrypoint] Auto-loading models..."
for model in $AUTO_LOAD_MODELS; do
    echo "[entrypoint] Loading: $model"
    curl -sf -X POST http://localhost:13305/api/v1/load \
        -H "Content-Type: application/json" \
        -d "{\"model_name\": \"$model\"}" \
        || echo "[entrypoint] Warning: Failed to load $model (may already be loaded)"
done

echo "[entrypoint] All models loaded. Server is ready."

# Wait for the server process
wait $SERVER_PID
