#!/usr/bin/env bash

set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' "uv is required. Install it, then run this script again." >&2
    exit 1
fi

uv sync
printf '%s\n' "Calendar dependencies installed in .venv."

