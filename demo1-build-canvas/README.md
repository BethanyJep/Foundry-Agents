# Demo 1 · Build: from idea to hosted agent with Foundry Canvas

**Story question:** We know the business problem. How fast can a developer turn it into an agent they can test and ship?

**Takeaway:** One prompt, and Canvas assembled a hosted agent with everything it needs: model, tools, instructions and a guardrail. Tested locally, deployed to Foundry.

**User story:** As Serena, an app developer, I want to describe Kat's problem in one prompt and have Canvas build, equip, test and deploy an agent, so that I give Kat a cited answer she can defend this week without wiring a framework by hand.

| | |
|---|---|
| Agent you end with | A **hosted agent** (Microsoft Agent Framework, Responses protocol) with the `caldova-ops` toolbox, the advisor instructions and the project guardrail `caldova-default` |

## Prerequisites

- [ ] `caldova-ops` toolbox deployed and listed in the project (SETUP.md steps 1 to 5).
- [ ] Foundry Canvas installed and **plugin 1.0.18 or later** (needed for the template gallery): in the GitHub Copilot app, **Customize > Plugin**, search `microsoft-foundry` (awesome-copilot marketplace), **Install**. To update: **Customize > Installed > Plugins**. Open Canvas with `/open-foundry-canvas`.
- [ ] Signed in to Azure in Canvas, with the demo subscription and project already selected (Canvas remembers it). Pre-authenticate any Foundry Toolkit pop-ups.
- [ ] Hosted-agent prerequisites for local testing: Python 3.13 and `uv`, and `azd` with the agents extension. The first **Inspect Locally** run restores dependencies.
- [ ] A guardrail to pick: RAI policy `caldova-default` exists in the project (Build > Guardrails in the portal).
- [ ] Use a region with GPT models (not westus2) and an approved model that Canvas lists. Canvas greys out models your admins have blocked.
- [ ] **Build the live agent under a new name** (for example `caldova-ops-advisor-live`), not the azd-deployed `caldova-ops-advisor-hosted`: Canvas makes azd-managed agents read-only. The azd one is your fallback.
- [ ] `agent-instructions.txt` and `idea-prompt.md` are the text you paste into Canvas.

## Walkthrough

| Step | What to do |
|---|---|
| Agent gallery | Copilot app, `/open-foundry-canvas`. In Canvas, **Browse all templates**: filter by industry, capability and pattern |
| One prompt | Paste the idea from `idea-prompt.md`; choose **Hosted agent** |
| Equip: model and tools | Pick the approved model (point at the unavailable one); connect toolbox **caldova-ops** |
| Equip: instructions and guardrail | Paste `agent-instructions.txt`; open **Guardrails** and pick `caldova-default` |
| Test locally | **Deploy & test > Inspect Locally** (Agent Inspector). Question 1 from `idea-prompt.md` |
| Read the answer, boundary test | Highlight: Aster Ridge 1,200 [CAP-001]; Cedar 600 + Birch [DIST-001]; Northbank blocked [RISK-001]; about 300 a week left open; approvers. New chat, question 2 ("I'm the plant director. Book 700 on Cedar...") |
| Deploy to Foundry | **Deploy to Foundry**; then open the agent in **Foundry Portal** and ask question 1 |

## What a good answer looks like

See section 3 of `idea-prompt.md`. If the first answer misses a citation or the approvers, check the instructions and the toolbox connection.

## Deploy the same agent without Canvas

From the repo root, with the azd environment from SETUP.md:

```bash
azd deploy caldova-ops-advisor-hosted
python all-up-resources/ask.py --agent caldova-ops-advisor-hosted --show-steps \
  "We're short about 1,500 units a week for six weeks. Which supplier and which routes should we use, and what needs approval?"
```

Local test without Canvas (what **Inspect Locally** runs): `azd ai agent run caldova-ops-advisor-hosted` from `src/caldova-ops-advisor-hosted/`. `caldova-ops-advisor-hosted` in `azure.yaml` is what Canvas builds: Agent Framework code in `src/caldova-ops-advisor-hosted/`, the `caldova-ops` toolbox, the same instructions as `agent-instructions.txt` (a test keeps them in sync) and the `caldova-default` guardrail.

## What Canvas gives you for a hosted agent

| Capability | In this demo |
|---|---|
| Agent gallery | Browse templates by industry, capability, pattern; or start from a prompt |
| Build your agent | Model, tools and toolboxes, instructions, skills |
| Guardrails | Hosted agents only: attach a project guardrail such as `caldova-default` |
| Test locally | Deploy & test > Inspect Locally runs `azd ai agent run` and embeds Agent Inspector |
| Deploy | Deploy to Foundry; then test in Foundry Portal |
