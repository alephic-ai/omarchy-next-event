#!/usr/bin/env bash

set -euo pipefail

PLUGIN_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$PLUGIN_DIR/next-event"

if [[ -x "$PLUGIN_DIR/.venv/bin/python" ]]; then
    exec "$PLUGIN_DIR/.venv/bin/python" "$SCRIPT" "$@"
fi

if command -v uv >/dev/null 2>&1; then
    exec uv run --project "$PLUGIN_DIR" --no-sync python "$SCRIPT" "$@"
fi

exec python3 "$SCRIPT" "$@"

