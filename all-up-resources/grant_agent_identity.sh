#!/usr/bin/env bash
# Give an agent's own identity the Foundry User role on the project. Every agent
# that calls the caldova-ops toolbox needs it, and the Copilot harness needs it to
# return generated files. Run once per agent after it first exists.
#
# People who only call an agent don't use this script: give them the Foundry Agent Consumer role instead.
#
# Usage: ./grant_agent_identity.sh <agent-name>
# Needs: az login, and permission to create role assignments at project scope.
set -euo pipefail
AGENT_NAME="${1:?agent name, e.g. caldova-ops-investigator}"

# Settings come from the repo-root .env (no azd project exists at the root any more).
ROOT_ENV="$(cd "$(dirname "$0")/.." && pwd)/.env"
if [ -f "$ROOT_ENV" ]; then set -a; . "$ROOT_ENV"; set +a; fi

ENDPOINT="${AZURE_AI_PROJECT_ENDPOINT:-$(azd env get-value AZURE_AI_PROJECT_ENDPOINT)}"
PROJECT_ID="${AZURE_AI_PROJECT_ID:-$(azd env get-value AZURE_AI_PROJECT_ID)}"
FOUNDRY_USER_ROLE="53ca6127-db72-4b80-b1b0-d745d6d5456d"   # Foundry User (role definition ID)

PRINCIPAL_ID="$(az rest --method GET \
  --url "$ENDPOINT/agents/$AGENT_NAME?api-version=v1" \
  --resource "https://ai.azure.com" \
  --query "instance_identity.principal_id" --output tsv)"

az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "$FOUNDRY_USER_ROLE" \
  --scope "$PROJECT_ID" --output none

echo "Granted Foundry User to $AGENT_NAME's identity. Allow up to five minutes, then start a new conversation."
