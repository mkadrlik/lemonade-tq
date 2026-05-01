# Splunk Logging Configuration for Lemonade-TQ + LiteLLM
# 
# Architecture:
#   Containers → Docker json-file log driver → Fluent Bit → Splunk HEC
#
# Prerequisites:
#   - Splunk HEC endpoint with token
#   - Fluent Bit container running on NAS
#   - Docker log driver configured (already in daemon.json)

---

## 1. Docker Log Driver (Already Configured)

/etc/docker/daemon.json:
```json
{
  "insecure-registries": ["192.168.50.11:5000"],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

Per-container override in docker-compose.yml:
```yaml
services:
  lemonade-tq-server:
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
        tag: "lemonade-tq"
  
  litellm-litellm-1:
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
        tag: "litellm"
```

---

## 2. Fluent Bit Configuration

Create `/home/mkadrlik/docker/fluent-bit/docker-compose.yml`:

```yaml
version: '3.8'

services:
  fluent-bit:
    image: cr.fluentbit.io/fluent/fluent-bit:latest
    container_name: fluent-bit
    restart: unless-stopped
    networks:
      - splunk
    volumes:
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - ./fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf
    environment:
      - SPLUNK_HEC_URL=${SPLUNK_HEC_URL}
      - SPLUNK_HEC_TOKEN=${SPLUNK_HEC_TOKEN}
      - SPLUNK_INDEX=${SPLUNK_INDEX:-main}
      - SPLUNK_SOURCE_TYPE=${SPLUNK_SOURCE_TYPE:-docker_json}
    ports:
      - "2020:2020"  # Fluent Bit admin API
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:2020/api/v1/info"]
      interval: 30s
      timeout: 10s
      retries: 3

networks:
  splunk:
    driver: bridge
```

Create `/home/mkadrlik/docker/fluent-bit/fluent-bit.conf`:

```ini
[SERVICE]
    Flush         5
    Daemon        Off
    Log_Level     info
    Parsers_File  parsers.conf
    HTTP_Server   On
    HTTP_Listen   0.0.0.0
    HTTP_Port     2020

# Tail Docker container logs
[INPUT]
    Name                tail
    Tag                 docker.*
    Path                /var/lib/docker/containers/*/*.log
    Parser              docker
    DB                  /fluent-bit/state/flb_container.db
    Mem_Buf_Limit       5MB
    Skip_Long_Lines     On
    Refresh_Interval    10

# Filter: Add metadata
[FILTER]
    Name                parser
    Match               docker.*
    Key_Name            log
    Parser              docker
    Reserve_Data        On

# Filter: Add host/container metadata
[FILTER]
    Name                modify
    Match               docker.*
    Add                 host 192.168.50.10
    Add                 environment production

# Output: Send to Splunk HEC
[OUTPUT]
    Name                splunk
    Match               docker.*
    Host                ${SPLUNK_HEC_URL}
    Port                443
    TLS                 On
    TLS.Verify_Off      On
    SPLUNK_Token        ${SPLUNK_HEC_TOKEN}
    SPLUNK_Index        ${SPLUNK_INDEX}
    SPLUNK_Source       docker
    SPLUNK_SourceType   ${SPLUNK_SOURCE_TYPE}
    SPLUNK_hec_Raw      Off
    Format              json
    Retry_Limit         5
```

Create `/home/mkadrlik/docker/fluent-bit/parsers.conf`:

```ini
[PARSER]
    Name                docker
    Format              json
    Time_Key            time
    Time_Format         %Y-%m-%dT%H:%M:%S.%L

[PARSER]
    Name                lemonade
    Format              regex
    Regex               ^(?<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \[(?<level>[A-Za-z]+)\] \((?<component>[^)]+)\) (?<message>.*)$
    Time_Key            time
    Time_Format         %Y-%m-%d %H:%M:%S.%L
```

---

## 3. Environment Variables

Create `/home/mkadrlik/docker/fluent-bit/.env`:

```env
# Splunk HEC Configuration
SPLUNK_HEC_URL=https://your-splunk-instance.com
SPLUNK_HEC_TOKEN=your-hec-token-here
SPLUNK_INDEX=main
SPLUNK_SOURCE_TYPE=docker_json
```

---

## 4. Splunk Dashboard Queries

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

---

## 5. Startup

```bash
cd /home/mkadrlik/docker/fluent-bit
docker compose up -d
docker logs -f fluent-bit
```

---

## 6. Log Rotation Cleanup

Add to crontab on NAS:
```cron
# Clean old Docker logs weekly
0 3 * * 0 find /var/lib/docker/containers -name "*.log" -mtime +7 -delete
```

---

## 7. Alternative: Direct Splunk Universal Forwarder

If Fluent Bit is too complex, use Splunk UF directly:

```bash
# Install Splunk UF on NAS
sudo rpm -ivh splunkforwarder-*.rpm

# Configure inputs
sudo /opt/splunkforwarder/bin/splunk add monitor /var/lib/docker/containers -index docker

# Configure outputs
sudo /opt/splunkforwarder/bin/splunk add forward-server your-splunk:9997

# Start
sudo /opt/splunkforwarder/bin/splunk start
```
