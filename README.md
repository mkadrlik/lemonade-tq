# lemonade-tq

[Lemonade SDK](https://github.com/lemonade-sdk) inference server with **TurboQuant** KV cache compression and multi-GPU tensor parallelism via Split Mode Graph.

## Overview

lemonade-tq wraps the Lemonade SDK server with a custom-built `llama-server` binary compiled from [llama.cpp with TurboQuant](https://github.com/domvox/llama.cpp-turboquant-hip). It provides:

- **TurboQuant 3-bit KV cache** — 5.12x compression, <0.1% perplexity cost
- **Multi-GPU tensor parallelism** — Split Mode Graph via NCCL
- **Auto-loading models** — Configure models to load on startup
- **Health checks** — Built-in curl-based health endpoint
- **Three backend variants** — ROCm (AMD), NVIDIA CUDA, or CPU-only

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
│  │  │  Backend: ROCm/CUDA/CPU     │    │    │
│  │  └─────────────────────────────┘    │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  entrypoint.sh → auto-load models           │
└─────────────────────────────────────────────┘
         ▲                    ▲
         │                    └─ Host ROCm/CUDA libs (ro)
         └─ Model GGUF files (volume mount)
```

## Quick Start

### 1. Build the image

```bash
# ROCm (AMD GPUs) — default
docker build -t lemonade-tq .

# NVIDIA GPUs
docker build --build-arg BACKEND=nvidia -t lemonade-tq .

# CPU-only
docker build --build-arg BACKEND=cpu -t lemonade-tq .
```

### 2. Configure

Copy `docker-compose.yml.example` to `docker-compose.yml` and customize:

```bash
cp docker-compose.yml.example docker-compose.yml
# Edit docker-compose.yml for your hardware
```

Key configuration files:
- `config/config.json` — Lemonade server settings
- `config/recipe_options.json` — Per-model overrides (context size, backend, args)
- `config/50-local.conf` — Environment variable overrides

### 3. Deploy

```bash
docker compose up -d
docker compose logs -f
```

## TurboQuant Configuration

### Global Arguments

Set via `LEMONADE_LLAMACPP_ARGS` in docker-compose.yml or `config/50-local.conf`:

```bash
# Global defaults for all models
LEMONADE_LLAMACPP_ARGS="--sm tensor -ngl 99 -ctk turbo3 -ctv turbo3 --tensor-split 1,1,1"
```

| Flag | Value | Description |
|------|-------|-------------|
| `--sm` | `tensor` / `graph` | Split Mode: tensor parallelism or NCCL graph |
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

Set the `AUTO_LOAD_MODELS` environment variable (space-separated model names):

```yaml
environment:
  AUTO_LOAD_MODELS: "Model1-GGUF Model2-GGUF Model3-GGUF"
```

Models are loaded sequentially after the server health check passes.

## Backend-Specific Setup

### ROCm (AMD)

```yaml
devices:
  - /dev/kfd
  - /dev/dri
security_opt:
  - seccomp=unconfined
environment:
  LEMONADE_LLAMACPP_BACKEND: rocm
  HSA_OVERRIDE_GFX_VERSION: "11.0.0"    # For RDNA2/RDNA3
  HIP_VISIBLE_DEVICES: "0,1,2"           # Which GPUs to use
volumes:
  - /opt/rocm:/opt/rocm:ro              # ROCm runtime from host
  - ./llama/rocm/llama-server:/opt/lemonade/llama/rocm/llama-server:ro
```

### NVIDIA (CUDA)

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 3                        # Number of GPUs
environment:
  LEMONADE_LLAMACPP_BACKEND: cuda
volumes:
  - ./llama/cuda/llama-server:/opt/lemonade/llama/cuda/llama-server:ro
```

### CPU

```yaml
environment:
  LEMONADE_LLAMACPP_BACKEND: cpu
volumes:
  - ./llama/cpu/llama-server:/opt/lemonade/llama/cpu/llama-server:ro
```

## Building Custom llama-server

Use the companion repos to build a TurboQuant-enabled `llama-server`:

- [llama-cpp-rocm-tq](https://github.com/mkadrlik/llama-cpp-rocm-tq) — AMD ROCm
- [llama-cpp-nvidia-tq](https://github.com/mkadrlik/llama-cpp-nvidia-tq) — NVIDIA CUDA
- [llama-cpp-cpu-tq](https://github.com/mkadrlik/llama-cpp-cpu-tq) — CPU-only

```bash
# Build and extract the binary
docker build -t llama-server-rocm ../llama-cpp-rocm-tq
docker create --name tmp llama-server-rocm
docker cp tmp:/usr/local/bin/llama-server ./llama/rocm/llama-server
docker rm tmp
```

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
4. **Set context size per model** — larger context = more memory, use recipe_options.json
5. **Monitor VRAM** — Lemonade shows per-model memory usage in the Web UI

## License

Lemonade SDK: Apache 2.0. TurboQuant patches by domvox. This wrapper: MIT.
