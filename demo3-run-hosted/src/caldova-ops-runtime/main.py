# Caldova Ops Runtime: a Microsoft Agent Framework agent hosted in Foundry Agent Service
# (Responses protocol). Same evidence tools as the prompt and harness agents (the
# caldova-ops toolbox), plus code Caldova owns: a planning tool, a policy gate on the
# only write path, and a case file in the Foundry durable state store.
import asyncio
import json
import os
from typing import Annotated

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from pydantic import BaseModel, Field

import runtime

try:  # FoundryToolbox ships in agent-framework-foundry-hosting (beta); its import path has moved once.
    from agent_framework_foundry_hosting import FoundryToolbox
except ImportError:  # pragma: no cover - depends on the installed package version
    from agent_framework.foundry import FoundryToolbox


class WeekAllocation(BaseModel):
    week: int = Field(description="Week number in the disruption window, 1-6.")
    supplier: str = Field(description="Supplier name from CAP-001, for example Aster Ridge.")
    units: int = Field(description="Units this supplier makes that week.")
    routes: dict[str, int] = Field(description="Units per route that week, for example {'Cedar': 600, 'Birch': 500}.")


def _plain(item):
    return item.model_dump() if isinstance(item, BaseModel) else dict(item)


def build_tools(store, include_local_evidence: bool):
    @tool(approval_mode="never_require")
    def plan_disruption_response(
        demand_plan_csv: Annotated[str, Field(description="Optional demand plan CSV text; empty uses the current plan.")] = "",
    ) -> str:
        """Compute the week-by-week supplier and route plan for DISRUPT-001 with Caldova's planning code (read-only)."""
        try:
            return json.dumps(runtime.plan_disruption_response(demand_plan_csv))
        except (runtime.PlanningError, ValueError, KeyError) as exc:
            return json.dumps({"error": f"Demand plan could not be read: {exc}. Send CSV text with columns "
                                        "week, week_start, forecast_units, internal_capacity_units, or leave it empty."})

    @tool(approval_mode="never_require")
    async def submit_recommendation(
        case_id: Annotated[str, Field(description="Case ID, for example CASE-DISRUPT-001.")],
        weeks: Annotated[list[WeekAllocation], Field(description="One entry per supplier per week.")],
        cited_sources: Annotated[list[str], Field(description="Source IDs the recommendation relies on.")],
        rationale: Annotated[str, Field(description="Plain-text reasoning for the reviewers.")] = "",
    ) -> str:
        """The ONLY write path: check a recommendation against policy in code and record it for human approval."""
        result = await runtime.submit_recommendation(store, case_id, [_plain(w) for w in weeks], cited_sources, rationale)
        return json.dumps(result)

    @tool(approval_mode="never_require")
    async def get_case(case_id: Annotated[str, Field(description="Case ID, for example CASE-DISRUPT-001.")]) -> str:
        """Read a recorded case and its submission history (read-only)."""
        try:
            case = await store.get(case_id)
        except Exception as exc:  # report storage problems instead of failing the turn
            return json.dumps({"error": f"Case store unavailable: {exc}", "storage": store.kind})
        return json.dumps({"storage": store.kind, "case": case} if case
                          else {"error": f"No case {case_id} recorded yet.", "storage": store.kind})

    @tool(approval_mode="never_require")
    async def list_cases() -> str:
        """List recorded cases with their status (read-only)."""
        try:
            return json.dumps({"storage": store.kind, "cases": await store.list()})
        except Exception as exc:
            return json.dumps({"error": f"Case store unavailable: {exc}", "storage": store.kind})

    tools = [plan_disruption_response, submit_recommendation, get_case, list_cases]

    if include_local_evidence:
        # Used only when no toolbox is configured (for example `azd ai agent run` before the toolbox exists).
        @tool(approval_mode="never_require")
        def get_evidence(source_id: Annotated[str, Field(description="Source ID such as CAP-001 or DIST-POLICY.")]) -> str:
            """Read one Caldova evidence record by source ID (read-only)."""
            return json.dumps(runtime.get_evidence(source_id))

        @tool(approval_mode="never_require")
        def list_evidence_sources() -> str:
            """List Caldova evidence records: source ID, title and owner (read-only)."""
            return json.dumps(runtime.list_evidence())

        tools += [get_evidence, list_evidence_sources]
    return tools


def build_agent(credential=None):
    credential = credential or DefaultAzureCredential()
    store = runtime.case_store_from_env()
    use_toolbox = runtime.toolbox_configured()
    tools = build_tools(store, include_local_evidence=not use_toolbox)
    if use_toolbox:
        # Same governed caldova-ops tools the prompt and harness agents use, over one MCP endpoint.
        tools = [FoundryToolbox(credential), *tools]

    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        credential=credential,
    )
    return Agent(
        client=client,
        instructions=runtime.INSTRUCTIONS,
        tools=tools,
        # Conversation history is managed by the hosting platform.
        default_options={"store": False},
    )


async def main():
    load_dotenv()
    server = ResponsesHostServer(build_agent())
    await server.run_async()


if __name__ == "__main__":
    asyncio.run(main())
