# Lemonade + TurboQuant Setup

## What was done

1. Built llama.cpp-turboquant-hip INSIDE the container (Ubuntu 24.04 GLIBC 2.39)
   - Host is Fedora 44 with GLIBC 2.43 - building on host would cause GLIBC mismatch
   - Source: domvox/llama.cpp-turboquant-hip branch feature/turboquant-hip-port-clean

2. Replaced backend binaries at /root/.cache/lemonade/bin/llamacpp/rocm-preview/
   - llama-server binary
   - ALL shared libs: libggml-hip.so, libggml-cpu.so, libggml-base.so, libggml.so, libllama.so, libmtmd.so
   - Fixed symlinks to point to correct versioned files (.0.0.8699)

3. Container mounts host ROCm at /opt/rocm (read-only)

## TurboQuant args

-ctk turbo3 -ctv turbo3 (3-bit KV cache, 5.12x compression, <0.1% PPL cost)

Set via LEMONADE_LLAMACPP_ARGS env var in docker-compose.yml.

Note: -ngl is managed by Lemonade (set via /v1/load API), --sm is not supported.

## GPU Setup

3x AMD Radeon RX 7900 XTX (gfx1100), 24GB each = 73GB total VRAM
HSA_OVERRIDE_GFX_VERSION=11.0.0 for ROCm compatibility

## Ports

- 13306 -> 13305 (HTTP/Web UI)
- WebSocket on port 9000 (internal)

## Commands

docker compose up -d          # Start
docker compose down           # Stop
docker compose logs -f        # Follow logs
docker restart lemonade-tq-server  # Restart

## Load model with TurboQuant

curl -X POST http://localhost:13306/v1/load \
  -H "Content-Type: application/json" \
  -d '{"model_name": "user.MyModel-GGUF", "ctx_size": 8192, "llamacpp_backend": "rocm", "llamacpp_args": "-ctk turbo3 -ctv turbo3"}'
