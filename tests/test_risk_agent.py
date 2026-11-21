from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError

from auditpilot.agent import audit_lead
from auditpilot.agents import risk as risk_module
from auditpilot.agents.risk import INPUT_KEYS
from auditpilot.agents.risk import build_risk_agent
from auditpilot.agents.risk import rank_findings_from_state
from auditpilot.schemas import Finding
from auditpilot.schemas import RankedFindings

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class RiskEchoModel(BaseLlm):
    """Test model that calls the risk tool and echoes its validated result."""

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        tool_result: dict[str, Any] | None = None
        for content in llm_request.contents:
            for part in content.parts or []:
                function_response = part.function_response
                if function_response is not None:
                    response = function_response.response
                    if "result" in response and isinstance(response["result"], dict):
                        response = response["result"]
                    tool_result = response
        if tool_result is None:
            parts = [
                types.Part(
                    function_call=types.FunctionCall(
                        name="calculate_ranked_findings", args={}
                    )
                )
            ]
        else:
            parts = [types.Part(text=json.dumps(tool_result))]
        yield LlmResponse(
            content=types.Content(role="model", parts=parts),
            turnComplete=True,
        )


def _finding_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "risk-example",
        "category": "duplicate_payment",
        "title": "Potential duplicate payment",
        "entry_ids": ["ENTRY-1"],
        "evidence": ["Source: anomaly_findings"],
        "amount_at_risk_inr": 10_000,
        "likelihood": 4,
        "impact": 2,
        "score": 8,
        "rationale": "Deterministic rubric test.",
        "status": "open",
    }
    payload.update(overrides)
    return payload


def _make_data_dir(directory: Path) -> Path:
    directory.mkdir()
    pd.DataFrame(
        [
            {
                "entry_id": "ENTRY-1",
                "date": "2025-04-01",
                "posted_by": "EMP-1",
                "approved_by": "EMP-2",
                "account_code": "1000",
                "account_name": "Cash",
                "vendor_id": "V-1",
                "amount_inr": 10_000,
                "description": "Routine payment",
            },
            {
                "entry_id": "ENTRY-2",
                "date": "2025-04-02",
                "posted_by": "EMP-2",
                "approved_by": "EMP-3",
                "account_code": "1000",
                "account_name": "Cash",
                "vendor_id": "V-2",
                "amount_inr": 50_000,
                "description": "Routine payment",
            },
            {
                "entry_id": "ENTRY-3",
                "date": "2025-04-03",
                "posted_by": "EMP-3",
                "approved_by": "EMP-4",
                "account_code": "1000",
                "account_name": "Cash",
                "vendor_id": "V-3",
                "amount_inr": 400_000,
                "description": "Routine payment",
            },
        ]
    ).to_csv(directory / "ledger.csv", index=False)
    return directory


def _source_state() -> dict[str, Any]:
    return {
        "anomaly_findings": json.dumps(
            {
                "findings": [
                    {
                        "tool": "find_duplicates",
                        "entry_ids": ["ENTRY-1"],
                        "stats": {"duplicate_entry_count": 1},
                        "notes": ["Duplicate candidate requires review."],
                    }
                ]
            }
        ),
        "vendor_findings": json.dumps(
            {
                "findings": [
                    {
                        "tool": "vendor_bank_overlap",
                        "entry_ids": ["ENTRY-2"],
                        "stats": {"shared_account_entry_ids": ["ENTRY-2"]},
                        "notes": ["Shared account match."],
                    }
                ]
            }
        ),
        "ratio_findings": json.dumps(
            {"findings": [{"tool": "ratio_table", "entry_ids": []}]}
        ),
        "policy_findings": json.dumps(
            {
                "findings": [
                    {
                        "finding_type": "self_approval",
                        "entry_ids": ["ENTRY-3"],
                        "policy_clause_id": "1.1",
                        "quote": "The poster must not approve the transaction.",
                    }
                ]
            }
        ),
    }


