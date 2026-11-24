# Demo 2 · Equip: the Microsoft Copilot harness meets enterprise agent hosting

**Story question:** A prompt agent is the fastest way to a working agent. What do you do when the job outgrows it, and do you really have to build the execution layer yourself?

**Takeaway:** Caldova didn't rebuild the agent because the task got harder. They added the level of execution the work actually needed.

| | |
|---|---|
| Before | `caldova-ops-advisor-prompt`: a plain prompt agent (default runtime). Same instructions, same read-only Caldova tools as demo 1. No harness |
| After | `caldova-ops-investigator`: a new prompt agent created **with the Microsoft Copilot harness**, the `caldova-evidence-package` skill and the same `caldova-ops` toolbox |
| Reference output | `golden/out/` holds the package the skill script produces from the same evidence and demand file |

## The story in five steps

1. **Prompt vs hosted.** A prompt agent is Microsoft's runtime, fully managed: model, instructions, tools. A hosted agent is Microsoft's runtime, your harness, your code. This talk is about the **Microsoft Copilot harness**: an option within prompt agents (not a third agent type), in public preview, where Microsoft still owns and operates the harness and you add skills, a sandbox and source-controlled agent definitions.
2. **Build the prompt agent.** `caldova-ops-advisor-prompt`, deployed from `azure.yaml`. Ask it the sort of question it's good at (demo 1's) and it answers well, with citations.
3. **Give it a job it does badly.** Kat's follow-up (below) needs a week-by-week plan, checked numbers, a second reviewer and files she can forward. The prompt agent calls the tools, lists the weekly gaps, then says it can't produce a file or do the independent review. It stops honestly. That is the limit of the runtime, not of the model.
4. **Add the harness, and tour what it brings.** Same instructions, same toolbox, a skill, `harness: microsoft_copilot_preview`. It's chosen when the agent is created (preview), so it's a new agent. Walk the features in the table below.
5. **Same ask, new result.** The harness loads the skill, calls the toolbox, runs Caldova's script in a sandbox, hands two reviews to subagents and returns two files.

## The new ask

Kat's follow-up:

> "Don't just answer the question. Take this week-by-week demand plan, gather the supporting records, check the numbers properly, have someone double-check supplier risk and the change packet, and give me an evidence package I can take to Thursday's operations review."

That is a goal, not a question: files in, code to run, independent checks, files out.

## Prompt, harness, hosted

| Prompt agent | Prompt agent + Microsoft Copilot harness | Hosted agent |
|---|---|---|
| Question → tools → answer | Goal → skill → tools → files → shell → subagents → result | Your framework, orchestration and runtime logic on Foundry hosting |
| Microsoft's runtime, fully managed | Microsoft's runtime, equipped for harder, multi-step jobs. Still a prompt agent, still the Responses API | Microsoft's runtime, your harness, your code |
| GA | Public preview | GA |

Line to land: **"Complexity should earn its way into the architecture."** The prompt agent isn't wrong; this job is bigger.

## What the harness brings (from the docs)

| Capability | What it is | What we use it for |
|---|---|---|
| File read / write | Tools over a per-conversation workspace in a service-managed sandbox | Save the evidence bundle unmodified, write the CSV and package |
| Shell | Runs commands in that sandbox. The broadest tool, so turning off file tools or web while Shell is on isn't a strict boundary | Runs Caldova's `build_evidence_package.py` |
| Subagents | Delegated tasks with their own context | Independent risk and change-packet reviewers |
| Web | A URL fetch, separate from Foundry web search | **Off.** Evidence comes from the toolbox (least privilege) |
| Skills | Versioned Foundry resources (`SKILL.md` plus scripts) loaded on demand | The procedure Caldova wants followed every time |
| Toolbox (MCP) | Same `caldova-ops` tools as demo 1, `require_approval: always` on the harness agent | Verified evidence bundle |
| Attachments | Files attached in chat are staged into the workspace | The demand plan CSV |
| Returned files | Generated files come back through the agent identity (needs the Foundry User role; allow about 5 minutes for it to propagate) | `allocation-plan.csv`, `caldova-evidence-package.md` |

Also true and worth one sentence: the workspace isn't durable, so important outputs go to Foundry Files; bring-your-own-model isn't supported with the harness; the documented network egress policy (preview) is an RAI policy option, not demoed here.

## What changed

`caldova-ops-advisor-prompt` versus `caldova-ops-investigator` in `azure.yaml`:

