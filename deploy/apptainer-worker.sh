#!/bin/bash
set -euo pipefail
umask 077

apptainer=${TRANSCRIBER_APPTAINER:-"$HOME/apptainer/bin/apptainer"}
image=${TRANSCRIBER_SIF:-"$HOME/containers/transcriber-sif_1.22.sif"}
cache="$HOME/.cache/transcriber-runtime"
mkdir -p "$cache/matplotlib"
chmod 700 "$cache" "$cache/matplotlib"
command=/usr/local/bin/transcriber-worker
if [[ ${1:-} == --ffmpeg ]]; then
    shift
    command=/usr/bin/ffmpeg
fi

exec "$apptainer" exec --userns --cleanenv \
    --bind "$HOME:$HOME" \
    --pwd /opt/transcriber/aau-whisper \
    --env "MPLCONFIGDIR=$cache/matplotlib" \
    --env "OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-4}" \
    "$image" "$command" "$@"