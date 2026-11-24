# Setup

How to deploy the Caldova agents to your own Foundry project. Do this once per project. Everything runs on synthetic data, and the offline tests need no Azure account.

## 0. What you need

| Need | Detail |
|---|---|
| Foundry project | New Foundry experience, in a region that supports **both** the Copilot harness and hosted agents. Check *Copilot harness limits and availability* and the hosted-agent region list. (Harness errors have been seen in Canada Central.) |
| Model | A deployment that supports reasoning and tool calling and is available to prompt agents in that region (`gpt-5.4-mini` also worked). This repo uses `gpt-6.1-terra` for demos 1 and 3 and `gpt-6.1-sol` for demo 2 (both agents, so the before/after comparison is fair). Bring-your-own model isn't supported with the harness. |
| Your roles | Foundry Project Manager (connections, toolbox, hosted agent), Foundry User, and permission to create role assignments at project scope (for agent identities). |
| CLI | `azd` 1.37.0 or later; `azd ext install microsoft.foundry` (agents, connections, toolboxes, skills, routines; uninstall older single extensions first); `azure.ai.agents` 1.0.0-beta.22 or later. Azure CLI with `az extension add -n containerapp`. |
| Python | 3.13 and `uv` (hosted agent); `pip install "azure-ai-projects>=2.9.0" azure-identity` for `all-up-resources/ask.py`. |
| Canvas | GitHub Copilot app, **Customize > Plugin > microsoft-foundry > Install** (plugin 1.0.18 or later; open with `/open-foundry-canvas`). A Canvas build that includes the prompt (harness) path and the template gallery. |

## 1. Point azd at your project

Each agent folder has its own `azure.yaml`, so azd looks for its environment in that folder, not at the repo root. For a new setup, run the commands below inside one agent folder (for example `demo2-equip-harness/agents/caldova-ops-investigator`):

```bash
azd env new caldova-demo
azd env set AZURE_AI_PROJECT_ENDPOINT "https://<account>.services.ai.azure.com/api/projects/<project>"
azd env set AZURE_AI_PROJECT_ID "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>"
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME "gpt-6.1-sol"   # demo 2; use gpt-6.1-terra in the demo 1 and demo 3 folders
```

Then copy that folder's `.azure/` to the repo root (`cp -R .azure ../../../`) and spread it to the other agent folders with the helper (an existing environment such as `my-foundry-env` already at the root only needs the helper):

```bash
./all-up-resources/link_azd_env.sh    # copies the root .azure/<env> into each agent folder; --force overwrites
```

Then run `azd` commands from inside the agent folder. Root `.env` holds the same values for `all-up-resources/ask.py` and the grant script.

If the first deploy prompts for other values (subscription, location, tenant), answer them; azd saves them in the environment. Keep `.azure/` out of source control (`.gitignore` already does).

## 2. Deploy the caldova-ops MCP server

```bash
az login
RESOURCE_GROUP=<rg> LOCATION=<region> ./all-up-resources/caldova-ops-mcp/deploy.sh
curl https://<fqdn>/healthz        # {"status": "ok"}
```

The script vendors the shared package, deploys to Azure Container Apps, stores a random key as a Container Apps secret, and writes `CALDOVA_OPS_MCP_URL` and `CALDOVA_OPS_MCP_KEY` into the azd environment. The key is never printed. Requests without it get HTTP 401.

## 3. Lock the hosted agent's dependencies

```bash
cd demo3-run-hosted/src/caldova-ops-runtime && uv lock && cd -
```

## 4. Deploy everything

```bash
export AZD_ALPHA_ENABLE_AGENTS_MANAGED_HARNESS=true     # every new shell
python -m unittest discover -s all-up-resources/tests                     # 61 offline tests; all must pass
# run in each agent folder (it has its own azure.yaml)
azd deploy --all --no-prompt
azd ai agent show caldova-ops-investigator --output json   # expect kind: prompt and harness.type: microsoft_copilot_preview
```

## 5. Grant each agent identity Foundry User on the project

Needed to call the toolbox (all three), return generated files (harness) and use the state store (hosted).

```bash
for agent in caldova-ops-advisor-hosted caldova-ops-investigator caldova-ops-runtime; do
  ./all-up-resources/grant_agent_identity.sh "$agent"
done
```

Wait about five minutes, then start new conversations. For the hosted agent, redeploy (`azd deploy caldova-ops-runtime`) if it was invoked before the grant, so it picks up a fresh token.

## 6. Smoke test each agent

