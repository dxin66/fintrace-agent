#!/bin/zsh
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
"$project_root/.venv/bin/python" "$project_root/scripts/runtime.py" stop
