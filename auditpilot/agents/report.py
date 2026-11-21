"""Audit memo generation and explicit human sign-off."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from typing import Literal
from collections.abc import Mapping

from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.tools import ToolContext
from pydantic import BaseModel
from pydantic import ConfigDict

from .intake import MODEL

REPORT_PATH = Path(__file__).resolve().parents[2] / "docs" / "audit_memo.md"
SIGNOFF_CHOICES = ("APPROVE", "REQUEST CHANGES", "REJECT")
_STATUS_LINE = re.compile(r"(?m)^\*\*Status: (DRAFT|FINAL)\*\*$")


class ReportActionResult(BaseModel):
    """Outcome of memo generation or human sign-off."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["DRAFT", "FINAL"]
    path: str
    message: str


def _read_state_object(state: Mapping[str, Any], key: str) -> dict[str, Any]:
    if key not in state:
        raise ValueError(f"Session state is missing {key!r}")
    value = state[key]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"Session state {key!r} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"Session state {key!r} must be a JSON object")
    return value


def _format_entry_ids(entry_ids: Any) -> str:
    if not isinstance(entry_ids, list) or not entry_ids:
        return "None supplied by the source output."
    return ", ".join(f"`{entry_id}`" for entry_id in entry_ids)


def _finding_payload(verified: Mapping[str, Any]) -> dict[str, Any]:
    finding = verified.get("finding")
    if not isinstance(finding, dict):
        raise ValueError("Verification output contains a finding without its source")
    return finding


def _recommended_action(category: str) -> str:
    actions = {
        "self_approval": (
            "Review the approval trail and enforce a separate approver for each "
            "transaction."
        ),
        "duplicate_payment": (
            "Match invoices and payment references before deciding whether a "
            "duplicate occurred."
        ),
        "split_payment": (
            "Review invoices and purchase orders to determine whether the "
            "payments are related and require combined approval."
        ),
        "weekend_round_payment": (
            "Request the applicable weekend authorization and supporting "
            "documentation."
        ),
        "vendor_control": (
            "Validate the vendor master entry and confirm bank-account ownership "
            "through approved records."
        ),
        "additional_review": (
            "Obtain evidence of the required finance review before closure."
        ),
        "benford_screening": (
            "Investigate the population-level signal; do not treat it alone as "
            "evidence of an individual transaction violation."
        ),
    }
    return actions.get(
        category,
        "Request supporting documentation and review the cited transaction records.",
    )


