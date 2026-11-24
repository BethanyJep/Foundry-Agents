#!/usr/bin/env bash
# Deploy the caldova-ops MCP server to Azure Container Apps and store its URL
# and key in the active azd environment (never printed, never committed).
#
# Usage: RESOURCE_GROUP=<rg> LOCATION=<region> ./deploy.sh
# Needs: az login, the containerapp extension (az extension add -n containerapp),
#        and an azd environment selected at the repo root.
set -euo pipefail

: "${RESOURCE_GROUP:?Set RESOURCE_GROUP}"
: "${LOCATION:?Set LOCATION}"
APP_NAME="${APP_NAME:-caldova-ops-mcp}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

python3 "$ROOT/all-up-resources/sync_shared.py"   # vendor the canonical caldova_ops package

KEY="${CALDOVA_OPS_MCP_KEY:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"

az containerapp up \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --source "$HERE" \
  --ingress external \
  --target-port 8000

# Store the key as a Container Apps secret and reference it from the env var.
az containerapp secret set --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --secrets "mcp-key=$KEY" --output none
az containerapp update --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --set-env-vars "CALDOVA_OPS_MCP_KEY=secretref:mcp-key" --output none

FQDN="$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)"

# Each agent folder has its own azure.yaml, so set the values in every folder's azd environment.
find "$ROOT" -name azure.yaml -not -path '*/.venv/*' | while read -r yaml; do
  (cd "$(dirname "$yaml")" && azd env set CALDOVA_OPS_MCP_URL "https://$FQDN/mcp" \
                           && azd env set CALDOVA_OPS_MCP_KEY "$KEY")
done

echo "caldova-ops MCP server: https://$FQDN/mcp (key stored in the azd environment)"
echo "Health check: curl https://$FQDN/healthz"
