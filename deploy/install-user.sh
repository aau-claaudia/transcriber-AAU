#!/bin/bash
set -euo pipefail
umask 077
project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python=${TRANSCRIBER_INSTALL_PYTHON:-python3.11}
requirements="$project_root/requirements-web.txt"
if [[ ${TRANSCRIBER_BUNDLED_SQLITE:-False} == True ]]; then
    requirements="$project_root/requirements-ondemand.txt"
fi
if [[ ! -d "$project_root/django-project/.venv" ]]; then
    "$python" -m venv "$project_root/django-project/.venv"
fi
"$project_root/django-project/.venv/bin/python" -m pip install -r "$requirements"
bash "$project_root/deploy/initialize.sh"