# lemonade-tq

Custom Lemonade SDK inference server with **ROCm TurboQuant** for long-context inference and **Vulkan** for speed.

## Architecture

```
lemonade-tq
├── Dockerfile          # Multi-stage build: fetches binaries from ghcr.io
├── entrypoint.sh       # Backend detection + binary extraction logic
├── docker-compose.yml  # Production deployment config (port 13306)
├── config/
│   ├── config.json     # Global Lemonade server config
│   └── recipe_options.json  # Per-model backend + args overrides
└── data/
    └── cache/hub/      # HuggingFace model cache (bind-mounted)
```

## Two Backends, Two Purposes

| Backend | Image | Purpose | TurboQuant | Context | Speed |
|---------|-------|---------|------------|---------|-------|
| **ROCm** | `ghcr.io/mkadrlik/llama-cpp-rocm-tq:latest` | Long-context inference | Yes (turbo3) | Up to 256K tokens | Slightly slower TG |
| **Vulkan** | `ghcr.io/mkadrlik/llama-cpp-vulkan-tq:latest` | Fast inference | No | Standard contexts | Faster TG |

### ROCm (Long Context + TurboQuant)

ROCm is the **only** backend that supports TurboQuant KV cache compression. Use it when you need:
- Context windows beyond 32K tokens
- TurboQuant compression (3-bit, 5.12x KV cache reduction)
- Multi-GPU tensor splitting (3x RX 7900 XTX)

**TurboQuant KV Cache Compression:**

| Type | Bits | Compression | PPL Cost |
|------|------|-------------|----------|
| `turbo3` | 3-bit | 5.12x | <1% (recommended) |
| `turbo4` | 4-bit | 3.8x | +0.23% |
| `turbo2` | 2-bit | 7.5x | +3.7% |

### Vulkan (Speed)

Vulkan is the **fastest** inference backend for standard workloads. Use it when:
- You need maximum tokens/second
- Context windows fit within standard VRAM (no TurboQuant needed)
- You want lower latency for interactive chat

**Vulkan requires:** `-fa on` (Flash Attention) for quantized models.

### CPU (Deprecated)

The CPU backend is **deprecated**. It never provided meaningful TurboQuant benefits, was never tested on real hardware, and adds no value. It will be removed in a future release.

## Performance Benchmarks

### ROCm (TurboQuant, Long Context)

Tested with `Qwen3.6-27B-GGUF` (16.4 GiB) on 3x RX 7900 XTX:

| Metric | Value | Notes |
|--------|-------|-------|
| Prompt tok/s | 76-85 | turbo3 KV cache |
| Token gen | 21-25 | turbo3 KV cache |
| Max context | 226K tokens | TurboQuant enabled |

### Vulkan (Speed)

Tested with `Qwen3.6-35B-A3B-GGUF` on 3x RX 7900 XTX:

| Metric | Value | Notes |
|--------|-------|-------|
| Prompt tok/s | 83-90 | No TurboQuant |
| Token gen | 35-48 | Flash Attention on |
| Max context | 226K tokens | Standard KV cache |

## Usage

### Start the server

```bash
cd /home/mkadrlik/docker/lemonade-tq
docker compose up -d
```

Server listens on `http://localhost:13306`.

### Load a model

```bash
# Load with ROCm (TurboQuant, long context)
curl -X POST "http://localhost:13306/api/v1/load" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "Gemma-4-26B-A4B-it-GGUF"}'

# Load with Vulkan (speed)
curl -X POST "http://localhost:13306/api/v1/load" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "Gemma-4-E2B-it-GGUF", "llamacpp_backend": "vulkan"}'
```

### Chat completion

```bash
curl http://localhost:13306/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Gemma-4-26B-A4B-it-GGUF",
    "messages": [{"role": "user", "content": "What is 2+2?"}],
    "max_tokens": 50
  }'
```

### Available models

```bash
curl "http://localhost:13306/api/v1/models?show_all=true" | python3 -m json.tool
```

## Configuration

### Global config (`config/config.json`)

```json
{
  "llamacpp": {
    "args": "--tensor-split 1,1,1",
    "backend": "auto",
    "rocm_bin": "/opt/lemonade/llama/rocm/llama-server",
    "vulkan_bin": "/opt/lemonade/llama/vulkan/llama-server-wrapper.sh"
  }
}
```

### Per-model overrides (`config/recipe_options.json`)

```json
{
  "Gemma-4-26B-A4B-it-GGUF": {
    "ctx_size": 256000,
    "llamacpp_args": "-fit off --n-cpu-moe 16 -fa on --temp 1.0 --top-p 0.95 --tensor-split 1,1,1 -ctk turbo3 -ctv turbo3",
    "llamacpp_backend": "rocm"
  },
  "Gemma-4-E2B-it-GGUF": {
    "ctx_size": 8192,
    "llamacpp_args": "-fit off -fa on --temp 0.7 --top-p 0.95",
    "llamacpp_backend": "vulkan"
  }
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LEMONADE_PORT` | `13306` | Host port mapping |
| `LEMONADE_LLAMACPP_BACKEND` | `auto` | Default backend |
| `TQ_REGISTRY` | `ghcr.io` | TurboQuant image registry |
| `TQ_USER` | `mkadrlik` | ghcr.io user/org |
| `TQ_TAG` | `latest` | Image tag |
| `GHCR_TOKEN` | (required) | ghcr.io PAT for auth |
| `HIP_VISIBLE_DEVICES` | `0,1,2` | ROCm GPU selection |
| `HSA_OVERRIDE_GFX_VERSION` | `11.0.0` | ROCm GFX override |

## Building Backends

See the following repos on Gitea for build workflows:
- **ROCm**: `llama-cpp-rocm-tq` — ROCm + TurboQuant, gfx1100 (RX 7900 series)
- **Vulkan**: `llama-cpp-vulkan-tq` — Vulkan SDK, cross-platform

## Troubleshooting

- **GGML_ASSERT(n_inputs < GGML_SCHED_MAX_SPLIT_INPUTS)**: Add `-fit off` to args.
- **Vulkan garbled output**: Add `-fa on` to args.
- **ROCm token gen slow at high context**: Known rocWMMA_FATTN bug. Ensure `GGML_HIP_ROCWMMA_FATTN` is disabled in the build.
- **Model not found**: Check `config/recipe_options.json` model name matches exactly.
- **Backend not available**: Check `GHCR_TOKEN` and network connectivity to ghcr.io.

## CI/CD

- Runner: `rocm/linux` (Gitea Actions)
- Pushes to: `ghcr.io/mkadrlik/lemonade-tq:latest`
- Trigger: push to main