def _render_audit_memo(state: Mapping[str, Any]) -> str:
    profile = _read_state_object(state, "data_profile")
    ranked = _read_state_object(state, "ranked_findings")
    verification = _read_state_object(state, "verification_report")

    profile_tools = profile.get("tool_results")
    if not isinstance(profile_tools, dict):
        raise ValueError("data_profile must contain tool_results")
    ledger_stats = profile_tools.get("load_ledger", {}).get("stats", {})
    trial_result = profile_tools.get("check_trial_balance", {})
    active = verification.get("findings")
    dropped = verification.get("dropped_appendix", [])
    ranked_findings = ranked.get("findings")
    if not isinstance(active, list) or not isinstance(dropped, list):
        raise ValueError("verification_report must contain findings and dropped_appendix")
    if not isinstance(ranked_findings, list):
        raise ValueError("ranked_findings must contain a findings list")
    ranked_by_id = {
        finding.get("id"): finding
        for finding in ranked_findings
        if isinstance(finding, dict) and isinstance(finding.get("id"), str)
    }

    verified_items: list[tuple[str, dict[str, Any], list[str], str]] = []
    for collection, expected_statuses in (
        (active, {"confirmed", "needs_evidence"}),
        (dropped, {"dropped"}),
    ):
        for verified in collection:
            if not isinstance(verified, dict):
                raise ValueError("verification_report contains a malformed finding")
            status = verified.get("status")
            if status not in expected_statuses:
                raise ValueError(f"Unexpected verification status {status!r}")
            finding = _finding_payload(verified)
            finding_id = finding.get("id")
            source_finding = ranked_by_id.get(finding_id)
            if source_finding is None:
                raise ValueError(
                    f"Verified finding {finding_id!r} is absent from ranked_findings"
                )
            amount = source_finding.get("amount_at_risk_inr")
            if type(amount) is not int or amount != finding.get(
                "amount_at_risk_inr"
            ):
                raise ValueError(
                    f"Finding {finding_id!r} has an amount that does not match "
                    "ranked_findings"
                )
            reason = verified.get("reason", "")
            verified_items.append(
                (
                    status,
                    finding,
                    verified.get("entry_ids", []),
                    str(reason),
                )
            )

    confirmed_count = sum(status == "confirmed" for status, *_ in verified_items)
    needs_evidence_count = sum(
        status == "needs_evidence" for status, *_ in verified_items
    )
    dropped_count = sum(status == "dropped" for status, *_ in verified_items)

    min_date = ledger_stats.get("min_date", "not reported")
    max_date = ledger_stats.get("max_date", "not reported")
    rows_loaded = ledger_stats.get("rows_loaded", "not reported")
    balanced = trial_result.get("stats", {}).get("is_balanced", "not reported")
    lines = [
        "# Audit Memo",
        "",
        "**Status: DRAFT**",
        "",
        "## 1. Scope and Data",
        "",
        f"- Ledger rows loaded: {rows_loaded}",
        f"- Ledger date range: {min_date} to {max_date}",
        f"- Trial-balance equality check: {balanced}",
        "- Sources: intake, specialist, risk, and verification outputs in this ADK session.",
        "",
        "## 2. Executive Summary",
        "",
        f"- Confirmed findings: {confirmed_count}",
        f"- Findings needing evidence: {needs_evidence_count}",
        f"- Dropped findings retained in the appendix: {dropped_count}",
        (
            "- No finding was independently interpreted beyond the cited "
            "session outputs."
        ),
        "",
        "## 3. Ranked Findings",
        "",
    ]

    reportable = [
        item for item in verified_items if item[0] in {"confirmed", "needs_evidence"}
    ]
    reportable.sort(
        key=lambda item: (
            -int(item[1].get("score", 0)),
            -int(item[1].get("amount_at_risk_inr", 0)),
            str(item[1].get("id", "")),
        )
    )
    if not any(status == "confirmed" for status, *_ in reportable):
        lines.append("No findings were confirmed by the verification checks.")
        lines.append("")
    for status, finding, entry_ids, reason in reportable:
        lines.extend(
            [
                f"### {finding.get('title', finding.get('category', 'Finding'))}",
                "",
                f"- Status: `{status}`",
                f"- Risk score: {finding.get('score')} "
                f"(likelihood {finding.get('likelihood')} × impact {finding.get('impact')})",
                f"- Amount at risk: INR "
                f"{int(finding['amount_at_risk_inr']):,}",
                f"- Verification: {reason}",
                "",
            ]
        )

    lines.extend(["## 4. Entry IDs and Supporting Evidence", ""])
    if not reportable:
        lines.extend(["No non-dropped findings to detail.", ""])
    for status, finding, entry_ids, _ in reportable:
        lines.extend(
            [
                f"### {finding.get('id', 'Finding')} — {status}",
                "",
                f"- Entry IDs: {_format_entry_ids(entry_ids)}",
                "- Evidence:",
            ]
        )
        evidence = finding.get("evidence", [])
        if not isinstance(evidence, list) or not evidence:
            lines.append("  - No supporting evidence was supplied.")
        else:
            lines.extend(f"  - {item}" for item in evidence)
        lines.append("")

    lines.extend(["## 5. Recommended Actions", ""])
    if not reportable:
        lines.extend(["No action is recommended from the available findings.", ""])
    for status, finding, entry_ids, _ in reportable:
        lines.append(
            f"- `{finding.get('id', 'Finding')}` ({status}): "
            f"{_recommended_action(str(finding.get('category', '')))}"
        )
    lines.append("")

    lines.extend(
        [
            "## 6. Limitations",
            "",
            "- Automated indicators are not, by themselves, proof of misconduct.",
            "- Findings marked `needs_evidence` require human review of supporting records.",
            "- This memo uses only the cited session state and tool outputs.",
            "",
            "## 7. Appendix of Dropped Findings with Reasons",
            "",
        ]
    )
    appendix = [
        item for item in verified_items if item[0] == "dropped"
    ]
    if not appendix:
        lines.extend(["No findings were dropped.", ""])
    for _, finding, entry_ids, reason in appendix:
        lines.extend(
            [
                f"- `{finding.get('id', 'Finding')}` "
                f"({finding.get('title', finding.get('category', 'Finding'))})",
                f"  - Entry IDs: {_format_entry_ids(entry_ids)}",
                f"  - Reason: {reason}",
            ]
        )
    lines.extend(
        [
            "",
            "## Human Sign-Off",
            "",
            "Reply exactly `APPROVE`, `REQUEST CHANGES`, or `REJECT`.",
            "",
        ]
    )
    return "\n".join(lines)


