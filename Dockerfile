###############################################################################
# lemonade-tq
# Custom Lemonade SDK inference server with TurboQuant support.
#
# Supports three backends: rocm, vulkan, cpu
# Backend selection is entirely runtime via LEMONADE_LLAMACPP_BACKEND env var
# and docker-compose volume mounts — no build args needed.
#
# Usage:
#   docker build -t lemonade-tq .              # single image, all backends
#   docker compose up -d                       # set LEMONADE_LLAMACPP_BACKEND in .env
###############################################################################

FROM ghcr.io/lemonade-sdk/lemonade-server:latest

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create backend directories for custom llama-server binaries
# (mounted from host via docker-compose volume)
# All three backends supported — no build arg needed.
RUN mkdir -p /opt/lemonade/llama/{rocm,vulkan,cpu}

# Copy and set entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
