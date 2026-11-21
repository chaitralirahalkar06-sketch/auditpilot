from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.loop_agent import LoopAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from auditpilot.agent import audit_lead
from auditpilot.agents import skeptic as skeptic_module
from auditpilot.agents.skeptic import build_skeptic_agent
from auditpilot.agents.skeptic import verification_loop
from auditpilot.schemas import VerificationReport


class SkepticEchoModel(BaseLlm):
    """Test model that calls the verifier and echoes its structured result."""

    waiting_for_tool_result: bool = False

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        if not self.waiting_for_tool_result:
            self.waiting_for_tool_result = True
            parts = [
                types.Part(
                    function_call=types.FunctionCall(
                        name="verify_entry_ids", args={}
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
                raise AssertionError("Verifier tool response was not present")
            parts = [types.Part(text=json.dumps(result))]
        yield LlmResponse(
            content=types.Content(role="model", parts=parts),
            turnComplete=True,
        )


def _make_data_dir(directory: Path) -> Path:
    directory.mkdir()
    pd.DataFrame(
        [
            {
                "entry_id": "ENTRY-SELF",
                "date": "2025-04-01",
                "posted_by": "EMP-1",
                "approved_by": "EMP-1",
                "account_code": "1000",
                "account_name": "Cash",
                "vendor_id": "V-1",
                "amount_inr": 1_000,
                "description": "Routine payment",
            },
            {
                "entry_id": "ENTRY-DUP-1",
                "date": "2025-04-02",
                "posted_by": "EMP-2",
                "approved_by": "EMP-3",
                "account_code": "1000",
                "account_name": "Cash",
                "vendor_id": "V-2",
                "amount_inr": 10_000,
                "description": "First payment",
            },
            {
                "entry_id": "ENTRY-DUP-2",
                "date": "2025-04-02",
                "posted_by": "EMP-4",
                "approved_by": "EMP-5",
                "account_code": "1000",
                "account_name": "Cash",
                "vendor_id": "V-2",
                "amount_inr": 10_000,
                "description": "Second payment",
            },
        ]
    ).to_csv(directory / "ledger.csv", index=False)
    return directory


def _finding(
    finding_id: str,
    category: str,
    entry_ids: list[str],
    amount: int,
    likelihood: int,
    impact: int,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "category": category,
        "title": f"Test {category}",
        "entry_ids": entry_ids,
        "evidence": ["Source tool evidence."],
        "amount_at_risk_inr": amount,
        "likelihood": likelihood,
        "impact": impact,
        "score": likelihood * impact,
        "rationale": "Deterministic test rationale.",
        "status": "open",
    }


async def _run_verification(
    data_dir: Path, findings: list[dict[str, Any]]
) -> tuple[list[Any], dict[str, Any]]:
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="auditpilot_skeptic_test",
        user_id="test_user",
        state={
            "ranked_findings": {
                "findings": findings,
                "excluded_findings": [],
            }
        },
    )
    skeptic_agent = build_skeptic_agent(
        model=SkepticEchoModel(model="skeptic-test-model")
    )
    loop = LoopAgent(
        name="verification_loop_test",
        sub_agents=[skeptic_agent],
        max_iterations=3,
    )
    runner = Runner(
        agent=loop,
        app_name="auditpilot_skeptic_test",
        session_service=session_service,
    )
    events = [
        event
        async for event in runner.run_async(
            user_id="test_user",
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text="Verify all ranked findings.")],
            ),
        )
    ]
    saved_session = await session_service.get_session(
        app_name="auditpilot_skeptic_test",
        user_id="test_user",
        session_id=session.id,
    )
    assert saved_session is not None
    return events, saved_session.state


def _verify_calls(events: list[Any]) -> Counter[str]:
    return Counter(
        part.function_call.name
        for event in events
        if event.content is not None
        for part in event.content.parts or []
        if part.function_call is not None
    )


def test_missing_entry_id_is_dropped_and_valid_seed_is_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _make_data_dir(tmp_path / "ledger_data")
    monkeypatch.setattr(skeptic_module, "DATA_DIR", data_dir)
    findings = [
        _finding(
            "self-approval-valid",
            "self_approval",
            ["ENTRY-SELF"],
            amount=1_000,
            likelihood=5,
            impact=1,
        ),
        _finding(
            "missing-ledger-id",
            "self_approval",
            ["ENTRY-DOES-NOT-EXIST"],
            amount=1_000,
            likelihood=5,
            impact=1,
        ),
        _finding(
            "unsupported-amount",
            "self_approval",
            ["ENTRY-SELF"],
            amount=2_000,
            likelihood=5,
            impact=1,
        ),
    ]

    events, state = asyncio.run(_run_verification(data_dir, findings))

    report = VerificationReport.model_validate(state["verification_report"])
    assert report.iteration == 1
    assert len(report.findings) == 1
    confirmed = report.findings[0]
    assert confirmed.id == "self-approval-valid"
    assert confirmed.status == "confirmed"
    assert confirmed.reason
    assert "\n" not in confirmed.reason
    assert confirmed.checks.entry_ids_exist
    assert confirmed.checks.evidence_supports_claim

    assert len(report.dropped_appendix) == 2
    dropped = next(
        finding
        for finding in report.dropped_appendix
        if finding.id == "missing-ledger-id"
    )
    assert dropped.id == "missing-ledger-id"
    assert dropped.status == "dropped"
    assert "ENTRY-DOES-NOT-EXIST" in dropped.reason
    assert dropped.finding["entry_ids"] == ["ENTRY-DOES-NOT-EXIST"]
    unsupported = next(
        finding
        for finding in report.dropped_appendix
        if finding.id == "unsupported-amount"
    )
    assert unsupported.status == "dropped"
    assert "does not match ledger total INR 1000" in unsupported.reason
    assert _verify_calls(events) == Counter({"verify_entry_ids": 1})


def test_needs_evidence_is_reverified_until_three_round_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _make_data_dir(tmp_path / "ledger_data")
    monkeypatch.setattr(skeptic_module, "DATA_DIR", data_dir)
    duplicate_finding = _finding(
        "duplicate-needs-invoice",
        "duplicate_payment",
        ["ENTRY-DUP-2"],
        amount=10_000,
        likelihood=4,
        impact=2,
    )

    events, state = asyncio.run(
        _run_verification(data_dir, [duplicate_finding])
    )

    report = VerificationReport.model_validate(state["verification_report"])
    assert report.iteration == 3
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.status == "needs_evidence"
    assert finding.checks.entry_ids_exist
    assert finding.checks.evidence_supports_claim
    assert finding.checks.innocent_explanation_plausible
    assert finding.reason
    assert _verify_calls(events) == Counter({"verify_entry_ids": 3})


def test_production_loop_follows_risk_and_has_three_iteration_cap() -> None:
    assert isinstance(verification_loop, LoopAgent)
    assert verification_loop.max_iterations == 3
    assert [agent.name for agent in audit_lead.sub_agents] == [
        "intake_agent",
        "specialists",
        "risk_agent",
        "verification_loop",
        "report_agent",
    ]
    assert isinstance(verification_loop.sub_agents[0], LlmAgent)
    assert verification_loop.sub_agents[0].name == "skeptic_agent"
    assert [tool.__name__ for tool in verification_loop.sub_agents[0].tools] == [
        "verify_entry_ids"
    ]
