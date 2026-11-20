from __future__ import annotations

import asyncio
import json
from collections import Counter
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

from auditpilot.agents import policy as policy_module
from auditpilot.agents.policy import build_policy_agent
from auditpilot.tools import check_approval_limits
from auditpilot.tools import find_split_payments
from auditpilot.tools.retrieve_policy import retrieve_policy

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RETRIEVAL_CASES = (
    (
        "Can the person who posts a payment approve the same transaction?",
        "1.1",
    ),
    (
        "When does a payment require additional finance review?",
        "1.3",
    ),
    (
        "Can related payments be split to avoid an approval limit?",
        "1.4",
    ),
    (
        "What authorization is needed for a Sunday payment?",
        "1.5",
    ),
    (
        "May a vendor share a bank account with an employee?",
        "2.2",
    ),
)
POLICY_QUERIES = (
    "person who posts approving the same transaction",
    "payment of INR 50,000 or more additional finance review",
    "related payments split purchase avoid approval limits",
)
POLICY_CATEGORIES = (
    ("self_approval", "self_approved_ids"),
    ("additional_review", "at_or_above_limit_ids"),
    ("split_payment", "split_payment_ids"),
)


class PolicyToolModel(BaseLlm):
    """Deterministic model that calls policy tools and cites their results."""

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        tool_results: dict[str, dict[str, Any]] = {}
        retrieval_results: list[dict[str, Any]] = []
        for content in llm_request.contents:
            for part in content.parts or []:
                response_part = part.function_response
                if response_part is None:
                    continue
                response = response_part.response
                if "result" in response and isinstance(response["result"], dict):
                    response = response["result"]
                if response_part.name == "retrieve_policy":
                    retrieval_results.append(response)
                else:
                    tool_results[response_part.name] = response

        if "check_approval_limits" not in tool_results:
            parts = [
                types.Part(
                    function_call=types.FunctionCall(
                        name="check_approval_limits", args={}
                    )
                )
            ]
        elif len(retrieval_results) < len(POLICY_QUERIES):
            query = POLICY_QUERIES[len(retrieval_results)]
            parts = [
                types.Part(
                    function_call=types.FunctionCall(
                        name="retrieve_policy", args={"query": query, "k": 3}
                    )
                )
            ]
        else:
            approval_stats = tool_results["check_approval_limits"]["stats"]
            findings = []
            for (finding_type, ids_key), retrieval_result in zip(
                POLICY_CATEGORIES, retrieval_results, strict=True
            ):
                entry_ids = approval_stats[ids_key]
                clauses = retrieval_result["clauses"]
                if entry_ids and clauses:
                    findings.append(
                        {
                            "finding_type": finding_type,
                            "entry_ids": entry_ids,
                            "policy_clause_id": clauses[0]["clause_id"],
                            "quote": clauses[0]["quote"],
                        }
                    )
            parts = [types.Part(text=json.dumps({"findings": findings}))]

        yield LlmResponse(
            content=types.Content(role="model", parts=parts),
            turnComplete=True,
        )


def test_retrieve_policy_ranks_expected_clause_first() -> None:
    policy_text = " ".join(
        (DATA_DIR / "policy.md").read_text(encoding="utf-8").split()
    )
    for query, expected_clause_id in RETRIEVAL_CASES:
        result = retrieve_policy(query)
        assert result["test"] == "retrieve_policy"
        assert result["stats"]["retrieval_method"] == "tfidf"
        assert result["clauses"][0]["clause_id"] == expected_clause_id
        assert len(result["clauses"]) <= 3
        assert result["clauses"][0]["quote"] in policy_text


def test_retrieve_policy_returns_no_unsupported_match() -> None:
    result = retrieve_policy("Explain quantum mechanics")
    assert result["clauses"] == []


def test_approval_tool_includes_self_approval_and_split_payment_evidence() -> None:
    approval_result = check_approval_limits(DATA_DIR)
    split_result = find_split_payments(DATA_DIR)
    stats = approval_result["stats"]

    assert stats["self_approved_count"] == 8
    assert set(stats["self_approved_ids"]) <= set(approval_result["flagged_ids"])
    assert stats["split_payment_group_count"] == split_result["stats"][
        "candidate_group_count"
    ]
    assert set(stats["split_payment_ids"]) == set(split_result["flagged_ids"])
    assert set(stats["split_payment_ids"]) <= set(approval_result["flagged_ids"])


async def _run_policy_agent() -> tuple[list[Any], dict[str, Any]]:
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="auditpilot_policy_test",
        user_id="test_user",
    )
    agent = build_policy_agent(
        model=PolicyToolModel(model="policy-test-model")
    )
    runner = Runner(
        agent=agent,
        app_name="auditpilot_policy_test",
        session_service=session_service,
    )
    events = [
        event
        async for event in runner.run_async(
            user_id="test_user",
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text="Check approval policy findings.")],
            ),
        )
    ]
    saved_session = await session_service.get_session(
        app_name="auditpilot_policy_test",
        user_id="test_user",
        session_id=session.id,
    )
    assert saved_session is not None
    return events, saved_session.state


def test_policy_agent_saves_cited_findings_for_self_and_split_payments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy_module, "DATA_DIR", DATA_DIR)
    events, state = asyncio.run(_run_policy_agent())

    assert "policy_findings" in state
    report = json.loads(state["policy_findings"])
    findings = {
        finding["finding_type"]: finding for finding in report["findings"]
    }
    assert {"self_approval", "split_payment"} <= findings.keys()

    approval_result = check_approval_limits(DATA_DIR)
    for finding_type, ids_key, clause_id in (
        ("self_approval", "self_approved_ids", "1.1"),
        ("split_payment", "split_payment_ids", "1.4"),
    ):
        finding = findings[finding_type]
        assert set(finding["entry_ids"]) == set(
            approval_result["stats"][ids_key]
        )
        assert finding["policy_clause_id"] == clause_id
        assert finding["quote"] == retrieve_policy(
            POLICY_QUERIES[0]
            if finding_type == "self_approval"
            else POLICY_QUERIES[2]
        )["clauses"][0]["quote"]

    calls = Counter(
        part.function_call.name
        for event in events
        if event.content is not None
        for part in event.content.parts or []
        if part.function_call is not None
    )
    assert calls == Counter(
        {"check_approval_limits": 1, "retrieve_policy": len(POLICY_QUERIES)}
    )


def test_policy_agent_declares_only_required_tools_and_output_key() -> None:
    agent = build_policy_agent(model=PolicyToolModel(model="policy-test-model"))
    assert isinstance(agent, LlmAgent)
    assert [tool.__name__ for tool in agent.tools] == [
        "check_approval_limits",
        "retrieve_policy",
    ]
    assert agent.output_key == "policy_findings"
