# lemonade-tq

<<<<<<< Updated upstream
[Lemonade SDK](https://github.com/lemonade-sdk) inference server with **TurboQuant** KV cache compression and multi-GPU tensor parallelism via Split Mode Graph.

## Overview

lemonade-tq wraps the Lemonade SDK server with a custom-built `llama-server` binary compiled from [llama.cpp with TurboQuant](https://github.com/TheTom/llama-cpp-turboquant). It provides:

- **TurboQuant 3-bit KV cache** — 5.12x compression, <0.1% perplexity cost
- **Multi-GPU tensor parallelism** — Split Mode Graph
- **Auto-loading models** — Configure models to load on startup
- **Health checks** — Built-in curl-based health endpoint
- **Three backend variants** — ROCm (AMD), Vulkan, or CPU-only
- **Parameterized deployment** — All settings via `.env` file
=======
Custom Lemonade SDK inference server with TurboQuant KV cache compression support.
>>>>>>> Stashed changes

## Architecture

```
<<<<<<< Updated upstream
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
=======
lemonade-tq
├── Dockerfile          # Multi-stage build: fetches binaries from ghcr.io
├── entrypoint.sh       # Backend detection + binary extraction logic
├── docker-compose.yml  # Production deployment config (port 13306)
├── config/
│   ├── config.json     # Global Lemonade server config
│   └── recipe_options.json  # Per-model backend + args overrides
└── data/
    └── cache/hub/      # HuggingFace model cache (bind-mounted)
>>>>>>> Stashed changes
```

## Backends

<<<<<<< Updated upstream
### 1. Configure
=======
Three llama.cpp TurboQuant backends are built and pushed to `ghcr.io`:

| Backend | Image | GPU | Notes |
|---------|-------|-----|-------|
| ROCm | `ghcr.io/mkadrlik/llama-cpp-rocm-tq:latest` | AMD RX 7900 XTX | Primary backend, 3x GPU tensor-split |
| Vulkan | `ghcr.io/mkadrlik/llama-cpp-vulkan-tq:latest` | AMD RX 7900 XTX | RADV driver, requires `-fa on` |
| CPU | `ghcr.io/mkadrlik/llama-cpp-cpu-tq:latest` | Any | Fallback, uses OpenBLAS |

All backends support:
- TurboQuant KV cache compression (`-ctk turbo3 -ctv turbo3`)
- Flash Attention (`-fa on`)
- Multi-GPU tensor splitting (`--tensor-split 1,1,1`)

## Performance Benchmarks

Tested with `gemma-4-E2B-it-Q4_K_M` (2.7B params, Q4_K_M quant):

| Backend | Prompt tok/s | Predicted tok/s | Notes |
|---------|-------------|-----------------|-------|
| ROCm | 76-85 | 26-50 | 3x RX 7900 XTX, tensor-split |
| Vulkan | 83-90 | 35-48 | RADV driver, `-fa on` required |
| CPU | 76-168 | 28-37 | 8 threads, no GPU |

## Usage

### Start the server

```bash
cd /home/mkadrlik/docker/lemonade-tq
docker compose up -d
```

Server listens on `http://localhost:13306`.

### Load a model
>>>>>>> Stashed changes

```bash
# Load with default backend (ROCm)
curl -X POST "http://localhost:13306/api/v1/load" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "Gemma-4-E2B-it-GGUF"}'

# Load with specific backend
curl -X POST "http://localhost:13306/api/v1/load" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "Gemma-4-E2B-it-GGUF", "llamacpp_backend": "vulkan"}'
```

### Chat completion

```bash
curl http://localhost:13306/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Gemma-4-E2B-it-GGUF",
    "messages": [{"role": "user", "content": "What is 2+2?"}],
    "max_tokens": 50
  }'
```

<<<<<<< Updated upstream
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
=======
### Available models
>>>>>>> Stashed changes

```bash
curl "http://localhost:13306/api/v1/models?show_all=true" | python3 -m json.tool
```

<<<<<<< Updated upstream
| Flag | Value | Description |
|------|-------|-------------|
| `--sm` | `tensor` / `graph` | Split Mode: tensor parallelism or graph |
| `-ngl` | `99` | Offload all layers to GPU |
| `-ctk` | `turbo` / `turbo3` | TurboQuant key cache compression |
| `-ctv` | `turbo` / `turbo3` | TurboQuant value cache compression |
| `--tensor-split` | `1,1,1` | Layer distribution across GPUs (one value per GPU) |
| `-fa` | `on` | Flash attention (reduces memory for attention layers) |
=======
## Configuration
>>>>>>> Stashed changes

### Global config (`config/config.json`)

```json
{
  "llamacpp": {
    "args": "-fit off --sm layer -ctk turbo3 -ctv turbo3 --tensor-split 1,1,1",
    "backend": "auto",
    "rocm_bin": "/opt/lemonade/llama/rocm/llama-server",
    "vulkan_bin": "/opt/lemonade/llama/vulkan/llama-server",
    "cpu_bin": "/opt/lemonade/llama/cpu/llama-server"
  }
}
```

### Per-model overrides (`config/recipe_options.json`)

<<<<<<< Updated upstream
Set the `AUTO_LOAD_MODELS` environment variable in `.env` (space-separated model names):

```bash
AUTO_LOAD_MODELS="Model1-GGUF Model2-GGUF Model3-GGUF"
=======
```json
{
  "Gemma-4-E2B-it-GGUF": {
    "ctx_size": 8192,
    "llamacpp_args": "-fit off -fa on --temp 0.7 --top-p 0.95 -ctk turbo3 -ctv turbo3",
    "llamacpp_backend": "rocm"
  }
}
>>>>>>> Stashed changes
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LEMONADE_PORT` | `13306` | Host port mapping |
| `LEMONADE_LLAMACPP_BACKEND` | `rocm` | Default backend |
| `LEMONADE_LLAMACPP_ARGS` | `-fit off --sm layer -ctk turbo3 -ctv turbo3 --tensor-split 1,1,1` | Global args |
| `TQ_REGISTRY` | `ghcr.io` | TurboQuant image registry |
| `TQ_USER` | `mkadrlik` | ghcr.io user/org |
| `TQ_TAG` | `latest` | Image tag |
| `GHCR_TOKEN` | (required) | ghcr.io PAT for auth |
| `HIP_VISIBLE_DEVICES` | `0,1,2` | ROCm GPU selection |
| `HSA_OVERRIDE_GFX_VERSION` | `11.0.0` | ROCm GFX override |

## Building Backends

<<<<<<< Updated upstream
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
=======
See `llama-cpp-rocm-tq`, `llama-cpp-vulkan-tq`, and `llama-cpp-cpu-tq` repos on Gitea for build workflows.

## Troubleshooting

- **GGML_ASSERT(n_inputs < GGML_SCHED_MAX_SPLIT_INPUTS)**: Add `-fit off` to args.
- **Vulkan garbled output**: Add `-fa on` to args.
- **Model not found**: Check `config/recipe_options.json` model name matches exactly.
- **Backend not available**: Check `GHCR_TOKEN` and network connectivity to ghcr.io.
>>>>>>> Stashed changes
