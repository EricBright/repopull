#!/usr/bin/env bash
# Convenience entry point: run the real launcher from the project root.
set -euo pipefail

here="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)"
exec "$here/bin/repopull" "$@"
