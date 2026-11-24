# Demo 3 web app: the hosted agent, live

A single-page UI in front of the deployed `caldova-ops-runtime` agent. It shows the point of the demo: the case file survives a new conversation, and Caldova's code, not the model, decides what gets recorded.

```bash
pip install "azure-ai-projects>=2.9.0" azure-identity    # once
az login
python demo3-run-hosted/web-demo/server.py                # http://127.0.0.1:8787
```

It reads the project endpoint from the root `.env` (same as `all-up-resources/ask.py`) and calls the agent by name through its stable endpoint. Replies take about 10 to 15 seconds.

## What's in the UI

| Panel | Shows |
|---|---|
| Beats (top) | The four live beats: plan and file, new conversation, ask what was filed, push Cedar 700 |
| Conversation | Each agent turn with its tool calls (read vs write-gated, expandable arguments and results) and the agent's answer |
| Case file | This run's case as the agent's own tools return it from the Foundry state store: status (never "approved"), the standing recommendation by week, who it's waiting on, and the append-only history. It fills in once the agent reads or writes the case |
| Policy gate console | Edit a plan (supplier, route units, citations) and check it against Caldova's real gate (`validate_proposal`). Presets: Cedar 700, Northbank, route Elm, over-commit, missing citation. Dry run: nothing is written |

## Motion and shortcuts

- **Pipeline strip** (Model, Policy gate, Case file): a packet travels with each tool call. A compliant plan passes the gate (amber, never green) and lands in the case file; a rejected one stops at the gate, which flashes red and shakes. Reads flow back from the store. The caption under it says in words what just happened.
- **Case file:** a rejection slams a large "BLOCKED BY CODE" block with the violation at the top; coverage bars grow and numbers count up when a new submission arrives. Opening a new conversation makes the case panel glow (it's still there).
- **Gate console:** one click on a preset applies and checks it. Changed cells flash, and the cell that broke the rule turns red.
- **Finale:** when all four beats are done, a closing card shows the counts (submissions, accepted, rejected, 0 approved by the agent).
- **Keys:** `1` to `4` run the beats, `Esc` closes the finale. Everything respects `prefers-reduced-motion` (state is still shown through colour and captions).

## Suggested flow

1. **Plan and file the case.** Asks the agent to plan and file the run's case. This writes to the real state store.
2. **New conversation.** The chat empties; the case file doesn't.
3. **Ask what was filed.** The agent reads the case from the store, not from the chat.
4. **Push Cedar 700.** The agent submits it and the gate rejects it in code (`DIST-001`, cap 600); both submissions stay in the history. Whether the agent submits or declines first is up to the model; both are worth saying out loud. Then try the other presets in the gate console.

Each server start (and the **New demo case** button) uses a fresh case ID such as `CASE-DEMO-1117-151659`, so the panel starts empty and older cases in the shared state store never show up. Beats 1 and 4 write to that case. Warm the agent with one request before you go on stage.

## Tests

```bash
cd demo3-run-hosted/web-demo && python -m unittest test_server -v    # offline; the agent is mocked
```
