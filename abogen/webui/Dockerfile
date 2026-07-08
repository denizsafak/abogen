FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  VIRTUAL_ENV=/opt/venv \
  PATH=/opt/venv/bin:$PATH

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu126
ARG TORCH_VERSION=
ARG USE_GPU=true

RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    ffmpeg \
    libsndfile1 \
    libgl1 \
    libglib2.0-0 \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv "$VIRTUAL_ENV"

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install uv \
  && if [ -n "$TORCH_VERSION" ]; then \
       uv pip install --system torch=="$TORCH_VERSION" torchvision=="$TORCH_VERSION" torchaudio=="$TORCH_VERSION" --index-url "$TORCH_INDEX_URL"; \
     else \
       uv pip install --system torch torchvision torchaudio --index-url "$TORCH_INDEX_URL"; \
     fi \
  && uv pip install --system . \
    https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl \
  && uv pip install --system "mutagen>=1.47.0"

COPY abogen ./abogen

# Install onnxruntime-gpu for CUDA acceleration (supertonic uses ONNX Runtime)
# Set USE_GPU=false to skip this for CPU-only deployments
RUN if [ "$USE_GPU" = "true" ]; then \
      uv pip install --system onnxruntime-gpu; \
    fi

ENV ABOGEN_HOST=0.0.0.0 \
  ABOGEN_PORT=8808

EXPOSE 8808

VOLUME ["/data"]

ENV ABOGEN_UPLOAD_ROOT=/data/uploads \
  ABOGEN_OUTPUT_ROOT=/data/outputs \
  ABOGEN_TEMP_DIR=/data/cache \
  ABOGEN_VOICE_CACHE_DIR=/data/voice-cache \
  HF_HOME=/data/huggingface \
  HUGGINGFACE_HUB_CACHE=/data/huggingface/hub

# Copy and setup entrypoint script
COPY abogen/webui/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create non-root user and setup permissions
RUN useradd -m -u 1000 abogen \
    && mkdir -p /data/uploads /data/outputs /data/cache /data/voice-cache /data/huggingface \
    && chown -R abogen:abogen /data /app

USER abogen

ENTRYPOINT ["/entrypoint.sh"]
CMD ["abogen-web"]
