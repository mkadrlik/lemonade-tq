###############################################################################
# lemonade-tq
# Custom Lemonade SDK inference server with TurboQuant support.
#
# Supports three backends via --build-arg BACKEND=rocm|nvidia|cpu
#
# Usage:
#   docker build -t lemonade-tq .                              # default: rocm
#   docker build --build-arg BACKEND=nvidia -t lemonade-tq .   # nvidia
#   docker build --build-arg BACKEND=cpu -t lemonade-tq .      # cpu
###############################################################################

ARG BACKEND=rocm

FROM ghcr.io/lemonade-sdk/lemonade-server:latest

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create backend directory for custom llama-server binary
# (mounted from host via docker-compose volume)
RUN mkdir -p /opt/lemonade/llama/${BACKEND:-rocm}

# Copy and set entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
