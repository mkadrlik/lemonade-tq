# Lemonade-TQ Runbook

> Self-resolution procedures for outages, updates, and maintenance.
> Last updated: 2026-05-01
> Host: 192.168.50.10 (bc9fbbd804d4)
> Working directory: `/home/mkadrlik/docker/lemonade-tq/`

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  LiteLLM  (port 4000)                                  │
│  └──→ http://192.168.50.10:13305/api/v1/               │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  lemonade-tq-server  (port 13305)                │   │
│  │  ├── Custom image: lemonade-tq:latest            │   │
│  │  ├── Backend: rocm (3x RX 7900 XTX, 72GB total) │   │
│  │  ├── KV cache: turbo3 (kernel-level WHT)         │   │
│  │  └── 4 preloaded models (max_loaded_models=4)    │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Configuration Sources (highest precedence wins)

| Priority | Source | Path |
|----------|--------|------|
| 1 (highest) | Environment vars | `docker-compose.yml` → `environment:` block |
| 2 | Bind-mounted config | `config/config.json` → `/app/config/config.json` |
| 3 (lowest) | Image-baked defaults | `Dockerfile` COPY |

**Rule:** If flags disagree between files, the environment variable always wins. Keep all three consistent to avoid confusion.

### Critical Flags

| Flag | Current Value | Valid Values |
|------|--------------|--------------|
| `backend` | `rocm` | `auto`, `vulkan`, `rocm`, `cpu` — **NOT `hip`** |
| `llamacpp_args` | `--sm tensor -ngl 99 -ctk turbo3 -ctv turbo3 --tensor-split 1,1,1` | See below |
| `-ctk` / `-ctv` | `turbo3` | `turbo2`, `turbo3`, `turbo4` — **NOT bare `turbo`** |
| `-sm` | `tensor` | `tensor`, `layer`, `pipe` — `graph` requires NCCL rebuild |
| `--tensor-split` | `1,1,1` | Comma-separated weights per GPU |

---

## Quick Health Checks

### Is the container running?
```bash
docker ps --filter name=lemonade
# Expected: lemonade-tq-server   Status: Up   Port: 0.0.0.0:13305->13305
```

### Is the healthcheck passing?
```bash
docker inspect lemonade-tq-server --format='{{.State.Health.Status}}'
# Expected: healthy
```

### Can the API respond?
```bash
curl -s http://localhost:13305/api/v1/models | python3 -m json.tool | head -20
# Expected: list of available models
```

### Are TurboQuant kernels active?
```bash
docker logs lemonade-tq-server 2>&1 | grep -i "turbo\|kv.cache"
# Expected: "TurboQuant KV cache enabled" + "kernel-level WHT"
```

### Are models loaded?
```bash
curl -s http://localhost:13305/api/v1/models | python3 -c "
import sys, json
models = json.load(sys.stdin).get('data', [])
for m in models:
    print(f\"{'✓' if m.get('loaded') else '○'} {m['id']}\")
"
```

### Is LiteLLM connected?
```bash
curl -s http://localhost:4000/v1/models | python3 -m json.tool | head -20
# Expected: models list from Lemonade via LiteLLM proxy
```

---

## Outage Resolution

### Scenario 1: Container crashed or is unhealthy

```bash
# 1. Check logs for root cause
docker logs lemonade-tq-server --tail 100

# 2. Common errors and fixes:
#    "backend 'hip' must be one of: auto, vulkan, rocm, cpu"
#    → Fix: set LEMONADE_LLAMACPP_BACKEND=rocm in compose
#
#    "invalid argument: -ctk turbo"
#    → Fix: use turbo2, turbo3, or turbo4 (not bare 'turbo')
#
#    "failed to load model"
#    → Check model path exists in /app/user_models/
#    → Check GPU memory: rocm-smi

# 3. Restart
docker compose -f /home/mkadrlik/docker/lemonade-tq/docker-compose.yml up -d

# 4. Wait for models to load (~2-3 minutes for all 4)
sleep 180

# 5. Verify
curl -s http://localhost:13305/api/v1/models | python3 -m json.tool
```

