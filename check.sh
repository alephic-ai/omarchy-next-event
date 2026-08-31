#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OMARCHY_ROOT="${OMARCHY_PATH:-/usr/share/omarchy}"
OMARCHY_SHELL="$OMARCHY_ROOT/shell"
PLUGIN_VALIDATOR="$OMARCHY_ROOT/bin/omarchy-plugin-validate"

require_command() {
    local command_name="$1"
    local install_hint="$2"

    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Missing required command: %s\n%s\n' "$command_name" "$install_hint" >&2
        exit 1
    fi
}

require_command jq "Install it with: omarchy pkg add jq"
require_command git "Install it with: omarchy pkg add git"
require_command shellcheck "Install it with: omarchy pkg add shellcheck"
require_command tar "Install it with: omarchy pkg add tar"
require_command uv "Install uv, then run this script again."

if command -v qmllint >/dev/null 2>&1; then
    QMLLINT="$(command -v qmllint)"
elif [[ -x /usr/lib/qt6/bin/qmllint ]]; then
    QMLLINT="/usr/lib/qt6/bin/qmllint"
else
    printf '%s\n' "Missing qmllint. Install it with: omarchy pkg add qt6-declarative" >&2
    exit 1
fi

if [[ ! -f "$PLUGIN_VALIDATOR" ]]; then
    printf 'Omarchy plugin validator not found: %s\n' "$PLUGIN_VALIDATOR" >&2
    exit 1
fi

for module in Commons Ui; do
    if [[ ! -d "$OMARCHY_SHELL/$module" ]]; then
        printf 'Omarchy QML module not found: %s\n' "$OMARCHY_SHELL/$module" >&2
        exit 1
    fi
done

cd "$REPO_DIR"

TEMP_ROOT="$(mktemp -d)"

cleanup() {
    rm -rf -- "$TEMP_ROOT"
}
trap cleanup EXIT

PLUGIN_SNAPSHOT="$TEMP_ROOT/plugin"
mkdir -p "$PLUGIN_SNAPSHOT"
git ls-files --cached --others --exclude-standard -z \
    | while IFS= read -r -d '' path; do
        if [[ -e "$path" || -L "$path" ]]; then
            printf '%s\0' "$path"
        fi
    done \
    | tar --create --file=- --null --verbatim-files-from --files-from=- \
    | tar --extract --file=- --directory="$PLUGIN_SNAPSHOT"

bash "$PLUGIN_VALIDATOR" "$PLUGIN_SNAPSHOT"
uv run --locked python -m unittest -v
shellcheck check.sh runner.sh setup.sh

QML_IMPORT_ROOT="$TEMP_ROOT/qml"
mkdir -p "$QML_IMPORT_ROOT"
ln -s "$OMARCHY_SHELL" "$QML_IMPORT_ROOT/qs"

# Omarchy's host object exposes dynamic bar properties, and Quickshell's QML
# metadata does not describe QProcess::ExitStatus. Neither can be resolved by qmllint.
"$QMLLINT" \
    --max-warnings 0 \
    --missing-property disable \
    --signal-handler-parameters disable \
    -I "$QML_IMPORT_ROOT" \
    BarWidget.qml
