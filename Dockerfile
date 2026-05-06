###############################################################################
# lemonade-tq
# Custom Lemonade SDK inference server with TurboQuant support.
#
# Bakes in the TurboQuant-enabled llama-server from llama-cpp-rocm-tq.
# Backend selection is entirely runtime via LEMONADE_LLAMACPP_BACKEND env var.
###############################################################################

FROM ghcr.io/lemonade-sdk/lemonade-server:latest

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create backend directories
RUN mkdir -p /opt/lemonade/llama/{rocm,vulkan,cpu}

# Copy TurboQuant-enabled llama-server binary + shared libs from llama-cpp-rocm-tq image
COPY --from=llama-cpp-rocm-tq:fix-paths /usr/local/bin/llama-server /opt/lemonade/llama/rocm/llama-server
COPY --from=llama-cpp-rocm-tq:fix-paths /usr/local/lib/libggml* /opt/lemonade/llama/rocm/
COPY --from=llama-cpp-rocm-tq:fix-paths /usr/local/lib/libllama* /opt/lemonade/llama/rocm/
COPY --from=llama-cpp-rocm-tq:fix-paths /usr/local/lib/libmtmd* /opt/lemonade/llama/rocm/

# Set library path so llama-server can find its shared libs
ENV LD_LIBRARY_PATH=/opt/lemonade/llama/rocm:${LD_LIBRARY_PATH:-/opt/rocm/lib}

# Copy and set entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
