FROM ghcr.io/lemonade-sdk/lemonade-server:latest

# Install curl for healthcheck (belt-and-suspenders)
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create hip directory for custom llama-server binary
# (will be mounted from host via docker-compose volume)
RUN mkdir -p /opt/lemonade/llama/hip

# Copy and set entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
