from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from auditpilot.agent import audit_lead
from auditpilot.agents import report as report_module
from auditpilot.agents.report import ReportActionResult
from auditpilot.agents.report import build_report_agent


class ReportToolModel(BaseLlm):
    """Test model that selects a tool only from the current user command."""

    waiting_for_tool_result: bool = False

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        if not self.waiting_for_tool_result:
            user_messages = [
                "\n".join(
                    part.text for part in content.parts or [] if part.text
                ).strip()
                for content in llm_request.contents
                if content.role == "user"
            ]
            latest_message = user_messages[-1].upper() if user_messages else ""
            self.waiting_for_tool_result = True
            if latest_message in {
                "APPROVE",
                "REQUEST CHANGES",
                "REJECT",
            }:
                parts = [
                    types.Part(
                        function_call=types.FunctionCall(
                            name="record_human_signoff",
                            args={"choice": latest_message},
                        )
                    )
                ]
            else:
                parts = [
                    types.Part(
                        function_call=types.FunctionCall(
                            name="generate_audit_memo", args={}
                        )
                    )
                ]
        else:
            self.waiting_for_tool_result = False
            result: dict[str, Any] | None = None
            for content in llm_request.contents:
                for part in content.parts or []:
                    function_response = part.function_response
                    if function_response is not None:
                        result = function_response.response
                        if (
                            "result" in result
                            and isinstance(result["result"], dict)
                        ):
                            result = result["result"]
            if result is None:
                raise AssertionError("Report tool response was not present")
            parts = [types.Part(text=json.dumps(result))]
        yield LlmResponse(
            content=types.Content(role="model", parts=parts),
            turnComplete=True,
        )


def _risk_finding(
    finding_id: str,
    category: str,
    title: str,
    entry_ids: list[str],
    amount: int,
    likelihood: int,
    impact: int,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "category": category,
        "title": title,
        "entry_ids": entry_ids,
        "evidence": ["Source tool confirmed the listed entry IDs."],
        "amount_at_risk_inr": amount,
        "likelihood": likelihood,
        "impact": impact,
        "score": likelihood * impact,
        "rationale": "Risk calculated from the source tool output.",
        "status": "open",
    }


def _session_state() -> dict[str, Any]:
    confirmed = _risk_finding(
        "finding-self-approval",
        "self_approval",
        "Self-approved payment",
        ["ENTRY-1"],
        10_000,
        5,
        2,
    )
    needs_evidence = _risk_finding(
        "finding-duplicate",
        "duplicate_payment",
        "Possible duplicate payment",
        ["ENTRY-2"],
        20_000,
        4,
        2,
    )
    dropped = _risk_finding(
        "finding-dropped",
        "self_approval",
        "Unverifiable payment",
        ["ENTRY-MISSING"],
        1_000,
        5,
        1,
    )
    return {
        "data_profile": {
            "status": "PASSED",
            "tool_results": {
                "load_ledger": {
                    "status": "PASSED",
                    "stats": {
                        "rows_loaded": 2,
                        "min_date": "2025-04-01",
                        "max_date": "2025-04-02",
                    },
                },
                "check_trial_balance": {
                    "status": "PASSED",
                    "stats": {"is_balanced": True},
                },
            },
        },
        "ranked_findings": {
            "findings": [confirmed, needs_evidence, dropped],
            "excluded_findings": [],
        },
        "verification_report": {
            "iteration": 1,
            "findings": [
                {
                    "id": confirmed["id"],
                    "finding": confirmed,
                    "entry_ids": confirmed["entry_ids"],
                    "status": "confirmed",
                    "reason": "Ledger records directly support this control exception.",
                    "checks": {},
                },
                {
                    "id": needs_evidence["id"],
                    "finding": needs_evidence,
                    "entry_ids": needs_evidence["entry_ids"],
                    "status": "needs_evidence",
                    "reason": "A plausible explanation requires supporting invoices.",
                    "checks": {},
                },
            ],
            "dropped_appendix": [
                {
                    "id": dropped["id"],
                    "finding": dropped,
                    "entry_ids": dropped["entry_ids"],
                    "status": "dropped",
                    "reason": "Ledger entry_id not found: ENTRY-MISSING.",
                    "checks": {},
                }
            ],
        },
    }


