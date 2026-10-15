#!/bin/bash
set -euo pipefail
umask 077
project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python=${TRANSCRIBER_WEB_PYTHON:-"$project_root/django-project/.venv/bin/python"}
if [[ ! -f "$project_root/django-project/frontend/build/index.html" ]]; then
    printf 'Build the frontend with npm run build before initializing.\n' >&2
    exit 1
fi
cd "$project_root/django-project"
chmod 700 bin/python
mkdir -p public
for asset in transcriber.png manifest.webmanifest; do
    if [[ -f "frontend/build/$asset" ]]; then
        cp "frontend/build/$asset" "public/$asset"
    fi
done
"$python" manage.py migrate --noinput
"$python" manage.py collectstatic --noinput
"$python" manage.py check