FROM rocm/dev-ubuntu-24.04:7.2.3-complete AS base

# Python and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Create venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY checkpoint.py extractor.py resume.py server.py ./

# Checkpoint storage
RUN mkdir -p /tmp/kv-cache-checkpoints

EXPOSE 13307

CMD ["python", "server.py", "--port", "13307", "--n-gpu-layers", "9999"]