### Scenario 2: Models not auto-loading on startup

The entrypoint script (`entrypoint.sh`) loads models after the server starts. If they're not loading:

```bash
# 1. Check entrypoint ran
docker logs lemonade-tq-server | grep -A2 "Loading model"

# 2. Manually load a model
curl -X POST http://localhost:13305/api/v1/load \
  -H "Content-Type: application/json" \
  -d '{"model_id": "Qwen3.6-35B-A3B"}'

# 3. Check user_models.json is correct
cat /home/mkadrlik/docker/lemonade-tq/config/user_models.json

# 4. Check recipe_options.json has matching entries
cat /home/mkadrlik/docker/lemonade-tq/config/recipe_options.json
```

### Scenario 3: GPU out of memory

```bash
# Check GPU utilization
rocm-smi

# If OOM, reduce max_loaded_models in config/config.json
# Or reduce tensor parallelism (--tensor-split)

# Force reload with fewer models
docker compose -f /home/mkadrlik/docker/lemonade-tq/docker-compose.yml down
# Edit config/config.json → max_loaded_models
docker compose -f /home/mkadrlik/docker/lemonade-tq/docker-compose.yml up -d
```

### Scenario 4: LiteLLM can't reach Lemonade

```bash
# 1. Check LiteLLM config
cat /home/mkadrlik/docker/litellm/config.yaml | grep -A5 lemonade

# 2. Verify connectivity from LiteLLM container
docker exec litellm-litellm-1 curl -s http://192.168.50.10:13305/api/v1/models

# 3. If no response, check firewall
sudo firewall-cmd --list-ports | grep 13305

# 4. Restart LiteLLM
docker compose -f /home/mkadrlik/docker/litellm/docker-compose.yml restart
```

### Scenario 5: ROCm driver issues after host update

```bash
# 1. Check ROCm is loaded
lsmod | grep amdgpu

# 2. Check ROCm tools work
rocm-smi

# 3. If broken, restart ROCm services
sudo systemctl restart systemd-udev-trigger

# 4. Restart container
docker compose -f /home/mkadrlik/docker/lemonade-tq/docker-compose.yml up -d
```

---

## Updates

### Updating the Docker Image

```bash
cd /home/mkadrlik/docker/lemonade-tq

# 1. Pull latest base image
docker pull ghcr.io/lemonade-sdk/lemonade-server:latest

# 2. Rebuild custom image
docker build -t lemonade-tq:latest .

# 3. Test the new image (run alongside old)
docker run --rm --name lemonade-test \
  --gpus all \
  -p 13306:13305 \
  -v $(pwd)/config:/app/user_config \
  -v $(pwd)/models:/app/user_models \
  lemonade-tq:latest

# 4. Verify on port 13306
curl -s http://localhost:13306/api/v1/models

# 5. If good, swap
docker compose -f docker-compose.yml down
docker compose -f docker-compose.yml up -d --build

# 6. Clean old images
docker image prune
```

### Updating config.json

```bash
# 1. Edit config
nano /home/mkadrlik/docker/lemonade-tq/config/config.json

# 2. Validate JSON
python3 -m json.tool /home/mkadrlik/docker/lemonade-tq/config/config.json

# 3. Restart container (bind mount picks up changes)
docker compose -f /home/mkadrlik/docker/lemonade-tq/docker-compose.yml restart
```

### Updating models

```bash
# 1. Add model to user_models.json
# 2. Add matching entry in recipe_options.json
# 3. Pull the model (if not already present)
# 4. Restart container
docker compose -f /home/mkadrlik/docker/lemonade-tq/docker-compose.yml restart

# Models will auto-load if max_loaded_models allows it
```

### Updating recipe_options.json

