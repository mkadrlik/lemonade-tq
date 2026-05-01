#!/bin/bash
# Rebuild TurboQuant backend inside the container
# Usage: ./rebuild-backend.sh [branch]

set -euo pipefail

CONTAINER="lemonade-tq-server"
BRANCH="${1:-feature/turboquant-hip-port-clean}"
SRC="/tmp/llama.cpp-turboquant-hip"
DEST="/root/.cache/lemonade/bin/llamacpp/rocm-preview"

echo "=== Rebuilding TurboQuant backend ==="

# Stop container
echo "Stopping container..."
docker stop "$CONTAINER" 2>/dev/null || true
docker start "$CONTAINER"

# Wait for container to be ready
sleep 3

# Clone if needed
if [ ! -d "$SRC/build" ]; then
    echo "Cloning repo (branch: $BRANCH)..."
    docker exec "$CONTAINER" git clone --depth 1 -b "$BRANCH" \
        https://github.com/domvox/llama.cpp-turboquant-hip.git "$SRC"
fi

# Build
echo "Building inside container..."
docker exec "$CONTAINER" bash -c "
    export HIP_PATH=/opt/rocm
    export LD_LIBRARY_PATH=/opt/rocm/lib
    export HIP_DEVICE_LIB_PATH=/opt/rocm/lib/llvm/lib/clang/22/lib/amdgcn/bitcode
    cd $SRC
    cmake -S . -B build -DGGML_HIP=ON -DGPU_TARGETS=gfx1100 -DCMAKE_BUILD_TYPE=Release
    cmake --build build --target llama-server -- -j \$(nproc)
"

# Replace binaries
echo "Replacing backend binaries..."
docker exec "$CONTAINER" bash -c "
    cd $DEST
    cp llama-server llama-server.bak.\$(date +%s) 2>/dev/null || true
    cp $SRC/build/bin/llama-server $DEST/
    cp $SRC/build/bin/libggml*.so* $DEST/
    cp $SRC/build/bin/libllama.so* $DEST/
    cp $SRC/build/bin/libmtmd.so* $DEST/

    # Fix symlinks
    rm -f libllama.so libllama.so.0 libmtmd.so libmtmd.so.0
    NEW_LLAMA=\$(ls libllama.so.0.0.* | sort -V | tail -1 | sed 's/^libllama\.so\./''/g')
    NEW_MTMD=\$(ls libmtmd.so.0.0.* | sort -V | tail -1 | sed 's/^libmtmd\.so\./''/g')
    ln -sf libllama.so.0.0.\"$NEW_LLAMA\" libllama.so.0
    ln -sf libllama.so.0 libllama.so
    ln -sf libmtmd.so.0.0.\"$NEW_MTMD\" libmtmd.so.0
    ln -sf libmtmd.so.0 libmtmd.so
"

# Restart
echo "Restarting container..."
docker restart "$CONTAINER"
sleep 5

# Verify
echo "=== Verifying ==="
docker exec "$CONTAINER" bash -c "cd $DEST && LD_LIBRARY_PATH=. ./llama-server --help 2>&1 | grep -i turbo"
echo "=== Done ==="
