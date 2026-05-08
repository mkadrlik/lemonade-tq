# KV Cache Proxy

Drop-in replacement for llama.cpp chat completions with **KV cache checkpointing** for interruption/resume support.

## Problem

When a model generation is interrupted (Ctrl+C, disconnect, timeout), the KV cache built from processing the conversation context is discarded. The next prompt forces full reprocessing of every token — 10-30 seconds of wasted compute on 256K context.

## Solution

Save the KV cache before generation starts. On interruption, restore it and append the partial response + new prompt. The model continues from where it left off without reprocessing the conversation context.

## Architecture

```
Client → KV Cache Proxy (Python) → llama-cpp-python → GPU
              ↑
         Checkpoint/Restore on interrupt/resume
```

## Components

| File | Purpose |
|------|---------|
| `checkpoint.py` | KV cache save/restore with disk persistence |
| `extractor.py` | Scan partial output for clues, facts, incomplete thoughts |
| `resume.py` | Orchestrate interrupt → extract → resume flow |
| `server.py` | HTTP API server (drop-in chat completions replacement) |

## API Endpoints

### Chat Completions (OpenAI-compatible)

```bash
# Normal chat
curl http://localhost:13307/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'

# Resume after interruption
curl http://localhost:13307/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true,
    "resume_from": "abc123def456",
    "partial_response": "Hello! I was saying that the answer is 42 and"
  }'
```

### Model Management

```bash
# Load model
curl -X POST http://localhost:13307/v1/models \
  -H "Content-Type: application/json" \
  -d '{"model_path": "/app/models/Qwen3.6-27B-GGUF"}'

# List models
curl http://localhost:13307/v1/models
```

### Checkpoint Management

```bash
# Save checkpoint
curl -X POST http://localhost:13307/checkpoint/save \
  -H "Content-Type: application/json" \
  -d '{}'

# Restore checkpoint
curl -X POST http://localhost:13307/checkpoint/restore \
  -H "Content-Type: application/json" \
  -d '{"checkpoint_id": "abc123def456"}'
```

### Status

```bash
# Health check
curl http://localhost:13307/health

# Full status (active interruptions, checkpoints)
curl http://localhost:13307/status

# Get interruption info
curl http://localhost:13307/interrupted
```

## Usage

### Direct (Python)

```bash
cd kv-cache-proxy
pip install -r requirements.txt
python server.py --model /path/to/model.gguf --port 13307
```

### Docker

```bash
cd kv-cache-proxy
docker compose up --build
```

### With Open WebUI

Set the Open WebUI API endpoint to `http://localhost:13307/v1` instead of the production endpoint.

## How It Works

1. **Before generation**: KV cache is saved as a checkpoint
2. **During generation**: Tokens streamed to client
3. **On interruption**: Client disconnect detected → partial output captured → checkpoint saved
4. **On resume**: KV cache restored → partial response + new prompt appended → generation continues

The key insight: restoring the KV cache means the model doesn't need to reprocess the conversation context. Only the partial response and new prompt are re-processed (which is fast since they're short).

## Testing

```bash
# Test normal chat
curl http://localhost:13307/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is 2+2?"}], "max_tokens": 50}'

# Test streaming
curl -N http://localhost:13307/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Tell me a story"}], "stream": true}'

# Test resume
curl http://localhost:13307/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Continue"}],
    "resume_from": "<checkpoint_id>",
    "partial_response": "<partial output>"
  }'
```

## Data Flow

```
Request: {messages, stream=true}
    │
    ▼
Save KV cache → checkpoint_id
    │
    ▼
Generate tokens → stream to client
    │
    ├── Client disconnects → capture partial → save state
    │       │
    │       ▼
    │   InterruptionState {checkpoint_id, partial, history}
    │
    └── Complete → return response
            │
            ▼
Next request: {messages, resume_from, partial_response}
    │
    ▼
Restore KV cache from checkpoint_id
    │
    ▼
Append: [history] + [assistant: partial] + [user: new_prompt]
    │
    ▼
Generate from restored state (no full reprocessing!)
```