```bash
# 1. Edit
nano /home/mkadrlik/docker/lemonade-tq/config/recipe_options.json

# 2. Validate
python3 -m json.tool /home/mkadrlik/docker/lemonade-tq/config/recipe_options.json

# 3. Restart (bind-mounted into /app/.cache/)
docker compose -f /home/mkadrlik/docker/lemonade-tq/docker-compose.yml restart
```

---

## Adding a New Model

1. **Find the HF repo** — search HuggingFace for the GGUF variant
2. **Add to `user_models.json`**:
   ```json
   {
     "id": "Model-Name",
     "source": "hf",
     "repo": "org/repo",
     "filename": "model.Q4_K_M.gguf"
   }
   ```
3. **Add to `recipe_options.json`**:
   ```json
   {
     "id": "Model-Name",
     "backend": "rocm",
     "llamacpp_args": "--sm tensor -ngl 99 -ctk turbo3 -ctv turbo3 --tensor-split 1,1,1"
   }
   ```
4. **Restart** — model will download on first request or auto-load if under `max_loaded_models`

---

## Troubleshooting Checklist

| Symptom | Check | Fix |
|---------|-------|-----|
| Container won't start | `docker logs` | Fix config error |
| Backend rejected | `LEMONADE_LLAMACPP_BACKEND` | Must be `rocm`, not `hip` |
| KV cache rejected | `-ctk` value | Must be `turbo2/3/4`, not `turbo` |
| Model won't load | `rocm-smi` VRAM | Reduce loaded models or use smaller quant |
| Slow first response | Model loaded? | Check `entrypoint.sh` logs |
| LiteLLM 502 errors | `curl localhost:13305` | Lemonade unreachable |
| OOM kill | `dmesg \| grep -i oom` | Increase swap (32GB), reduce models |
| Healthcheck fails | `curl` in container | Rebuild with `entrypoint.sh` |
| GPU not detected | `rocm-smi` | Check ROCm driver, `--gpus all` |

---

## File Inventory

| File | Purpose | Mounted As |
|------|---------|------------|
| `docker-compose.yml` | Container orchestration | — |
| `Dockerfile` | Custom image build | — |
| `entrypoint.sh` | Auto-load models on startup | `/app/entrypoint.sh` |
| `config/config.json` | Server config (max_loaded_models, backend) | `/app/user_config/config.json` |
| `config/user_models.json` | Model definitions (HF repos) | `/app/user_config/user_models.json` |
| `config/recipe_options.json` | Per-model backend/args | `/app/.cache/recipe_options.json` |
| `models/` | Downloaded GGUF files | `/app/user_models/` |

---

## Emergency Rollback

If a new image or config breaks everything:

```bash
# 1. Stop broken container
docker compose -f /home/mkadrlik/docker/lemonade-tq/docker-compose.yml down

# 2. Revert config files (if git-tracked)
cd /home/mkadrlik/docker/lemonade-tq
git checkout -- config/

# 3. Or restore from backup
cp config/config.json.bak config/config.json

# 4. Rebuild from known-good image tag
docker tag lemonade-tq:backup lemonade-tq:latest

# 5. Start
docker compose -f /home/mkadrlik/docker/lemonade-tq/docker-compose.yml up -d
```

---

## Known Limitations

- **`--sm graph` not yet supported** — bundled binary doesn't support graph mode. Requires rebuilding llama-server with NCCL from the domvox fork.
- **Docker registry push blocked** — `192.168.50.11:5000` needs `insecure-registries` in `/etc/docker/daemon.json`. Currently using local image only.
- **Max 4 models loaded** — `max_loaded_models=4` in config. Other models load on-demand (cold start ~30s).
- **No GPU hot-swap** — container must restart if GPU topology changes.

---

## Contacts & Escalation

| Issue | Action |
|-------|--------|
| Config error | Fix file, restart container |
| GPU driver crash | `sudo systemctl restart systemd-udev-trigger`, then restart container |
| ROCm firmware issue | Host reboot required |
| Model corruption | Delete from `models/`, restart to re-download |
| Can't resolve | Check `docker logs lemonade-tq-server --tail 200` |
