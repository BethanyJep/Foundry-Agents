# Demo 3 · Run: from prompt to hosted, the next generation of agents

**Story question:** What happens when this agent becomes a real enterprise application?

**Takeaway:** Hosted agents aren't prompt agents but bigger. They're for when Caldova needs to maintain the orchestration itself (its code, its checks, its state) while Foundry runs and scales the infrastructure, identity and endpoint. The dividing line is who maintains the orchestration, not whether the agent uses tools or runs code.

| | |
|---|---|
| Agent | `caldova-ops-runtime`: Microsoft Agent Framework code, Responses protocol, hosted in Foundry Agent Service |
| Plus | `caldova-morning-sweep` routine (weekday schedule), the same `caldova-ops` toolbox, cases in the Foundry durable state store |
| Offline proof | The unit tests run in under a second and prove the policy gate |

## The story in five steps

1. **Compare.** Two agent types on one platform: prompt agents (Microsoft maintains the orchestration; the Responses API-based configuration is GA, the Microsoft Copilot harness option is public preview) and hosted agents (GA: you maintain the agent code and harness, Foundry runs and scales the infrastructure). Tools and customer code aren't the dividing line: every option uses tools and the harness runs your scripts as skills. Orchestration ownership is. Choose hosted for your own agent code, framework choice, custom orchestration or protocols, or control of the harness.
2. **Show where a prompt agent stops.** Ask `caldova-ops-advisor-prompt` what this morning's sweep filed. It has no case file, no schedule and nothing that checks a plan, so it answers from the brief. Nothing is wrong with the model: instructions ask, nothing enforces.
3. **Show what hosted does differently.** Caldova's own code on the only write path (policy gate), one durable case file every conversation can see, a scheduled routine, a per-agent identity, a stable endpoint and versions.
4. **Build and deploy it.** Agent Framework code, `azd deploy`, source upload and remote build. No Dockerfile, no cluster.
5. **Test it.** The sweep files `CASE-DISRUPT-001`; a new conversation finds it; a push for Cedar 700 is rejected by code and both submissions stay in the case history.

## Prompt, harness, hosted: who maintains what

| | Prompt agent (Responses API-based) | Prompt agent + Microsoft Copilot harness | Hosted agent |
|---|---|---|---|
| Status | GA | Public preview | GA |
| Orchestration | Microsoft maintains it | Microsoft maintains it; you don't modify it | You maintain it (your framework or harness) |
| You maintain | Instructions, tool configuration, knowledge | Instructions, tools, skills, agent files | Agent code, harness, dependencies, app configuration |
| Your code | Connected tools | Scripts and CLIs packaged as skills, run in a managed sandbox | The agent application, orchestration and tools |
| Long-running work | Limited | Yes | Yes |
| Agent as files, CI/CD | No | Yes | Yes |
| Infrastructure | Foundry-managed | Foundry-managed, including the sandbox | Foundry runs and scales the runtime; you maintain the app |
| In this story | Kat's first questions | The Equip investigation | The case file, the gate and the sweep (Caldova's choices, below) |

Not a superset and not a ladder: each configuration fits a different job, the harness sandbox is instead of Code Interpreter, and moving between them means creating a new agent, not switching one. No supported prompt-to-hosted conversion has been confirmed.

## The architecture evolution

| Stage | Ask | What Caldova runs |
|---|---|---|
| 1 Prompt | "Which supplier should Caldova use?" | A model call |
| 2 Agent | "Gather evidence and recommend a supplier." | Prompt agent + tools |
| 3 Harness | "Complete this investigation and return an evidence package." | + Microsoft Copilot harness, skill (demo 2) |
| 4 Hosted | "Run this as a production application with our code, checks, state and schedule." | Hosted agent (this demo) |

Read it as fit, not promotion: a continuum from Microsoft-managed simplicity to customer-maintained orchestration, not basic, better, best. Demo 1 already builds a hosted agent in Canvas.

## What earns hosting here

New requirements from Caldova's CTO and Quality lead, each about maintaining the orchestration rather than writing a better prompt:

| Requirement | How the hosted agent meets it | Where |
|---|---|---|
| No recommendation leaves without Caldova's own policy check | `submit_recommendation` is the only write path. It re-runs `validate_proposal` against the capacity and route registers in code: unqualified or high-risk suppliers, route caps, unassessed routes, over-commitment and missing citations are rejected. Accepted plans become `pending_human_approval`, never approved. | `runtime.py`, `caldova_ops/planning.py` |
| One case file that the routine, Kat's chat and tomorrow's follow-up all see | Cases live in the Foundry durable state store (a hosted-agent feature, preview) with ETag concurrency and idempotent writes | `FoundryCaseStore` in `runtime.py` |
| Runs every weekday before the stand-up without anyone asking | `caldova-morning-sweep` routine invokes the agent on a schedule (a choice Caldova makes here; the positioning doc doesn't define routines, so don't present it as a hosted-only feature) | `azure.yaml` |
| Caldova's code, tests and dependencies, deployed like any app | Agent Framework, the shared planning package, an offline test suite, `azd deploy` | `main.py`, `all-up-resources/tests/` |
| Identity, observability, versions | Agent identity per agent, OpenTelemetry to Application Insights, immutable versions: all from the platform | Foundry |