def test_finding_schema_requires_entry_ids() -> None:
    payload = _finding_payload()
    payload.pop("entry_ids")
    with pytest.raises(ValidationError):
        Finding.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("likelihood", 0), ("likelihood", 6), ("impact", 0), ("impact", 6)],
)
def test_finding_schema_rejects_out_of_range_risk_ratings(
    field: str, value: int
) -> None:
    with pytest.raises(ValidationError):
        Finding.model_validate(_finding_payload(**{field: value}))


def test_finding_schema_rejects_score_not_calculated_from_ratings() -> None:
    with pytest.raises(ValidationError):
        Finding.model_validate(_finding_payload(score=9))


def test_rank_findings_calculates_amount_risk_and_sorts(
    tmp_path: Path,
) -> None:
    data_dir = _make_data_dir(tmp_path / "ledger_data")

    result = rank_findings_from_state(_source_state(), data_dir)

    assert [finding.score for finding in result.findings] == [20, 15, 8]
    assert [finding.amount_at_risk_inr for finding in result.findings] == [
        400_000,
        50_000,
        10_000,
    ]
    assert [finding.likelihood for finding in result.findings] == [5, 5, 4]
    assert [finding.impact for finding in result.findings] == [4, 3, 2]
    assert all(finding.score == finding.likelihood * finding.impact for finding in result.findings)
    assert all(finding.entry_ids for finding in result.findings)
    assert len(result.excluded_findings) == 1
    assert "ratio_findings" in result.excluded_findings[0]
    assert "no entry_ids" in result.excluded_findings[0]


def test_rank_findings_rejects_missing_state_or_unknown_entry_ids(
    tmp_path: Path,
) -> None:
    data_dir = _make_data_dir(tmp_path / "ledger_data")
    state = _source_state()
    del state["vendor_findings"]
    with pytest.raises(ValueError, match="vendor_findings"):
        rank_findings_from_state(state, data_dir)

    state = _source_state()
    state["anomaly_findings"] = json.dumps(
        {"findings": [{"tool": "find_duplicates", "entry_ids": ["UNKNOWN"]}]}
    )
    with pytest.raises(ValueError, match="unknown ledger entry_ids"):
        rank_findings_from_state(state, data_dir)


async def _run_risk_agent(
    state: dict[str, Any],
) -> tuple[list[Any], dict[str, Any]]:
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="auditpilot_risk_test",
        user_id="test_user",
        state=state,
    )
    agent = build_risk_agent(model=RiskEchoModel(model="risk-test-model"))
    runner = Runner(
        agent=agent,
        app_name="auditpilot_risk_test",
        session_service=session_service,
    )
    events = [
        event
        async for event in runner.run_async(
            user_id="test_user",
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text="Rank the audit findings.")],
            ),
        )
    ]
    saved_session = await session_service.get_session(
        app_name="auditpilot_risk_test",
        user_id="test_user",
        session_id=session.id,
    )
    assert saved_session is not None
    return events, saved_session.state


def test_risk_agent_saves_structured_ranked_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _make_data_dir(tmp_path / "ledger_data")
    monkeypatch.setattr(risk_module, "DATA_DIR", data_dir)

    events, state = asyncio.run(_run_risk_agent(_source_state()))

    assert "ranked_findings" in state
    report = RankedFindings.model_validate(state["ranked_findings"])
    assert [finding.score for finding in report.findings] == [20, 15, 8]
    assert all(finding.entry_ids for finding in report.findings)
    assert len(report.excluded_findings) == 1
    tool_calls = [
        part.function_call.name
        for event in events
        if event.content is not None
        for part in event.content.parts or []
        if part.function_call is not None
    ]
    assert tool_calls == ["calculate_ranked_findings"]


def test_risk_agent_uses_schema_and_runs_after_specialists() -> None:
    agent = build_risk_agent(model=RiskEchoModel(model="risk-test-model"))
    assert isinstance(agent, LlmAgent)
    assert agent.name == "risk_agent"
    assert agent.output_key == "ranked_findings"
    assert agent.output_schema is RankedFindings
    assert [sub_agent.name for sub_agent in audit_lead.sub_agents] == [
        "intake_agent",
        "specialists",
        "risk_agent",
        "verification_loop",
        "report_agent",
    ]
    assert set(INPUT_KEYS) == {
        "anomaly_findings",
        "vendor_findings",
        "ratio_findings",
        "policy_findings",
    }
