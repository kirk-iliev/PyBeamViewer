#!/bin/sh
set -e

# First-start initialization: populate config volume on initial run.

if [ ! -f /app/config/config.json ]; then
    echo "entrypoint: config.json not found — copying default"
    cp /app/config.default/config.json /app/config/config.json
fi

mkdir -p /app/config/backgrounds

exec python -m beam_viewer "$@"
