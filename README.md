# lemonade-tq

[Lemonade SDK](https://github.com/lemonade-sdk) inference server with **TurboQuant** KV cache compression and multi-GPU tensor parallelism via Split Mode Graph.

## Overview

lemonade-tq wraps the Lemonade SDK server with a custom-built `llama-server` binary compiled from [llama.cpp with TurboQuant](https://github.com/TheTom/llama-cpp-turboquant). It provides:

- **TurboQuant 3-bit KV cache** — 5.12x compression, <0.1% perplexity cost
- **Multi-GPU tensor parallelism** — Split Mode Graph
- **Auto-loading models** — Configure models to load on startup
- **Health checks** — Built-in curl-based health endpoint
- **Three backend variants** — ROCm (AMD), Vulkan, or CPU-only
- **Parameterized deployment** — All settings via `.env` file

## Architecture

```
┌─────────────────────────────────────────────┐
│  lemonade-tq Docker Container               │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  Lemonade SDK Server                │    │
│  │  (ghcr.io/lemonade-sdk/lemonade)    │    │
│  │                                     │    │
│  │  ┌─────────────────────────────┐    │    │
│  │  │  llama-server (custom)      │    │    │
│  │  │  TurboQuant + Split Mode    │    │    │
│  │  │  Backend: ROCm/Vulkan/CPU   │    │    │
│  │  └─────────────────────────────┘    │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  entrypoint.sh → auto-load models           │
└─────────────────────────────────────────────┘
         ▲                    ▲
         │                    └─ Host GPU libs (ro)
         └─ Model GGUF files (volume mount)
```

## Quick Start

### 1. Configure

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env for your hardware (backend, GPUs, models)
nano .env
```

Key settings in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `LEMONADE_IMAGE` | `mkadrlik/lemonade-tq:latest` | Pre-built server image |
| `LEMONADE_PORT` | `13305` | Host port mapping |
| `LEMONADE_HOST` | `0.0.0.0` | Bind address |
| `LEMONADE_LLAMACPP_BACKEND` | `rocm` | Backend: `rocm`, `vulkan`, or `cpu` |
| `TQ_REGISTRY` | `ghcr.io` | TurboQuant image registry |
| `TQ_USER` | `mkadrlik` | TurboQuant image owner |
| `TQ_TAG` | `latest` | TurboQuant image tag |
| `GHCR_TOKEN` | *(empty)* | GitHub PAT for private image pull |
| `HSA_OVERRIDE_GFX_VERSION` | `11.0.0` | ROCm GPU architecture override |
| `HIP_VISIBLE_DEVICES` | `0,1,2` | ROCm GPU indices |
| `LEMONADE_LLAMACPP_ARGS` | *(empty)* | TurboQuant + llama-server flags |
| `AUTO_LOAD_MODELS` | *(empty)* | Space-separated model names |

### 2. Deploy

```bash
docker compose up -d
docker compose logs -f
```

The entrypoint will:
1. Detect required backends from `config.json` + `recipe_options.json`
2. Pull TurboQuant images from `ghcr.io` and extract `llama-server` binaries
3. Start the Lemonade server
4. Auto-load configured models

### 3. Build from source (optional)

If you need a custom build, uncomment the `build:` section in `docker-compose.yml` and comment out `image:`:

```yaml
# image: ${LEMONADE_IMAGE}
build:
    context: .
    args:
        BACKEND: ${LEMONADE_LLAMACPP_BACKEND}
```

## Configuration Files

- `.env` — Environment variables (copy from `.env.example`)
- `config/config.json` — Lemonade server settings
- `config/recipe_options.json` — Per-model overrides (context size, backend, args)

## TurboQuant Configuration

### Global Arguments

Set via `LEMONADE_LLAMACPP_ARGS` in `.env`:

```bash
# Global defaults for all models
LEMONADE_LLAMACPP_ARGS="--sm tensor -ngl 99 -ctk turbo3 -ctv turbo3 --tensor-split 1,1,1"
```

| Flag | Value | Description |
|------|-------|-------------|
| `--sm` | `tensor` / `graph` | Split Mode: tensor parallelism or graph |
| `-ngl` | `99` | Offload all layers to GPU |
| `-ctk` | `turbo` / `turbo3` | TurboQuant key cache compression |
| `-ctv` | `turbo` / `turbo3` | TurboQuant value cache compression |
| `--tensor-split` | `1,1,1` | Layer distribution across GPUs (one value per GPU) |
| `-fa` | `on` | Flash attention (reduces memory for attention layers) |

### Per-Model Overrides

In `config/recipe_options.json`, override per model:

```json
{
  "YourModel-GGUF": {
    "ctx_size": 226000,
    "llamacpp_backend": "rocm",
    "llamacpp_args": "--n-cpu-moe 20 -fa on --temp 0.6 --tensor-split 1,1,1"
  }
}
```

## Auto-Loading Models

Set the `AUTO_LOAD_MODELS` environment variable in `.env` (space-separated model names):

```bash
AUTO_LOAD_MODELS="Model1-GGUF Model2-GGUF Model3-GGUF"
```

Models are loaded sequentially after the server health check passes.

## Backend-Specific Setup

### ROCm (AMD)

Default backend. Set in `.env`:

```bash
LEMONADE_LLAMACPP_BACKEND=rocm
HSA_OVERRIDE_GFX_VERSION=11.0.0    # For RDNA2/RDNA3
HIP_VISIBLE_DEVICES=0,1,2           # Which GPUs to use
```

The compose file mounts:
- `/dev/kfd`, `/dev/dri`, `/dev/mem` for GPU access
- `/opt/rocm:/opt/rocm:ro` for ROCm runtime
- `./llama/rocm/llama-server` for the custom binary

### Vulkan

```bash
LEMONADE_LLAMACPP_BACKEND=vulkan
```

### CPU

```bash
LEMONADE_LLAMACPP_BACKEND=cpu
```

## Building Custom llama-server

Use the companion repos to build a TurboQuant-enabled `llama-server`:

- [llama-cpp-rocm-tq](https://github.com/mkadrlik/llama-cpp-rocm-tq) — AMD ROCm
- [llama-cpp-vulkan-tq](https://github.com/mkadrlik/llama-cpp-vulkan-tq) — Vulkan
- [llama-cpp-cpu-tq](https://github.com/mkadrlik/llama-cpp-cpu-tq) — CPU-only

```bash
# Build and extract the binary
docker build -t llama-server-rocm ../llama-cpp-rocm-tq
docker create --name tmp llama-server-rocm
docker cp tmp:/usr/local/bin/llama-server ./llama/rocm/llama-server
docker rm tmp
```

Or use the pre-built images from `ghcr.io/mkadrlik/llama-cpp-{rocm,vulkan,cpu}-tq:latest` — the entrypoint will auto-extract the binary on startup.

## API

The Lemonade server exposes an OpenAI-compatible API:

```bash
# Load a model
curl -X POST http://localhost:13305/api/v1/load \
  -H "Content-Type: application/json" \
  -d '{"model_name": "YourModel-GGUF", "ctx_size": 8192}'

# Chat completion
curl http://localhost:13305/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "YourModel-GGUF",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

# Health check
curl http://localhost:13305/health
```

## Performance Tips

1. **Always use TurboQuant** (`-ctk turbo3 -ctv turbo3`) — 5x more context for the same VRAM
2. **Use Flash Attention** (`-fa on`) — reduces memory for attention-heavy models
3. **Tensor-split evenly** — `--tensor-split 1,1,1` for 3 identical GPUs
4. **Set context size per model** — larger context = more memory, use `recipe_options.json`
5. **Monitor VRAM** — Lemonade shows per-model memory usage in the Web UI

## License

Lemonade SDK: Apache 2.0. TurboQuant patches by TheTom. This wrapper: MIT.
