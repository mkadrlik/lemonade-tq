#!/bin/bash
set -e

# Create symlink for libopenblas.so.0 -> libopenblaso.so.0
# (Vulkan binary expects libopenblas.so.0 but host provides libopenblaso.so.0)
if [ -f /lib64/libopenblaso.so.0 ] && [ ! -f /tmp/libopenblas.so.0 ]; then
    ln -s /lib64/libopenblaso.so.0 /tmp/libopenblas.so.0
    export LD_LIBRARY_PATH="/tmp:/opt/rocm/lib:${LD_LIBRARY_PATH:-}"
    echo "[entrypoint] Created symlink /tmp/libopenblas.so.0 -> /lib64/libopenblaso.so.0"
fi

# Models to auto-load on startup (space-separated, override via env)
: "${AUTO_LOAD_MODELS:=}"

# Server configuration (override via env)
: "${LEMONADE_HOST:=0.0.0.0}"
: "${LEMONADE_PORT:=13305}"
: "${HEALTH_CHECK_TIMEOUT:=60}"

# TurboQuant registry config
: "${TQ_REGISTRY:=ghcr.io}"
: "${TQ_USER:=mkadrlik}"
: "${TQ_TAG:=latest}"
: "${GHCR_TOKEN:=}"

echo "[entrypoint] Starting Lemonade server on ${LEMONADE_HOST}:${LEMONADE_PORT}"

# Detect required backends from recipe_options.json
if [ -f /root/.cache/lemonade/recipe_options.json ]; then
    REQUIRED_BACKENDS=$(cat /root/.cache/lemonade/recipe_options.json | jq -r '.[].llamacpp_backend' | sort -u)
    echo "[entrypoint] Required backends: ${REQUIRED_BACKENDS}"
    
    # Fetch each backend binary from ghcr.io
    for backend in ${REQUIRED_BACKENDS}; do
        binary_path="/opt/lemonade/llama/${backend}/llama-server"
        if [ ! -f "$binary_path" ]; then
            echo "[entrypoint] Fetching ${backend} binary from ${TQ_REGISTRY}/${TQ_USER}/llama-cpp-${backend}-tq:${TQ_TAG}..."
            
            # Authenticate to ghcr.io
            if [ -n "${GHCR_TOKEN}" ]; then
                echo "[entrypoint] Authenticated to ${TQ_REGISTRY}"
                echo "${GHCR_TOKEN}" | docker login "${TQ_REGISTRY}" -u "${TQ_USER}" --password-stdin 2>/dev/null || true
            fi
            
            # Pull the image and extract the binary + libs
            image="${TQ_REGISTRY}/${TQ_USER}/llama-cpp-${backend}-tq:${TQ_TAG}"
            docker pull "${image}" 2>/dev/null || true
            
            # Extract binary
            tmp_container=$(docker create "${image}" ls /usr/local/bin/llama-server)
            docker cp "${tmp_container}:/usr/local/bin/llama-server" "$binary_path" 2>/dev/null || true
            docker rm "${tmp_container}" >/dev/null 2>&1
            
            # Extract shared libs
            tmp_container=$(docker create "${image}" ls /usr/local/lib/libggml* /usr/local/lib/libllama* /usr/local/lib/libmtmd* 2>/dev/null || true)
            if [ -n "$tmp_container" ] && [ -f "$binary_path" ]; then
                mkdir -p "/opt/lemonade/llama/${backend}"
                docker cp "${tmp_container}:/usr/local/lib/libggml*" "/opt/lemonade/llama/${backend}/" 2>/dev/null || true
                docker cp "${tmp_container}:/usr/local/lib/libllama*" "/opt/lemonade/llama/${backend}/" 2>/dev/null || true
                docker cp "${tmp_container}:/usr/local/lib/libmtmd*" "/opt/lemonade/llama/${backend}/" 2>/dev/null || true
                docker rm "${tmp_container}" >/dev/null 2>&1
            fi
            
            chmod +x "$binary_path" 2>/dev/null || true
            echo "[entrypoint] ${backend} binary extracted to ${binary_path}"
        else
            echo "[entrypoint] ${backend} binary already at ${binary_path}"
        fi
    done
else
    echo "[entrypoint] No recipe_options.json found, skipping backend detection"
fi

# Update LD_LIBRARY_PATH to include all backend libs
export LD_LIBRARY_PATH="/opt/lemonade/llama/rocm:/opt/lemonade/llama/vulkan:/opt/lemonade/llama/cpu:${LD_LIBRARY_PATH:-/opt/rocm/lib}"

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
