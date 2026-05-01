# Multi-stage build to create the optimized Lemonade-TQ container

# Stage 1: Build llama.cpp with ROCm, NCCL, and TurboQuant
FROM rocm/dev-ubuntu-22.04 AS builder
RUN apt-get update && apt-get install -y \
    cmake \
    git \
    build-essential \
    libnccl-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /opt/llama.cpp
WORKDIR /opt/llama.cpp

# Build with Split Mode Graph (-sm graph) and TurboQuant (-ctk/ctv turbo)
RUN cmake -B build \
    -DGGML_HIP=ON \
    -DGGML_NCCL=ON \
    -DGGML_BLAS=ON \
    -DGGML_BLAS_VENDOR=OpenBLAS \
    -DGGML_NATIVE=OFF \
    -DGGML_AVX=OFF \
    -DGGML_AVX2=OFF \
    -DGGML_AVX512=OFF \
    -DGGML_F16C=OFF \
    -DGGML_FMA=OFF \
    -DCMAKE_CXX_COMPILER=/opt/rocm/llvm/bin/clang++ \
    -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang
RUN cmake --build build --config Release -j$(nproc)

# Stage 2: Runtime Environment
FROM rocm/dev-ubuntu-22.04
LABEL maintainer="mkadrlik"
LABEL description="Lemonade-TQ: Optimized Inference Server with Split Mode Graph & TurboQuant"

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libnccl2 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy optimized binaries from builder
COPY --from=builder /opt/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=builder /opt/llama.cpp/build/bin/llama-quantize /usr/local/bin/llama-quantize

# Install Lemonade (Inference Server)
RUN pip install --no-cache-dir lemonade-tq

# Set working directory
WORKDIR /data

# Expose ports
EXPOSE 13305

# Environment variables for Lemonade
ENV LEMONADE_MAX_LOADED_MODELS=4
ENV LEMONADE_CTX_SIZE=4096
ENV LEMONADE_BACKEND=llama.cpp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:13305/health || exit 1

# Default command
ENTRYPOINT ["lemonade"]
CMD ["--host", "0.0.0.0", "--port", "13305"]
