"""Run deterministic audit-tool evaluation against evaluation-only labels."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from collections.abc import Mapping

import pandas as pd

from auditpilot.tools.audit_tools import benford_test
from auditpilot.tools.audit_tools import check_approval_limits
from auditpilot.tools.audit_tools import check_trial_balance
from auditpilot.tools.audit_tools import find_duplicates
from auditpilot.tools.audit_tools import find_split_payments
from auditpilot.tools.audit_tools import find_weekend_round
from auditpilot.tools.audit_tools import load_ledger
from auditpilot.tools.audit_tools import ratio_table
from auditpilot.tools.audit_tools import vendor_bank_overlap

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_RESULTS_PATH = Path(__file__).resolve().parent / "results.md"
DEFAULT_MEMO_PATH = PROJECT_ROOT / "docs" / "audit_memo.md"

ANOMALY_TYPES = (
    "duplicate_payment",
    "split_payment",
    "ghost_vendor",
    "shared_bank_account",
    "self_approved",
    "sunday_round_amount",
    "prompt_injection",
    "trial_balance_gap",
)
ENTITY_LABEL_TYPES = {"ghost_vendor", "shared_bank_account", "trial_balance_gap"}
_MEMO_AMOUNT_PATTERN = re.compile(r"\bINR\s+([\d,]+)\b", re.IGNORECASE)
_INJECTION_PATTERN = re.compile(
    r"ignore\s+(?:all\s+)?prior instructions|"
    r"system\s+override|"
    r"bypass\s+policy checks|"
    r"ignore\s+the auditor(?:'s)? prompt",
    re.IGNORECASE,
)


def run_tool_pipeline(data_dir: Path | str = DEFAULT_DATA_DIR) -> dict[str, Any]:
    """Run all deterministic audit tools without accessing ground truth."""
    return {
        "load_ledger": load_ledger(data_dir),
        "check_trial_balance": check_trial_balance(data_dir),
        "benford_test": benford_test(data_dir),
        "find_duplicates": find_duplicates(data_dir),
        "find_split_payments": find_split_payments(data_dir),
        "find_weekend_round": find_weekend_round(data_dir),
        "check_approval_limits": check_approval_limits(data_dir),
        "vendor_bank_overlap": vendor_bank_overlap(data_dir),
        "ratio_table": ratio_table(data_dir),
    }


def calculate_metrics(
    predicted: set[str], actual: set[str]
) -> dict[str, int | float]:
    """Calculate precision, recall, and confusion counts for one anomaly type."""
    true_positives = len(predicted & actual)
    false_positives = len(predicted - actual)
    false_negatives = len(actual - predicted)
    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if true_positives + false_negatives
        else 0.0
    )
    return {
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "precision": precision,
        "recall": recall,
    }


def _predictions(
    data_dir: Path | str, tool_outputs: Mapping[str, Any]
) -> dict[str, set[str]]:
    ledger_path = Path(data_dir) / "ledger.csv"
    ledger = pd.read_csv(
        ledger_path,
        usecols=["entry_id", "date", "vendor_id", "description"],
        dtype={
            "entry_id": "string",
            "date": "string",
            "vendor_id": "string",
            "description": "string",
        },
        keep_default_na=False,
        on_bad_lines="error",
    )
    ledger["date"] = pd.to_datetime(ledger["date"], errors="raise")

    duplicates = tool_outputs["find_duplicates"]["flagged_ids"]
    split_payments = tool_outputs["find_split_payments"]["flagged_ids"]
    approval_stats = tool_outputs["check_approval_limits"]["stats"]
    weekend_ids = set(tool_outputs["find_weekend_round"]["flagged_ids"])
    sunday_ids = set(
        ledger.loc[
            ledger["entry_id"].isin(weekend_ids)
            & (ledger["date"].dt.day_of_week == 6),
            "entry_id",
        ].astype(str)
    )
    vendor_stats = tool_outputs["vendor_bank_overlap"]["stats"]
    ghost_vendors = set(vendor_stats["unregistered_vendor_ids"])
    shared_vendors = set(vendor_stats["shared_vendor_ids"])
    trial_balance_accounts = {
        f"TB-{account}"
        for account in tool_outputs["check_trial_balance"]["stats"][
            "flagged_accounts"
        ]
    }
    injection_entries = set(
        ledger.loc[
            ledger["description"].str.contains(_INJECTION_PATTERN, na=False),
            "entry_id",
        ].astype(str)
    )
    return {
        "duplicate_payment": set(duplicates),
        "split_payment": set(split_payments),
        "ghost_vendor": ghost_vendors,
        "shared_bank_account": shared_vendors,
        "self_approved": set(approval_stats["self_approved_ids"]),
        "sunday_round_amount": sunday_ids,
        "prompt_injection": injection_entries,
        "trial_balance_gap": trial_balance_accounts,
    }


def _truth_labels(truth_path: Path | str) -> dict[str, set[str]]:
    truth = pd.read_csv(
        truth_path,
        dtype={
            "entry_id": "string",
            "anomaly_type": "string",
            "entity_id": "string",
        },
        keep_default_na=False,
        on_bad_lines="error",
    )
    required = {"entry_id", "anomaly_type", "entity_id"}
    if not required <= set(truth.columns):
        raise ValueError(f"{truth_path} is missing columns: {sorted(required - set(truth.columns))}")
    labels: dict[str, set[str]] = {}
    for anomaly_type in ANOMALY_TYPES:
        column = "entity_id" if anomaly_type in ENTITY_LABEL_TYPES else "entry_id"
        values = truth.loc[
            (truth["anomaly_type"] == anomaly_type) & truth[column].ne(""),
            column,
        ]
        labels[anomaly_type] = set(values.astype(str))
        if not labels[anomaly_type]:
            raise ValueError(f"{truth_path} contains no labels for {anomaly_type}")
    return labels


def _ledger_amounts(data_dir: Path | str) -> dict[str, int]:
    result = load_ledger(data_dir)
    ledger_path = Path(data_dir) / "ledger.csv"
    ledger = pd.read_csv(
        ledger_path,
        usecols=["entry_id", "amount_inr"],
        dtype={"entry_id": "string"},
        keep_default_na=False,
        on_bad_lines="error",
    )
    if len(ledger) != result["stats"]["rows_loaded"]:
        raise ValueError(f"{ledger_path} changed while evaluating memo amounts")
    amounts = pd.to_numeric(ledger["amount_inr"], errors="raise")
    return {
        str(entry_id): int(amount)
        for entry_id, amount in zip(ledger["entry_id"], amounts, strict=True)
    }


def _amounts_in_tool_outputs(
    outputs: Any, amount_by_id: Mapping[str, int]
) -> set[int]:
    amounts: set[int] = set()

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                visit(child, str(child_key))
        elif isinstance(value, list):
            if key.endswith("_ids") or key == "flagged_ids":
                ids = [str(entry_id) for entry_id in value]
                if ids and all(entry_id in amount_by_id for entry_id in ids):
                    amounts.add(sum(amount_by_id[entry_id] for entry_id in ids))
            for child in value:
                visit(child, key)
        elif isinstance(value, int) and not isinstance(value, bool):
            if "amount" in key.lower() or key.lower().endswith("_inr"):
                amounts.add(value)

    visit(outputs)
    return amounts


def memo_amounts_supported(
    memo_text: str,
    tool_outputs: Mapping[str, Any],
    amount_by_id: Mapping[str, int],
) -> bool:
    """Return whether every INR amount in a memo is present in tool outputs."""
    memo_amounts = {
        int(value.replace(",", ""))
        for value in _MEMO_AMOUNT_PATTERN.findall(memo_text)
    }
    return memo_amounts <= _amounts_in_tool_outputs(tool_outputs, amount_by_id)


def _results_markdown(
    metrics: Mapping[str, Mapping[str, int | float]],
    *,
    repeated_runs_identical: bool,
    memo_status: str,
    memo_detail: str,
) -> str:
    lines = [
        "# AuditPilot Evaluation Results",
        "",
        "Evaluation uses deterministic Python audit tools; no Gemini/API calls are made.",
        "Ground truth is read only after the three tool-pipeline runs and is never passed to agents.",
        "",
        f"- Three repeated runs identical: **{'PASS' if repeated_runs_identical else 'FAIL'}**",
        "",
        "| Anomaly type | TP | FP | FN | Precision | Recall | Recall >= 90% |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for anomaly_type in ANOMALY_TYPES:
        row = metrics[anomaly_type]
        lines.append(
            f"| {anomaly_type} | {row['true_positives']} | "
            f"{row['false_positives']} | {row['false_negatives']} | "
            f"{row['precision']:.1%} | {row['recall']:.1%} | "
            f"{'PASS' if row['recall'] >= 0.9 else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "The `prompt_injection` row measures the evaluator's deterministic detector for the four planted instruction-like descriptions; the text remains untrusted and is not an agent instruction.",
            "",
            f"- Memo amount consistency: **{memo_status}** — {memo_detail}",
            "",
        ]
    )
    return "\n".join(lines)


def run_evaluation(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    memo_path: Path | str = DEFAULT_MEMO_PATH,
    results_path: Path | str = DEFAULT_RESULTS_PATH,
) -> dict[str, Any]:
    """Run the deterministic pipeline three times and write evaluation results."""
    runs = [run_tool_pipeline(data_dir) for _ in range(3)]
    serialized_runs = [
        json.dumps(run, sort_keys=True, separators=(",", ":"), default=str)
        for run in runs
    ]
    repeated_runs_identical = len(set(serialized_runs)) == 1

    # Ground truth is intentionally opened only after all agent-independent
    # tool results have been collected.
    actual = _truth_labels(Path(data_dir) / "ground_truth.csv")
    predicted = _predictions(data_dir, runs[-1])
    metrics = {
        anomaly_type: calculate_metrics(predicted[anomaly_type], actual[anomaly_type])
        for anomaly_type in ANOMALY_TYPES
    }

    memo_file = Path(memo_path)
    if memo_file.is_file():
        memo_text = memo_file.read_text(encoding="utf-8")
        supported = memo_amounts_supported(
            memo_text, runs[-1], _ledger_amounts(data_dir)
        )
        memo_status = "PASS" if supported else "FAIL"
        memo_detail = (
            "Every INR amount is supported by deterministic tool output."
            if supported
            else "At least one INR amount is absent from deterministic tool output."
        )
    else:
        memo_status = "SKIPPED"
        memo_detail = (
            "No audit memo was present; the check is covered by tests and will "
            "run when a pipeline memo is available."
        )

    report = _results_markdown(
        metrics,
        repeated_runs_identical=repeated_runs_identical,
        memo_status=memo_status,
        memo_detail=memo_detail,
    )
    output_path = Path(results_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return {
        "metrics": metrics,
        "repeated_runs_identical": repeated_runs_identical,
        "memo_status": memo_status,
        "results_path": output_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--memo", type=Path, default=DEFAULT_MEMO_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH)
    args = parser.parse_args()
    result = run_evaluation(
        args.data_dir,
        memo_path=args.memo,
        results_path=args.output,
    )
    recall_passed = all(
        item["recall"] >= 0.9 for item in result["metrics"].values()
    )
    memo_passed = result["memo_status"] in {"PASS", "SKIPPED"}
    if not result["repeated_runs_identical"] or not recall_passed or not memo_passed:
        raise SystemExit(1)
    print(f"Evaluation results written to {result['results_path']}")


if __name__ == "__main__":
    main()