```bash
python all-up-resources/ask.py --agent caldova-ops-advisor-hosted --show-steps \
  "We're short about 1,500 units a week for six weeks. Which supplier and which routes should we use, and what needs approval?"

python all-up-resources/ask.py --agent caldova-ops-investigator --show-steps --download \
  --attach all-up-resources/inputs/aller-demand-plan.csv \
  "Build the evidence package for Thursday's operations review from this demand plan."

azd ai routine dispatch caldova-morning-sweep
python all-up-resources/ask.py --agent caldova-ops-runtime --show-steps \
  "What did this morning's sweep file for DISRUPT-001, and what is waiting on whom?"
```

Compare with: `demo1-build-canvas/idea-prompt.md` (section 3), `demo2-equip-harness/golden/out/`, and "Expected results" in `demo3-run-hosted/README.md`. Save a screenshot of each good answer and its trace.

## 7. Known gotchas

Points that depend on preview features and your tenant. Check them if something doesn't behave.

| Item | Why it matters | Check with |
|---|---|---|
| `toolboxes:` on a plain prompt agent (`caldova-ops-advisor-prompt`) | azd rejects `toolboxes:` without a harness. The plain prompt agent declares the MCP tool directly with `project_connection_id` (the `connection:` key deploys but fails at run time with HTTP 400). Already done in `azure.yaml` | `azd deploy caldova-ops-advisor-prompt` |
| Model TPM for the harness demo | The harness sends many tokens; at 50K tokens/min a run stopped with `rate_limit_exceeded`. `gpt-6.1-sol` (capacity 2182) is the demo 2 model and `gpt-6.1-terra` (150) runs demos 1 and 3; `gpt-5.4-mini` and `gpt-5.4` remain as spares | Foundry portal, Models + endpoints |
| Routine dispatch | `azd ai routine dispatch caldova-morning-sweep` returned, but `azd ai routine run list` showed no runs in testing; the case was filed by sending the routine's input to the agent. Re-check before relying on it | `azd ai routine run list caldova-morning-sweep` |
| `ask.py` against the hosted agent | `get_openai_client(agent_name=...)` is documented for prompt and harness agents. If it fails for the hosted agent, use `azd ai agent invoke caldova-ops-runtime "..."` | Smoke test |
| Connection key header | The `CustomKeys` key name `x-caldova-key` should arrive as a header at the MCP server; a 401 in the server logs means it didn't | `az containerapp logs show` |
| State store in the hosted runtime | `azure.ai.agentserver.core.storage.FoundryStateStore` (Learn, 29 Oct 2026, preview). If it's missing, results say `"storage": "session file ($HOME)"` and cross-session reads won't work | Smoke test step 6 |
| `FoundryToolbox` import | Beta package; `main.py` tries both documented import paths | `azd ai agent run caldova-ops-runtime` |
| Demo 1 is a hosted agent | Guardrail editing in Canvas is hosted-only, which is why demo 1 is hosted. Create the `caldova-default` guardrail (RAI policy) in your project and set `raiPolicyName` in demo 1's `azure.yaml` to its resource ID. The agent you create live needs its own name (e.g. `caldova-ops-advisor-live`), because azd-managed agents are read-only in Canvas. The deployed definition carries `caldova-default` in `rai_config` | Try the Canvas path once |
| Harness invocation | Harness agents must be called through the agent endpoint (project-level Responses gives HTTP 400); `ask.py` does this | Smoke test |
| Demo 3 production polish | Application Insights and trace access connected before the first remote call; each agent has a stable endpoint and `version_selector` defaults to always-latest, so pin a version for production; callers who only invoke hold **Foundry Agent Consumer** | Portal / azd docs; role assignment test with a caller-only account |

Direct MCP tool for the advisor, if needed (replace its `toolboxes:` block):

```yaml
    tools:
      - type: mcp
        server_label: caldova_ops
        server_url: ${CALDOVA_OPS_MCP_URL}
        project_connection_id: caldova-ops-conn
        require_approval: never
```

## Cost and cleanup

- Model inference and Container Apps are billed while used; hosted agents bill CPU and memory for active sessions. The routine deploys disabled.
- Never run `azd down` against a shared project. Remove only what this repo created:

```bash
azd ai routine delete caldova-morning-sweep
# delete the three caldova-ops-* agents, the caldova-evidence-package skill,
# the caldova-ops toolbox and the caldova-ops-conn connection in the Foundry portal
az containerapp delete --name caldova-ops-mcp --resource-group <rg>
```
