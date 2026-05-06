# lemonade-tq

Custom Lemonade SDK inference server with TurboQuant KV cache compression. Fetches llama.cpp binaries from ghcr.io at startup.

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

## Backends

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

### Available models

```bash
curl "http://localhost:13306/api/v1/models?show_all=true" | python3 -m json.tool
```

## Configuration

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

```json
{
  "Gemma-4-E2B-it-GGUF": {
    "ctx_size": 8192,
    "llamacpp_args": "-fit off -fa on --temp 0.7 --top-p 0.95 -ctk turbo3 -ctv turbo3",
    "llamacpp_backend": "rocm"
  }
}
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

See `llama-cpp-rocm-tq`, `llama-cpp-vulkan-tq`, and `llama-cpp-cpu-tq` repos on Gitea for build workflows.

## Troubleshooting

- **GGML_ASSERT(n_inputs < GGML_SCHED_MAX_SPLIT_INPUTS)**: Add `-fit off` to args.
- **Vulkan garbled output**: Add `-fa on` to args.
- **Model not found**: Check `config/recipe_options.json` model name matches exactly.
- **Backend not available**: Check `GHCR_TOKEN` and network connectivity to ghcr.io.
- **Docker not found in entrypoint**: Install docker in the image.

## CI/CD

- Runner: `rocm/linux` (Gitea Actions)
- Pushes to: `ghcr.io/mkadrlik/lemonade-tq:latest`
- Trigger: push to main
- Branch: `home-lab` (specific config), `main` (generic)