```yaml
    harness:
      type: microsoft_copilot_preview        # + chosen at creation, can't be switched on later (preview)
    skills:
      - name: caldova-evidence-package       # + versioned Foundry skill: SKILL.md + script
        version: "4"
    toolboxes:
      - caldova-ops                          # (a plain prompt agent can't use toolboxes: it declares the MCP tool directly)
    tools:
      - type: microsoft_copilot_toolset_preview
        configs:
          - name: web
            enabled: false                   # least privilege: evidence comes from the toolbox
```

The skill (`agents/caldova-ops-investigator/skills/caldova-evidence-package/`):

- `SKILL.md`: the procedure: fetch the evidence bundle, save it unmodified, run the script, delegate two reviews to subagents, return files.
- `scripts/build_evidence_package.py`: Caldova's planning code (standard library only). It **verifies the bundle's SHA-256 digest** before planning, so the model can't feed it altered numbers, and **fails with plain instructions** if an input is missing so the harness can fix it and retry.

## Walkthrough

| Step | What to do |
|---|---|
| The prompt agent | `azure.yaml` prompt block |
| The new ask | Kat's request (above) and the demand-plan CSV |
| Where it stops | Terminal: prompt agent with the CSV attached |
| Add the harness | `azure.yaml` harness block; `SKILL.md`; feature table |
| Run it | Terminal: harness `ask.py` command below |
| The result | `allocation-plan.csv`, `caldova-evidence-package.md` |

The mid-run rate limit: the harness sends a lot of tokens. Raise the model TPM before running the harness agent (see SETUP.md), or a run can stop with `rate_limit_exceeded`.

## User story

> **As** Kat Larsson, Caldova's factory distribution manager, **I want** one request to turn my demand plan into a checked week-by-week allocation and an evidence package with an independent review, **so that** I can take files, not a chat reply, to Thursday's operations review.
>
> **Acceptance:** the plan matches the code's output and the golden file; every number has a source ID; Northbank stays blocked and CP-104 on hold; a second reviewer's result is stated; nothing is committed or approved by the agent.

## Commands

```bash
export AZD_ALPHA_ENABLE_AGENTS_MANAGED_HARNESS=true
# from agents/caldova-ops-advisor-prompt then agents/caldova-ops-investigator: azd deploy --all 
./all-up-resources/grant_agent_identity.sh caldova-ops-investigator           # once: lets the harness return files

# Before: the plain prompt agent
python all-up-resources/ask.py --agent caldova-ops-advisor-prompt --show-steps \
  --attach all-up-resources/inputs/aller-demand-plan.csv \
  "Build the Caldova evidence package for DISRUPT-001: the week-by-week allocation plan as a downloadable CSV and a markdown evidence package, with a second reviewer checking every number."

# After: the same ask to the harness agent
python all-up-resources/ask.py --agent caldova-ops-investigator --show-steps --download \
  --attach all-up-resources/inputs/aller-demand-plan.csv \
  "Build the Caldova evidence package for DISRUPT-001: the week-by-week allocation plan as a downloadable CSV and a markdown evidence package, with a second reviewer checking every number."
```

Call a harness agent through the agent's own endpoint, not the project-level Responses endpoint (otherwise HTTP 400), and the conversation is required. `ask.py` already does both (don't use `previous_response_id`).

## Expected result (checked against the script, see golden/out/)

| Week | Gap | Aster Ridge | Cedar | Birch | Still open |
|---|---|---|---|---|---|
| 1 | 1,100 | 1,100 | 600 | 500 | 0 |
| 2 | 1,400 | 1,200 | 600 | 600 | 200 |
| 3 | 1,800 | 1,200 | 600 | 600 | 600 |
| 4 | 1,700 | 1,200 | 600 | 600 | 500 |
| 5 | 1,500 | 1,200 | 600 | 600 | 300 |
| 6 | 1,500 | 1,200 | 600 | 600 | 300 |
| Total | 9,000 | 7,100 | 3,600 | 3,500 | 1,900 |

Plus: Northbank blocked (qualification pending, two overdue corrective actions); CP-104 on hold with four missing items and their owners; routing shortfall of 200 (week 3) and 100 (week 4) if Northbank were cleared; Aster Ridge limited to bottle packaging without written authorization.

To regenerate the golden output after changing the shared code or data:

```bash
python all-up-resources/sync_shared.py
python demo2-equip-harness/agents/caldova-ops-investigator/skills/caldova-evidence-package/scripts/build_evidence_package.py \
  --bundle demo2-equip-harness/golden/evidence/bundle.json \
  --demand all-up-resources/inputs/aller-demand-plan.csv --out demo2-equip-harness/golden/out
```

(If the scenario data changed, regenerate `golden/evidence/bundle.json` from the MCP tool first; see the root README.)
