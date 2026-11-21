"""Deterministic risk scoring and ADK structured-output agent."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any
from collections.abc import Mapping

import pandas as pd
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.tools import ToolContext

from ..schemas import Finding
from ..schemas import RankedFindings
from ..tools.audit_tools import DEFAULT_DATA_DIR
from ..tools.audit_tools import load_ledger
from .intake import MODEL

DATA_DIR = DEFAULT_DATA_DIR
INPUT_KEYS = (
    "anomaly_findings",
    "vendor_findings",
    "ratio_findings",
    "policy_findings",
)

_CATEGORY_CONFIG: dict[str, tuple[str, str, int]] = {
    "benford_test": (
        "benford_screening",
        "Benford population screening signal",
        2,
    ),
    "find_duplicates": (
        "duplicate_payment",
        "Potential duplicate payment",
        4,
    ),
    "find_split_payments": (
        "split_payment",
        "Potential split-payment group",
        4,
    ),
    "find_weekend_round": (
        "weekend_round_payment",
        "Weekend round-amount payment",
        3,
    ),
    "vendor_bank_overlap": (
        "vendor_control",
        "Vendor master or bank-account control concern",
        5,
    ),
    "self_approval": (
        "self_approval",
        "Transaction approved by its poster",
        5,
    ),
    "additional_review": (
        "additional_review",
        "Payment requires additional finance review",
        3,
    ),
    "split_payment": (
        "split_payment",
        "Potential split-payment group",
        4,
    ),
    "ratio_table": (
        "ratio_anomaly",
        "Financial ratio screening signal",
        2,
    ),
}

_LIKELIHOOD_RATIONALE = {
    5: "Direct transaction-level evidence indicates a prohibited control condition.",
    4: "Multiple transaction attributes indicate a strong but reviewable anomaly.",
    3: "The transaction meets a review trigger, but the available ledger does not establish a control failure.",
    2: "This is a screening indicator and is not proof of an individual transaction issue.",
}


def _read_report(state: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    if key not in state:
        raise ValueError(f"Required specialist output {key!r} is missing")
    value = state[key]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"Specialist output {key!r} is not valid JSON") from error
    if not isinstance(value, dict) or not isinstance(value.get("findings"), list):
        raise ValueError(f"Specialist output {key!r} must contain a findings list")
    if any(not isinstance(item, dict) for item in value["findings"]):
        raise ValueError(f"Specialist output {key!r} contains a malformed finding")
    return value["findings"]


def _ledger_amounts(data_dir: Path | str) -> dict[str, int]:
    result = load_ledger(data_dir)
    path = Path(data_dir) / "ledger.csv"
    ledger = pd.read_csv(
        path,
        usecols=["entry_id", "amount_inr"],
        dtype={"entry_id": "string"},
        keep_default_na=False,
        on_bad_lines="error",
    )
    if len(ledger) != result["stats"]["rows_loaded"]:
        raise ValueError(f"{path} changed while computing risk exposure")
    if ledger["entry_id"].str.strip().eq("").any():
        raise ValueError(f"{path} contains a blank entry_id")
    if ledger["entry_id"].duplicated().any():
        raise ValueError(f"{path} contains duplicate entry_id values")
    amounts = pd.to_numeric(ledger["amount_inr"], errors="raise")
    if (
        amounts.isna().any()
        or not amounts.map(math.isfinite).all()
        or (amounts <= 0).any()
        or (amounts % 1 != 0).any()
    ):
        raise ValueError(f"{path} contains invalid amount_inr values")
    return {
        str(entry_id): int(amount)
        for entry_id, amount in zip(ledger["entry_id"], amounts, strict=True)
    }


def _impact_for_amount(amount: int) -> tuple[int, str]:
    if amount < 10_000:
        return 1, "INR 1–9,999"
    if amount < 50_000:
        return 2, "INR 10,000–49,999"
    if amount < 100_000:
        return 3, "INR 50,000–99,999"
    if amount < 500_000:
        return 4, "INR 100,000–499,999"
    return 5, "INR 500,000 or more"


def _finding_category(source: Mapping[str, Any]) -> tuple[str, str, int]:
    source_type = source.get("finding_type") or source.get("tool")
    if not isinstance(source_type, str) or source_type not in _CATEGORY_CONFIG:
        raise ValueError(f"Unsupported specialist finding type: {source_type!r}")
    return _CATEGORY_CONFIG[source_type]


def _evidence(source_key: str, source: Mapping[str, Any]) -> list[str]:
    evidence = [f"Source: {source_key}"]
    for key in ("tool", "finding_type", "policy_clause_id", "quote"):
        value = source.get(key)
        if value is not None:
            evidence.append(f"{key}: {value}")
    stats = source.get("stats")
    if stats is not None:
        evidence.append(
            "Supporting tool statistics: "
            + json.dumps(stats, sort_keys=True, separators=(",", ":"))
        )
    notes = source.get("notes")
    if isinstance(notes, list):
        evidence.extend(f"Tool note: {note}" for note in notes)
    elif isinstance(notes, str) and notes:
        evidence.append(f"Tool note: {notes}")
    return evidence


def rank_findings_from_state(
    state: Mapping[str, Any],
    data_dir: Path | str = DEFAULT_DATA_DIR,
) -> RankedFindings:
    """Build validated, risk-ranked findings using only source reports and ledger data."""
    reports = {key: _read_report(state, key) for key in INPUT_KEYS}
    amount_by_id = _ledger_amounts(data_dir)
    findings: list[Finding] = []
    excluded: list[str] = []

    for source_key in INPUT_KEYS:
        for index, source in enumerate(reports[source_key], start=1):
            raw_ids = source.get("entry_ids")
            if not isinstance(raw_ids, list):
                raise ValueError(
                    f"{source_key} finding {index} must have an entry_ids list"
                )
            entry_ids = list(dict.fromkeys(str(entry_id) for entry_id in raw_ids))
            if not entry_ids:
                excluded.append(
                    f"{source_key} finding {index} excluded: no entry_ids are "
                    "available to support a transaction-level risk amount."
                )
                continue
            unknown_ids = sorted(set(entry_ids) - amount_by_id.keys())
            if unknown_ids:
                raise ValueError(
                    f"{source_key} finding {index} references unknown ledger "
                    f"entry_ids: {', '.join(unknown_ids)}"
                )

            category, title, likelihood = _finding_category(source)
            amount = sum(amount_by_id[entry_id] for entry_id in entry_ids)
            impact, amount_band = _impact_for_amount(amount)
            score = likelihood * impact
            rationale = (
                f"Likelihood {likelihood}/5: "
                f"{_LIKELIHOOD_RATIONALE[likelihood]} "
                f"Impact {impact}/5: unique listed ledger amounts total INR "
                f"{amount}, within the {amount_band} impact band. "
                f"Risk score = {likelihood} × {impact} = {score}."
            )
            identity = hashlib.sha256(
                f"{source_key}|{category}|{'|'.join(sorted(entry_ids))}".encode()
            ).hexdigest()[:16]
            findings.append(
                Finding(
                    id=f"risk-{identity}",
                    category=category,
                    title=title,
                    entry_ids=entry_ids,
                    evidence=_evidence(source_key, source),
                    amount_at_risk_inr=amount,
                    likelihood=likelihood,
                    impact=impact,
                    score=score,
                    rationale=rationale,
                    status="open",
                )
            )

    findings.sort(
        key=lambda finding: (
            -finding.score,
            -finding.amount_at_risk_inr,
            finding.id,
        )
    )
    return RankedFindings(findings=findings, excluded_findings=excluded)


def calculate_ranked_findings(tool_context: ToolContext) -> dict[str, Any]:
    """Calculate all findings deterministically from the specialist session state."""
    return rank_findings_from_state(tool_context.state, DATA_DIR).model_dump()


def build_risk_agent(model: str | BaseLlm = MODEL) -> LlmAgent:
    """Build the risk agent with deterministic scoring and Pydantic output."""
    return LlmAgent(
        model=model,
        name="risk_agent",
        description="Combines specialist evidence into deterministic ranked findings.",
        instruction=(
            "Call calculate_ranked_findings exactly once after the specialist "
            "outputs are available. Return the tool result verbatim using the "
            "required output schema. Do not invent, alter, recalculate, or "
            "summarize any IDs, evidence, amount, likelihood, impact, score, "
            "rationale, status, or exclusions. Python calculated every "
            "numerical value. Findings without entry IDs are intentionally "
            "excluded with a reason."
        ),
        tools=[calculate_ranked_findings],
        output_schema=RankedFindings,
        output_key="ranked_findings",
    )


risk_agent = build_risk_agent()
