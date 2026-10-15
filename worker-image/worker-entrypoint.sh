#!/bin/bash
set -euo pipefail
umask 077

if [[ $# -eq 0 ]]; then
    echo 'Usage: transcriber-worker <transcriber arguments...>' >&2
    exit 2
fi

if [[ -z "${HOME:-}" || "$HOME" == '/' ]]; then
    echo 'Apptainer must provide the submitting host user HOME.' >&2
    exit 1
fi

torch_home=${TORCH_HOME:-"$HOME/.cache/torch"}
hf_cache=${HF_HUB_CACHE:-"$torch_home/pyannote"}
whisper_cache=${WHISPER_MODEL_CACHE:-"$HOME/.cache/whisper"}
cache_marker="$torch_home/.transcriber-model-cache-${TRANSCRIBER_MODEL_CACHE_VERSION:-unknown}"

mkdir -p "$torch_home" "$hf_cache" "$whisper_cache"
chmod 700 "$torch_home" "$hf_cache" "$whisper_cache"

if [[ ! -f "$cache_marker" ]]; then
    if [[ -d /opt/transcriber/model-cache/torch ]]; then
        cp -R /opt/transcriber/model-cache/torch/. "$torch_home/"
    fi
    if [[ -d /opt/transcriber/model-cache/whisper ]]; then
        cp -R /opt/transcriber/model-cache/whisper/. "$whisper_cache/"
    fi
    touch "$cache_marker"
fi

export TORCH_HOME="$torch_home"
export HF_HOME="$hf_cache"
export HF_HUB_CACHE="$hf_cache"
export HUGGINGFACE_HUB_CACHE="$hf_cache"
export TRANSFORMERS_CACHE="$hf_cache"
export PYANNOTE_CACHE_DIR="$hf_cache"
export WHISPER_MODEL_CACHE="$whisper_cache"

exec /opt/transcriber/venv/bin/python /opt/transcriber/aau-whisper/app.py "$@"