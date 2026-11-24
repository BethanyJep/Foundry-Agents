#!/usr/bin/env bash
# Each agent folder has its own azure.yaml, so azd looks for its environment in <folder>/.azure.
# This copies the repo-root .azure/<env> into every agent folder that doesn't have it yet
# (add --force to overwrite), so `azd deploy` works from any agent folder.
#
# Usage: ./all-up-resources/link_azd_env.sh [--force]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FORCE="${1:-}"
ENV_NAME="$(python3 -c "import json,sys; print(json.load(open('$ROOT/.azure/config.json'))['defaultEnvironment'])")"

find "$ROOT" -name azure.yaml -not -path '*/.venv/*' -not -path '*/node_modules/*' | while read -r yaml; do
  dir="$(dirname "$yaml")"
  [ "$dir" = "$ROOT" ] && continue
  if [ -d "$dir/.azure/$ENV_NAME" ] && [ "$FORCE" != "--force" ]; then
    echo "skip   ${dir#$ROOT/} (already has .azure/$ENV_NAME)"; continue
  fi
  mkdir -p "$dir/.azure/$ENV_NAME"
  cp "$ROOT/.azure/$ENV_NAME/.env" "$dir/.azure/$ENV_NAME/.env"
  cp "$ROOT/.azure/$ENV_NAME/config.json" "$dir/.azure/$ENV_NAME/config.json" 2>/dev/null || true
  cp "$ROOT/.azure/config.json" "$dir/.azure/config.json"
  echo "linked ${dir#$ROOT/}"
done