async def _run_report_flow(
    state: dict[str, Any],
    user_messages: list[str],
) -> tuple[list[list[Any]], dict[str, Any]]:
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="auditpilot_report_test",
        user_id="test_user",
        state=state,
    )
    agent = build_report_agent(
        model=ReportToolModel(model="report-test-model")
    )
    runner = Runner(
        agent=agent,
        app_name="auditpilot_report_test",
        session_service=session_service,
    )
    event_batches = []
    for message in user_messages:
        event_batches.append(
            [
                event
                async for event in runner.run_async(
                    user_id="test_user",
                    session_id=session.id,
                    new_message=types.Content(
                        role="user", parts=[types.Part(text=message)]
                    ),
                )
            ]
        )
    saved_session = await session_service.get_session(
        app_name="auditpilot_report_test",
        user_id="test_user",
        session_id=session.id,
    )
    assert saved_session is not None
    return event_batches, saved_session.state


def _tool_calls(event_batches: list[list[Any]]) -> list[str]:
    return [
        part.function_call.name
        for events in event_batches
        for event in events
        if event.content is not None
        for part in event.content.parts or []
        if part.function_call is not None
    ]


def test_report_agent_generates_draft_with_sourced_amounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "docs" / "audit_memo.md"
    monkeypatch.setattr(report_module, "REPORT_PATH", report_path)

    events, state = asyncio.run(
        _run_report_flow(_session_state(), ["Generate the audit memo."])
    )

    assert state["audit_memo_status"] == "DRAFT"
    result = ReportActionResult.model_validate(state["audit_memo_result"])
    assert result.status == "DRAFT"
    assert result.path == str(report_path)
    memo = report_path.read_text(encoding="utf-8")
    for section in (
        "1. Scope and Data",
        "2. Executive Summary",
        "3. Ranked Findings",
        "4. Entry IDs and Supporting Evidence",
        "5. Recommended Actions",
        "6. Limitations",
        "7. Appendix of Dropped Findings with Reasons",
    ):
        assert section in memo
    assert "**Status: DRAFT**" in memo
    assert "finding-self-approval" in memo
    assert "`ENTRY-1`" in memo
    assert "confirmed" in memo
    assert "ENTRY-MISSING" in memo
    assert "Ledger entry_id not found" in memo

    tool_output_amounts = {
        finding["amount_at_risk_inr"]
        for finding in state["ranked_findings"]["findings"]
    }
    memo_amounts = {
        int(value.replace(",", ""))
        for value in re.findall(r"\bINR\s+([\d,]+)", memo)
    }
    assert memo_amounts <= tool_output_amounts
    assert _tool_calls(events) == ["generate_audit_memo"]


def test_explicit_approval_changes_draft_to_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "docs" / "audit_memo.md"
    monkeypatch.setattr(report_module, "REPORT_PATH", report_path)
    batches, state = asyncio.run(
        _run_report_flow(
            _session_state(),
            ["Generate the audit memo.", "APPROVE"],
        )
    )

    assert state["audit_memo_status"] == "FINAL"
    assert state["audit_memo_signoff_choice"] == "APPROVE"
    assert "**Status: FINAL**" in report_path.read_text(encoding="utf-8")
    assert _tool_calls(batches) == [
        "generate_audit_memo",
        "record_human_signoff",
    ]


@pytest.mark.parametrize("choice", ["REQUEST CHANGES", "REJECT"])
def test_nonapproval_signoff_keeps_memo_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    choice: str,
) -> None:
    report_path = tmp_path / "docs" / "audit_memo.md"
    monkeypatch.setattr(report_module, "REPORT_PATH", report_path)
    _, state = asyncio.run(
        _run_report_flow(_session_state(), ["Generate the audit memo.", choice])
    )

    assert state["audit_memo_status"] == "DRAFT"
    assert state["audit_memo_signoff_choice"] == choice
    memo = report_path.read_text(encoding="utf-8")
    assert "**Status: DRAFT**" in memo
    assert f"**Human decision:** {choice}. Status remains DRAFT." in memo


def test_report_agent_is_final_stage_after_verification() -> None:
    assert [agent.name for agent in audit_lead.sub_agents] == [
        "intake_agent",
        "specialists",
        "risk_agent",
        "verification_loop",
        "report_agent",
    ]
    assert isinstance(audit_lead.sub_agents[-1], LlmAgent)
    assert audit_lead.sub_agents[-1].output_key == "audit_memo_result"
