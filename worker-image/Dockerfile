# syntax=docker/dockerfile:1.7

ARG UBUNTU_VERSION=24.04
ARG TRANSCRIBER_VERSION=1.22

FROM ubuntu:${UBUNTU_VERSION} AS build

ARG TRANSCRIBER_VERSION

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive
ENV TRANSCRIBER_ROOT=/opt/transcriber
ENV PATH=/opt/transcriber/venv/bin:$PATH
ENV HOME=/opt/transcriber/build-home
ENV HF_HOME=/opt/transcriber/model-cache/torch/pyannote
ENV HF_HUB_CACHE=/opt/transcriber/model-cache/torch/pyannote
ENV HUGGINGFACE_HUB_CACHE=/opt/transcriber/model-cache/torch/pyannote
ENV TORCH_HOME=/opt/transcriber/model-cache/torch
ENV WHISPER_MODEL_CACHE=/opt/transcriber/model-cache/whisper

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates git build-essential ffmpeg libsndfile1 libgomp1 \
      python3.12 python3.12-venv python3-pip \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p "$TRANSCRIBER_ROOT" "$HOME" "$HF_HUB_CACHE" "$TORCH_HOME" "$WHISPER_MODEL_CACHE"

RUN python3.12 -m venv "$TRANSCRIBER_ROOT/venv" \
 && "$TRANSCRIBER_ROOT/venv/bin/python" -m pip install --no-cache-dir --upgrade pip \
 && git clone --depth 1 --single-branch --recursive --shallow-submodules \
      -b "V${TRANSCRIBER_VERSION}" \
      https://github.com/aau-claaudia/transcriber.git \
      "$TRANSCRIBER_ROOT/aau-whisper" \
 && "$TRANSCRIBER_ROOT/venv/bin/python" -m pip install --no-cache-dir -e "$TRANSCRIBER_ROOT/aau-whisper" \
 && "$TRANSCRIBER_ROOT/venv/bin/python" -m pip install --no-cache-dir 'huggingface_hub[cli]' \
 && chmod -R a+rX "$TRANSCRIBER_ROOT/aau-whisper"

# Keep registry credentials out of image layers and build history.
RUN --mount=type=secret,id=hf_token,required=true \
    set -eu; \
    export HF_TOKEN="$(cat /run/secrets/hf_token)"; \
    hf download pyannote/speaker-diarization-community-1 --cache-dir "$HF_HUB_CACHE"; \
    "$TRANSCRIBER_ROOT/venv/bin/python" -c \
     "import os; from pyannote.audio import Pipeline; Pipeline.from_pretrained('pyannote/speaker-diarization-community-1', token=os.environ['HF_TOKEN'])"

# Preload Whisper weights into the image. The runtime launcher copies these to
# job-local writable storage before the host UID runs the worker.
RUN python -c "import whisper; whisper.load_model('base', None, '$WHISPER_MODEL_CACHE')" \
 && python -c "import whisper; whisper.load_model('small', None, '$WHISPER_MODEL_CACHE')" \
 && python -c "import whisper; whisper.load_model('medium', None, '$WHISPER_MODEL_CACHE')" \
 && python -c "import whisper; whisper.load_model('large-v3', None, '$WHISPER_MODEL_CACHE')" \
 && python -c "import whisper; whisper.load_model('large-v3-turbo', None, '$WHISPER_MODEL_CACHE')" \
 && chmod -R a+rX "$TRANSCRIBER_ROOT/model-cache" "$TRANSCRIBER_ROOT/aau-whisper"

FROM ubuntu:${UBUNTU_VERSION} AS final

ARG TRANSCRIBER_VERSION

LABEL software="Transcriber worker" \
     description="Transcriber worker for unprivileged Apptainer execution"

ENV DEBIAN_FRONTEND=noninteractive \
    TRANSCRIBER_ROOT=/opt/transcriber \
    TRANSCRIBER_IMAGE_MODEL_CACHE=/opt/transcriber/model-cache \
    TRANSCRIBER_MODEL_CACHE_VERSION=${TRANSCRIBER_VERSION} \
    TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=true

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates ffmpeg libsndfile1 libgomp1 python3.12 \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /opt/transcriber

COPY --from=build /opt/transcriber/venv /opt/transcriber/venv
COPY --from=build /opt/transcriber/aau-whisper /opt/transcriber/aau-whisper
COPY --from=build /opt/transcriber/model-cache /opt/transcriber/model-cache
COPY --chmod=0555 worker-image/worker-entrypoint.sh /usr/local/bin/transcriber-worker

ENV PATH=/opt/transcriber/venv/bin:$PATH
WORKDIR /opt/transcriber/aau-whisper

# Deliberately omit USER: Apptainer runs this image as the invoking Slurm UID.
# Image code and baked model weights are readable; only job-bound cache/work
# directories need to be writable by that UID.