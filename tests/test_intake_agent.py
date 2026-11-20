from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.events.event import Event
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from auditpilot.agent import AuditLeadAgent
from auditpilot.agent import audit_lead
from auditpilot.agent import root_agent
from auditpilot.agents import intake as intake_module
from auditpilot.agents.intake import build_intake_agent
from auditpilot.agents.intake import intake_agent

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class ScriptedModel(BaseLlm):
    """Test model that calls the real intake tools and echoes their results."""

    calls: int = 0

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        self.calls += 1
        tool_results: dict[str, dict[str, Any]] = {}
        for content in llm_request.contents:
            for part in content.parts or []:
                function_response = part.function_response
                if function_response is not None:
                    response = function_response.response
                    if "result" in response and isinstance(response["result"], dict):
                        response = response["result"]
                    tool_results[function_response.name] = response

        if "load_ledger" not in tool_results:
            parts = [types.Part(function_call=types.FunctionCall(name="load_ledger", args={}))]
        elif "check_trial_balance" not in tool_results:
            parts = [
                types.Part(
                    function_call=types.FunctionCall(
                        name="check_trial_balance", args={}
                    )
                )
            ]
        else:
            reasons = [
                reason
                for result in tool_results.values()
                for reason in result.get("reasons", [])
            ]
            profile = {
                "status": (
                    "PASSED"
                    if all(
                        result.get("status") == "PASSED"
                        for result in tool_results.values()
                    )
                    else "FAILED"
                ),
                "reasons": reasons,
                "tool_results": tool_results,
            }
            parts = [types.Part(text=json.dumps(profile))]

        yield LlmResponse(
            content=types.Content(role="model", parts=parts),
            turnComplete=True,
        )


class ProbeAgent(BaseAgent):
    """Test-only downstream agent used to verify the intake gate."""

    was_run: bool = False

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        del ctx
        self.was_run = True
        if False:
            yield Event()


def _copy_data(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__"))
    return destination


async def _run_intake(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[Any], dict[str, Any], ProbeAgent]:
    monkeypatch.setattr(intake_module, "DATA_DIR", data_dir)
    probe = ProbeAgent(name="downstream_probe")
    intake = build_intake_agent(model=ScriptedModel(model="test-scripted"))
    audit_lead = AuditLeadAgent(
        name="audit_lead_test",
        sub_agents=[intake, probe],
    )
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="auditpilot_test",
        user_id="test_user",
    )
    runner = Runner(
        agent=audit_lead,
        app_name="auditpilot_test",
        session_service=session_service,
    )
    events = [
        event
        async for event in runner.run_async(
            user_id="test_user",
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text="Validate the financial data.")],
            ),
        )
    ]
    saved_session = await session_service.get_session(
        app_name="auditpilot_test",
        user_id="test_user",
        session_id=session.id,
    )
    assert saved_session is not None
    return events, saved_session.state, probe


def _tool_calls(events: list[Any]) -> set[str]:
    return {
        part.function_call.name
        for event in events
        if event.content is not None
        for part in event.content.parts or []
        if part.function_call is not None
    }


def test_intake_agent_has_only_the_required_tools_and_output_key() -> None:
    assert isinstance(intake_agent, LlmAgent)
    assert intake_agent.name == "intake_agent"
    assert intake_agent.output_key == "data_profile"
    assert [tool.__name__ for tool in intake_agent.tools] == [
        "load_ledger",
        "check_trial_balance",
    ]
    assert audit_lead.sub_agents[0] is intake_agent
    assert root_agent is audit_lead


def test_intake_passes_valid_data_and_runs_downstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _copy_data(DATA_DIR, tmp_path / "valid")
    trial_balance = pd.read_csv(data_dir / "trial_balance.csv", dtype={"account_code": str})
    bank_row = trial_balance["account_code"] == "1010"
    trial_balance.loc[bank_row, "debit_inr"] -= 1
    trial_balance.to_csv(data_dir / "trial_balance.csv", index=False)

    events, state, probe = asyncio.run(_run_intake(data_dir, monkeypatch))

    assert _tool_calls(events) == {"load_ledger", "check_trial_balance"}
    profile = json.loads(state["data_profile"])
    assert profile["status"] == "PASSED"
    assert profile["tool_results"]["load_ledger"]["status"] == "PASSED"
    assert profile["tool_results"]["check_trial_balance"]["status"] == "PASSED"
    ledger_stats = profile["tool_results"]["load_ledger"]["stats"]
    assert ledger_stats["rows_loaded"] == 6_000
    assert ledger_stats["min_date"] >= "2025-04-01"
    assert ledger_stats["max_date"] <= "2026-03-31"
    assert profile["tool_results"]["check_trial_balance"]["stats"]["is_balanced"]
    assert probe.was_run


def test_intake_fails_missing_required_column_and_stops_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _copy_data(DATA_DIR, tmp_path / "missing_column")
    ledger = pd.read_csv(data_dir / "ledger.csv")
    ledger.drop(columns=["posted_by"]).to_csv(
        data_dir / "ledger.csv", index=False
    )

    events, state, probe = asyncio.run(_run_intake(data_dir, monkeypatch))

    assert _tool_calls(events) == {"load_ledger", "check_trial_balance"}
    profile = json.loads(state["data_profile"])
    assert profile["status"] == "FAILED"
    assert profile["reasons"]
    assert not probe.was_run
