# Phase 4/5/6: CI/CD, Splunk, GitHub Mirror

## Architecture

```
big-chungus (192.168.50.10)                    NAS (192.168.50.11)
┌──────────────────────────┐                   ┌──────────────────────────┐
│ Gitea Actions Runner     │──SSH push──▶      │ lemonade-tq-server       │
│ (builds on 3x 7900 XTX)  │                   │ (health check + rollback)│
│                          │                   │                          │
│ 1. llama-cpp-tq build    │  ──SSH──▶         │ fluent-bit (Splunk)      │
│ 2. Docker image build    │  ──SSH──▶         │ GitHub mirror cron       │
└──────────────────────────┘                   └──────────────────────────┘
```

## Setup Instructions

### 1. Gitea Actions Runner

```bash
# Get runner token from Gitea
# http://192.168.50.11:3042/settings/runners

cd /home/mkadrlik/docker/gitea-runner
cat > .env << 'EOF'
GITEA_RUNNER_TOKEN=your-registration-token-here
EOF

docker compose up -d
docker logs -f gitea-runner
```

### 2. SSH Keys for NAS Access

```bash
# On big-chungus, ensure SSH key exists
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N "" -C "ci-runner"

# Copy to NAS
ssh-copy-id mkadrlik@192.168.50.11

# Test
ssh mkadrlik@192.168.50.11 "echo 'SSH works'"
```

### 3. Splunk Logging

```bash
cd /home/mkadrlik/docker/fluent-bit
cp .env.example .env
# Edit .env with your Splunk HEC details

docker compose up -d
docker logs -f fluent-bit
```

### 4. GitHub Mirror

```bash
# Add secrets to Gitea repo settings:
# - GITHUB_TOKEN: GitHub personal access token with repo scope
# - GITEA_PAT: Gitea personal access token

# Workflow will auto-mirror on push
```

## Workflows

| Workflow | Trigger | Action |
|----------|---------|--------|
| `build-deploy.yml` | Tag push (`v*`) | Build Docker image, deploy to NAS, health check, rollback |
| `build-llama-rocm.yml` | Tag push (`v*`) | Build llama-cpp with ROCm, deploy binary to NAS |
| `mirror-github.yml` | Push to main / every 6h | Mirror repo to GitHub |

## Rollback Procedure

Automatic rollback is built into `build-deploy.yml`:

1. If health check fails after deploy
2. Finds previous version tag
3. Restores previous image
4. Restarts container
5. Verifies health

Manual rollback:
```bash
ssh mkadrlik@192.168.50.11 << 'EOF'
  cd /home/mkadrlik/docker/lemonade-tq
  # List available versions
  docker images lemonade-tq
  
  # Rollback to specific version
  PREV=v0.0.1
  docker compose down
  sed -i "s/image: .*/image: lemonade-tq:${PREV}/" docker-compose.yml
  docker compose up -d
  
  # Verify
  sleep 10
  docker inspect --format='{{.State.Health.Status}}' lemonade-tq-server
EOF
```

## Splunk Dashboards

### Lemonade-TQ Health
```
index=main source=docker component=Server
| stats count by level
| where level="Error" OR level="Warning"
```

### Model Load Times
```
index=main source=docker component=Model
| search message="*loaded*"
| stats avg(load_time) by model_name
```

### TurboQuant KV Cache Stats
```
index=main source=docker
| search message="*TurboQuant*" OR message="*turbo*"
| stats count by level
```

### LiteLLM Request Latency
```
index=main source=docker component=LiteLLM
| stats avg(latency_ms) p95(latency_ms) p99(latency_ms) by model
```

### Error Rate by Hour
```
index=main source=docker level=Error
| bin _time span=1h
| stats count by _time
| timechart span=1h count
```

## File Inventory

| Path | Purpose |
|------|---------|
| `/home/mkadrlik/docker/gitea-runner/` | Actions runner Docker compose |
| `/home/mkadrlik/docker/fluent-bit/` | Splunk log shipper |
| `/home/mkadrlik/docker/lemonade-tq/.gitea/workflows/` | CI/CD workflows |
| `/home/mkadrlik/docker/lemonade-tq/docker-compose.yml` | Updated for versioned images |

## Known Limitations

1. **No Docker registry** — Using SSH-based image transfer instead
2. **Single runner** — Only big-chungus has GPUs for ROCm builds
3. **Manual Splunk setup** — Requires HEC endpoint and token
4. **GitHub mirror** — Only mirrors code, not Docker images

## Troubleshooting

| Symptom | Check | Fix |
|---------|-------|-----|
| Runner not connecting | `docker logs gitea-runner` | Verify token and URL |
| SSH fails | `ssh mkadrlik@192.168.50.11` | Check keys and permissions |
| Health check fails | `docker logs lemonade-tq-server` | Check model loading |
| Splunk not receiving | `docker logs fluent-bit` | Verify HEC credentials |
| GitHub mirror fails | Check Gitea workflow logs | Verify tokens |