def generate_audit_memo(tool_context: ToolContext) -> dict[str, str]:
    """Write a DRAFT audit memo from validated session outputs."""
    state = tool_context.state
    if state.get("audit_memo_status") == "FINAL":
        raise ValueError("A FINAL memo cannot be overwritten by draft generation")
    content = _render_audit_memo(state)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(content, encoding="utf-8")
    state["audit_memo_status"] = "DRAFT"
    state["audit_memo_path"] = str(REPORT_PATH)
    return {
        "status": "DRAFT",
        "path": str(REPORT_PATH),
        "message": "The audit memo was generated as DRAFT and requires human sign-off.",
    }


def _user_choice(tool_context: ToolContext) -> str:
    content = tool_context.user_content
    if content is None:
        return ""
    return "\n".join(
        part.text for part in content.parts or [] if part.text
    ).strip().upper()


def record_human_signoff(
    choice: Literal["APPROVE", "REQUEST CHANGES", "REJECT"],
    tool_context: ToolContext,
) -> dict[str, str]:
    """Apply a sign-off only when the current user explicitly chose it."""
    if _user_choice(tool_context) != choice:
        raise ValueError(
            "Sign-off requires the exact choice in the current human message."
        )
    if tool_context.state.get("audit_memo_status") != "DRAFT":
        raise ValueError("Only a DRAFT audit memo can receive sign-off.")
    if not REPORT_PATH.is_file():
        raise FileNotFoundError(f"Audit memo not found: {REPORT_PATH}")

    content = REPORT_PATH.read_text(encoding="utf-8")
    match = _STATUS_LINE.search(content)
    if match is None or match.group(1) != "DRAFT":
        raise ValueError("The audit memo file is not in DRAFT status.")
    status = "FINAL" if choice == "APPROVE" else "DRAFT"
    updated = _STATUS_LINE.sub(f"**Status: {status}**", content, count=1)
    updated += f"\n**Human decision:** {choice}. Status remains {status}.\n"
    REPORT_PATH.write_text(updated, encoding="utf-8")
    tool_context.state["audit_memo_status"] = status
    tool_context.state["audit_memo_signoff_choice"] = choice
    return {
        "status": status,
        "path": str(REPORT_PATH),
        "message": (
            "The memo is FINAL after explicit human approval."
            if choice == "APPROVE"
            else f"The memo remains DRAFT after {choice}."
        ),
    }


def build_report_agent(model: str | BaseLlm = MODEL) -> LlmAgent:
    """Build the report LlmAgent with deterministic generation and sign-off tools."""
    return LlmAgent(
        model=model,
        name="report_agent",
        description="Generates a sourced draft audit memo and handles human sign-off.",
        instruction=(
            "For an ordinary audit completion, call generate_audit_memo exactly "
            "once and do not call a sign-off tool. If the current human message "
            "is exactly APPROVE, REQUEST CHANGES, or REJECT, call "
            "record_human_signoff exactly once with that choice and do not "
            "regenerate the memo. Return only the tool result. Never invent "
            "financial values, allegations, evidence, IDs, or approval."
        ),
        tools=[generate_audit_memo, record_human_signoff],
        output_schema=ReportActionResult,
        output_key="audit_memo_result",
    )


report_agent = build_report_agent()
