"""ADK intake agent and deterministic dataset validation tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.tools import ToolContext

from ..tools.audit_tools import DEFAULT_DATA_DIR
from ..tools.audit_tools import check_trial_balance as _check_trial_balance
from ..tools.audit_tools import load_ledger as _load_ledger

MODEL = "gemini-3.1-flash-lite"
DATA_DIR = DEFAULT_DATA_DIR
EXPECTED_LEDGER_ROWS = 6_000
FISCAL_START = "2025-04-01"
FISCAL_END = "2026-03-31"
LOAD_STATUS_KEY = "intake_load_ledger_status"
TRIAL_BALANCE_STATUS_KEY = "intake_check_trial_balance_status"


def _record_result(
    result: dict[str, Any],
    tool_context: ToolContext,
    status_key: str,
    reasons: list[str],
) -> dict[str, Any]:
    status = "FAILED" if reasons else "PASSED"
    result["status"] = status
    result["reasons"] = reasons
    tool_context.state[f"{status_key}:{tool_context.invocation_id}"] = status
    return result


def _failed_result(
    test: str,
    tool_context: ToolContext,
    status_key: str,
    reason: str,
) -> dict[str, Any]:
    return _record_result(
        {
            "test": test,
            "flagged_ids": [],
            "stats": {},
            "notes": [reason],
        },
        tool_context,
        status_key,
        [reason],
    )


def load_ledger(tool_context: ToolContext) -> dict[str, Any]:
    """Validate ledger columns, row count, and FY dates using the Phase 2 loader."""
    try:
        result = _load_ledger(DATA_DIR)
    except (FileNotFoundError, pd.errors.ParserError, ValueError) as error:
        return _failed_result(
            "load_ledger", tool_context, LOAD_STATUS_KEY, str(error)
        )

    stats = result["stats"]
    reasons: list[str] = []
    row_count = int(stats["rows_loaded"])
    if row_count != EXPECTED_LEDGER_ROWS:
        reasons.append(
            f"Expected {EXPECTED_LEDGER_ROWS} ledger rows; found {row_count}."
        )

    min_date = stats["min_date"]
    max_date = stats["max_date"]
    if min_date is None or max_date is None:
        reasons.append("Ledger date range could not be verified because it has no rows.")
    elif min_date < FISCAL_START or max_date > FISCAL_END:
        reasons.append(
            f"Ledger dates {min_date} through {max_date} fall outside "
            f"FY 2025-26 ({FISCAL_START} through {FISCAL_END})."
        )

    stats["expected_rows"] = EXPECTED_LEDGER_ROWS
    stats["expected_fiscal_start"] = FISCAL_START
    stats["expected_fiscal_end"] = FISCAL_END
    return _record_result(result, tool_context, LOAD_STATUS_KEY, reasons)


def check_trial_balance(tool_context: ToolContext) -> dict[str, Any]:
    """Validate balance equality and ledger-to-trial-balance reconciliation."""
    try:
        result = _check_trial_balance(DATA_DIR)
    except (FileNotFoundError, pd.errors.ParserError, ValueError) as error:
        return _failed_result(
            "check_trial_balance",
            tool_context,
            TRIAL_BALANCE_STATUS_KEY,
            str(error),
        )

    stats = result["stats"]
    reasons: list[str] = []
    if not stats["is_balanced"]:
        reasons.append(
            "Trial-balance debits and credits differ by "
            f"INR {stats['difference_inr']}."
        )
    account_differences = stats["account_differences"]
    if account_differences:
        reasons.append(
            "Ledger does not tie to trial_balance.csv for account(s): "
            + ", ".join(sorted(account_differences))
            + "."
        )
    if stats["unknown_accounts"]:
        reasons.append(
            "Trial balance contains account(s) not present in the ledger mapping: "
            + ", ".join(stats["unknown_accounts"])
            + "."
        )
    return _record_result(
        result, tool_context, TRIAL_BALANCE_STATUS_KEY, reasons
    )


def build_intake_agent(model: str | BaseLlm = MODEL) -> LlmAgent:
    """Build the intake LlmAgent, optionally with a deterministic test model."""
    return LlmAgent(
        model=model,
        name="intake_agent",
        description="Validates AuditPilot ledger intake before audit analysis.",
        instruction=(
            "Validate the dataset by calling load_ledger once and then "
            "check_trial_balance once. Always call both tools, even if the "
            "first reports FAILED. Use only facts and values returned by these "
            "tools. Never estimate missing values, invent financial records, "
            "or claim a check passed unless its tool reports PASSED. If either "
            "tool reports FAILED, return status FAILED and copy its reasons. "
            "Return only a JSON object with status, reasons, and tool_results "
            "containing the two tool results. Do not add any other facts."
        ),
        tools=[load_ledger, check_trial_balance],
        output_key="data_profile",
    )


intake_agent = build_intake_agent()
