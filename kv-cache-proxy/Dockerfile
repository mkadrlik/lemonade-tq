FROM rocm/dev-ubuntu-24.04:7.2.3-complete

# Python and build deps for llama-cpp-python with ROCm
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    cmake git build-essential curl \
    autoconf automake libtool pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Create venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ROCm build env
ENV LLAMA_CPP_ROCM=1 \
    HSA_OVERRIDE_GFX_VERSION=11.0.0 \
    ROCM_PATH=/opt/rocm \
    HIP_PATH=/opt/rocm \
    LD_LIBRARY_PATH=/opt/rocm/lib

WORKDIR /app

# Install non-llama deps
COPY requirements.txt .
RUN pip install --no-cache-dir aiohttp pydantic uvicorn

# Build llama-cpp-python with ROCm from source
RUN CMAKE_ARGS="-DGGML_HIP=ON -DGGML_HIP_BLAS=ON" \
    pip install --no-cache-dir --no-binary llama-cpp-python "llama-cpp-python>=0.3.0"

# Copy application code
COPY checkpoint.py extractor.py resume.py server.py ./

RUN mkdir -p /tmp/kv-cache-checkpoints

EXPOSE 13307

CMD ["python3", "server.py", "--model", "/models/Qwen3.6-27B-UD-Q4_K_XL.gguf", "--port", "13307", "--host", "0.0.0.0", "--n-gpu-layers", "-1"]
