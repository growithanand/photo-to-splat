# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f AS uv
FROM ubuntu:24.04@sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl python3 tini libegl1 libgl1 libgomp1 libglib2.0-0t64 \
    libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_LINK_MODE=copy \
    PHOTOSPLAT_RUNTIME_ROOT=/opt/photosplat-tools \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

FROM base AS runtime
WORKDIR /opt/photosplat
RUN groupadd --gid 10001 photosplat && \
    useradd --uid 10001 --gid 10001 --create-home photosplat && \
    install -d -o 10001 -g 10001 /data /cache
ENV PATH=/opt/photosplat/.venv/bin:$PATH \
    PHOTOSPLAT_CONTAINER=1 PHOTOSPLAT_WORKSPACE=/data PHOTOSPLAT_DATA_ROOT=/data \
    XDG_CACHE_HOME=/cache TORCH_HOME=/cache/torch TORCH_EXTENSIONS_DIR=/cache/torch_extensions \
    HF_HOME=/cache/huggingface MPLCONFIGDIR=/cache/matplotlib CUDA_CACHE_PATH=/cache/cuda QT_QPA_PLATFORM=offscreen
EXPOSE 8765 7010
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)"
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["photosplat", "ui", "--no-browser"]

# Inherit this stage in the GPU image so its installed tools remain image layers.
FROM runtime AS tools
WORKDIR /tmp/provision
COPY src/photosplat/gpu/ ./gpu/
COPY src/photosplat/setup-runtime.sh src/photosplat/runtime.sh src/photosplat/native_lock.py ./
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_CACHE_DIR=/root/.cache/uv bash setup-runtime.sh && \
    rm -rf /opt/photosplat-tools/mamba /opt/photosplat-tools/micromamba.tar.bz2

# This lightweight target exercises container networking and persistence in CPU CI.
FROM runtime AS app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_CACHE_DIR=/root/.cache/uv uv sync --locked --no-dev --no-editable --python 3.11.18
USER 10001:10001

FROM tools AS gpu
WORKDIR /opt/photosplat
COPY --from=app /opt/python /opt/python
COPY --from=app /opt/photosplat /opt/photosplat
USER 10001:10001
LABEL org.opencontainers.image.source="https://github.com/growithanand/photo-to-splat" \
      org.opencontainers.image.description="Local Gaussian reconstruction studio with pinned NVIDIA GPU tools" \
      org.opencontainers.image.licenses="MIT"
ENV NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    TRITON_CACHE_DIR=/cache/triton TORCHINDUCTOR_CACHE_DIR=/cache/torch_inductor
