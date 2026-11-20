from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from auditpilot.tools import (
    benford_test,
    check_approval_limits,
    check_trial_balance,
    find_duplicates,
    find_split_payments,
    find_weekend_round,
    load_ledger,
    ratio_table,
    vendor_bank_overlap,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RESULT_KEYS = {"test", "flagged_ids", "stats", "notes"}


@pytest.fixture(scope="module")
def ground_truth() -> pd.DataFrame:
    return pd.read_csv(
        DATA_DIR / "ground_truth.csv",
        dtype={"entry_id": str, "entity_id": str},
        keep_default_na=False,
    )


def _assert_result_shape(result: dict[str, object]) -> None:
    assert RESULT_KEYS <= result.keys()
    assert isinstance(result["test"], str)
    assert isinstance(result["flagged_ids"], list)
    assert isinstance(result["stats"], dict)
    assert isinstance(result["notes"], list)
    json.dumps(result, allow_nan=False)


def _assert_recall(
    result: dict[str, object],
    truth: pd.DataFrame,
    anomaly_type: str,
) -> None:
    truth_ids = set(
        truth.loc[
            (truth["anomaly_type"] == anomaly_type) & truth["entry_id"].ne(""),
            "entry_id",
        ]
    )
    assert truth_ids
    predicted_ids = set(result["flagged_ids"])
    recall = len(truth_ids & predicted_ids) / len(truth_ids)
    assert recall >= 0.9, f"{anomaly_type} recall was {recall:.1%}"


def test_load_ledger_retains_ground_truth_entry_ids(
    ground_truth: pd.DataFrame,
) -> None:
    result = load_ledger(DATA_DIR)
    _assert_result_shape(result)
    ledger = pd.read_csv(
        DATA_DIR / "ledger.csv", dtype={"entry_id": str}, keep_default_na=False
    )
    assert len(ledger) == result["stats"]["rows_loaded"] == 6_000
    truth_ids = set(ground_truth.loc[ground_truth["entry_id"].ne(""), "entry_id"])
    assert truth_ids <= set(ledger["entry_id"])
    assert result["stats"]["rows_retained"] == 6_000


def test_check_trial_balance_finds_seeded_account_gap(
    ground_truth: pd.DataFrame,
) -> None:
    result = check_trial_balance(DATA_DIR)
    _assert_result_shape(result)
    truth = ground_truth.loc[
        ground_truth["anomaly_type"] == "trial_balance_gap", "entity_id"
    ]
    expected_accounts = {value.removeprefix("TB-") for value in truth}
    assert result["stats"]["difference_inr"] == 1
    assert expected_accounts <= set(result["stats"]["flagged_accounts"])
    assert result["flagged_ids"] == []
    assert any("no entry_id" in note for note in result["notes"])


def test_benford_test_reports_all_amounts_without_dropping_rows() -> None:
    result = benford_test(DATA_DIR)
    _assert_result_shape(result)
    assert sum(result["stats"]["observed_counts"].values()) == 6_000
    assert result["stats"]["rows_analyzed"] == 6_000
    ledger_ids = set(pd.read_csv(DATA_DIR / "ledger.csv")["entry_id"])
    assert set(result["flagged_ids"]) <= ledger_ids


def test_find_duplicates_recalls_seeded_duplicate_payments(
    ground_truth: pd.DataFrame,
) -> None:
    result = find_duplicates(DATA_DIR)
    _assert_result_shape(result)
    _assert_recall(result, ground_truth, "duplicate_payment")


def test_find_split_payments_recalls_seeded_groups(
    ground_truth: pd.DataFrame,
) -> None:
    result = find_split_payments(DATA_DIR)
    _assert_result_shape(result)
    _assert_recall(result, ground_truth, "split_payment")
    assert result["stats"]["approval_limit_inr"] == 50_000


def test_find_weekend_round_recalls_seeded_sunday_payments(
    ground_truth: pd.DataFrame,
) -> None:
    result = find_weekend_round(DATA_DIR)
    _assert_result_shape(result)
    _assert_recall(result, ground_truth, "sunday_round_amount")


def test_check_approval_limits_recalls_self_approval(
    ground_truth: pd.DataFrame,
) -> None:
    result = check_approval_limits(DATA_DIR)
    _assert_result_shape(result)
    _assert_recall(result, ground_truth, "self_approved")
    assert result["stats"]["self_approved_count"] == 8


def test_vendor_bank_overlap_recalls_ghost_and_shared_vendors(
    ground_truth: pd.DataFrame,
) -> None:
    result = vendor_bank_overlap(DATA_DIR)
    _assert_result_shape(result)
    _assert_recall(result, ground_truth, "ghost_vendor")
    truth_vendor_ids = set(
        ground_truth.loc[
            ground_truth["anomaly_type"] == "shared_bank_account", "entity_id"
        ]
    )
    predicted_vendor_ids = set(result["stats"]["shared_vendor_ids"])
    assert len(truth_vendor_ids & predicted_vendor_ids) / len(truth_vendor_ids) >= 0.9


def test_ratio_table_returns_all_monthly_periods() -> None:
    result = ratio_table(DATA_DIR)
    _assert_result_shape(result)
    assert result["stats"]["period_count"] == 12
    assert len(result["stats"]["ratios"]) == 12
    assert all(
        {"month", "net_margin", "expense_to_revenue"} <= row.keys()
        for row in result["stats"]["ratios"]
    )
    assert result["flagged_ids"] == []


def test_load_ledger_rejects_bad_rows_instead_of_dropping_them(
    tmp_path: Path,
) -> None:
    source = pd.read_csv(DATA_DIR / "ledger.csv")
    invalid_row = source.iloc[[0]].copy()
    invalid_row["entry_id"] = "LE-INVALID"
    invalid_row["amount_inr"] = "not-an-amount"
    pd.concat([source, invalid_row], ignore_index=True).to_csv(
        tmp_path / "ledger.csv", index=False
    )

    with pytest.raises(ValueError):
        load_ledger(tmp_path)