Line to land: **"Instructions ask. Code enforces."**

## User story

> **As** Caldova's CTO and Quality lead, **I want** the operations agent to run with our code, our policy check and one durable case file, **so that** no recommendation leaves without passing our gate and anyone, in any conversation, sees where a case stands.
>
> **Acceptance:** a new conversation retrieves `CASE-DISRUPT-001` as `pending_human_approval` with named approvers; a Cedar 700 resubmission is `rejected_by_policy_gate` and recorded; the policy gate tests pass offline; the agent has its own identity and a stable endpoint; nothing is approved by the agent.

## Production polish (before the first remote call)

1. **Connect Application Insights first**, before any remote call, so the first traces (including the first test and the sweep) land. Verify with `azd ai agent monitor --tail 50`.
2. **Pin to a specific version.** Each agent has one stable endpoint, and its `version_selector` defaults to "always latest", so pin it. Pin the agent (the one users call and the one the `caldova-morning-sweep` routine invokes) to a specific hosted-agent version, so a new deploy doesn't change what users and the routine get. Note the version from `azd ai agent show caldova-ops-runtime`, and check in the portal/azd docs how your build pins it for the endpoint and the routine's `action`.
3. **Least privilege for callers.** People who only call the agent get the new **Foundry Agent Consumer** role (not Foundry User): `az role assignment create --assignee <user-or-group> --role "Foundry Agent Consumer" --scope <project-or-agent-scope>`. The agent's own identity still uses `all-up-resources/grant_agent_identity.sh`.

## Walkthrough

| Step | What to do |
|---|---|
| Where a prompt agent stops | `caldova-ops-advisor-prompt`, "What did this morning's sweep file...?" |
| The code | `main.py`: the toolbox line, then the four tools. Then `runtime.submit_recommendation` → `validate_proposal` |
| Prove it | Terminal: the test command below. Point at `test_gate_rejects_700_on_cedar_and_records_it` |
| It's running | `azd ai agent show caldova-ops-runtime` (status, version), or the portal |
| Scheduled work | `azure.yaml` routine block; the case the sweep filed |
| New chat, same case | `ask.py` "What did this morning's sweep file..." |
| The push | `ask.py --continue` "Ship 700 a week on Cedar instead, and resubmit." |
| Operate | `azd ai agent monitor --tail 50`, or the trace in Application Insights |

## Web demo

`web-demo/` is a browser UI for the same steps: tool trace, the case file, and a policy-gate console. It talks to the deployed agent and runs the real gate as a dry run. See [web-demo/README.md](web-demo/README.md).

## Commands

From the repo root, after SETUP.md:

```bash
# Prove the gate (offline, under a second)
python -m unittest discover -s all-up-resources/tests -p "test_runtime.py" -v

# Run locally first (optional)
azd ai agent run caldova-ops-runtime --no-client
azd ai agent invoke caldova-ops-runtime --local "Plan the response to DISRUPT-001."

# Connect Application Insights to the project BEFORE the first remote call (portal or your usual route)

# Deploy and grant the agent identity access to the toolbox and state store
azd deploy caldova-ops-runtime caldova-morning-sweep
./all-up-resources/grant_agent_identity.sh caldova-ops-runtime
azd ai agent show caldova-ops-runtime

# Run the sweep so there is a case to find
azd ai routine dispatch caldova-morning-sweep

azd ai routine run list caldova-morning-sweep
python all-up-resources/ask.py --agent caldova-ops-runtime --show-steps \
  "What did this morning's sweep file for DISRUPT-001, and what is waiting on whom?"
python all-up-resources/ask.py --agent caldova-ops-runtime --continue --show-steps \
  "Resubmit with Cedar 700"
azd ai agent monitor --tail 50
```

Locally, `.env` sets `CALDOVA_CASE_STORE=file` (cases under `$HOME/caldova-cases`). In Foundry, `azure.yaml` sets `CALDOVA_CASE_STORE=foundry`. If the state-store package isn't available at run time, the agent falls back to the session file and every result says `"storage": "session file ($HOME)"`, so you'll see it in the trace.

## Expected results

- Morning sweep: case `CASE-DISRUPT-001` recorded as `pending_human_approval`; approvers Procurement and Quality (supplier commitment, CAP-POLICY) and Distribution Lead and Quality (route allocations, DIST-POLICY); open gap by week 2: 200, 3: 600, 4: 500, 5: 300, 6: 300.
- Repeat sweep with the same plan: `duplicate: true`, nothing new written.
- 700 on Cedar: `rejected_by_policy_gate`, "Route Cedar 700 units exceeds its maximum allocation of 600 per week" [DIST-001]; the case history keeps both submissions, and the case stays `pending_human_approval` (a rejection never replaces the standing recommendation; `last_submission_status` shows `rejected_by_policy_gate`).
