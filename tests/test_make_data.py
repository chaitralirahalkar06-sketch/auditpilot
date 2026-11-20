from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from scripts.make_data import OUTPUT_FILENAMES, generate_data

EXPECTED_ANOMALY_COUNTS = {
    "duplicate_payment": 10,
    "split_payment": 18,
    "ghost_vendor": 5,
    "shared_bank_account": 3,
    "self_approved": 8,
    "sunday_round_amount": 12,
    "trial_balance_gap": 1,
    "prompt_injection": 4,
}


@pytest.fixture()
def generated_dir(tmp_path: Path) -> Path:
    output_dir = tmp_path / "generated"
    generate_data(output_dir)
    return output_dir


def test_generates_required_files_columns_and_row_counts(
    generated_dir: Path,
) -> None:
    for filename in OUTPUT_FILENAMES:
        assert (generated_dir / filename).is_file()

    ledger = pd.read_csv(generated_dir / "ledger.csv")
    vendors = pd.read_csv(generated_dir / "vendors.csv")
    employees = pd.read_csv(generated_dir / "employees.csv")
    trial_balance = pd.read_csv(generated_dir / "trial_balance.csv")
    financials = pd.read_csv(generated_dir / "financials.csv")
    ground_truth = pd.read_csv(generated_dir / "ground_truth.csv")

    assert len(ledger) == 6_000
    assert len(vendors) == 120
    assert len(employees) == 40
    assert len(financials) == 12
    assert set(ledger.columns) >= {
        "entry_id",
        "date",
        "posted_by",
        "approved_by",
        "account_code",
        "account_name",
        "vendor_id",
        "amount_inr",
        "description",
    }
    assert set(vendors.columns) >= {
        "vendor_id",
        "vendor_name",
        "gstin",
        "pan",
        "bank_account",
        "created_date",
    }
    assert set(employees.columns) >= {
        "employee_id",
        "employee_name",
        "department",
        "job_title",
        "bank_account",
        "start_date",
    }
    assert set(trial_balance.columns) >= {
        "account_code",
        "account_name",
        "debit_inr",
        "credit_inr",
    }
    assert set(financials.columns) >= {
        "month",
        "revenue_inr",
        "expenses_inr",
        "net_income_inr",
        "transaction_count",
    }
    assert set(ground_truth.columns) >= {
        "entry_id",
        "anomaly_type",
        "group_id",
        "entity_id",
    }
    assert (generated_dir / "policy.md").read_text(encoding="utf-8")

    dates = pd.to_datetime(ledger["date"])
    assert dates.min() >= pd.Timestamp("2025-04-01")
    assert dates.max() <= pd.Timestamp("2026-03-31")


def test_ground_truth_counts_match_planted_records(generated_dir: Path) -> None:
    ledger = pd.read_csv(generated_dir / "ledger.csv", dtype={"entry_id": str})
    vendors = pd.read_csv(generated_dir / "vendors.csv", dtype={"vendor_id": str})
    employees = pd.read_csv(
        generated_dir / "employees.csv", dtype={"employee_id": str}
    )
    trial_balance = pd.read_csv(generated_dir / "trial_balance.csv")
    ground_truth = pd.read_csv(
        generated_dir / "ground_truth.csv",
        dtype={"entry_id": str, "entity_id": str},
        keep_default_na=False,
    )
    counts = ground_truth["anomaly_type"].value_counts().to_dict()
    assert counts == EXPECTED_ANOMALY_COUNTS

    duplicate_ids = ground_truth.loc[
        ground_truth["anomaly_type"] == "duplicate_payment", "entry_id"
    ]
    for entry_id in duplicate_ids:
        row = ledger.loc[ledger["entry_id"] == entry_id].iloc[0]
        matches = ledger.loc[
            (ledger["date"] == row["date"])
            & (ledger["vendor_id"] == row["vendor_id"])
            & (ledger["amount_inr"] == row["amount_inr"])
        ]
        assert len(matches) == 2

    split_truth = ground_truth.loc[
        ground_truth["anomaly_type"] == "split_payment"
    ].merge(ledger, on="entry_id")
    assert split_truth["group_id"].nunique() == 6
    for _, group in split_truth.groupby("group_id"):
        assert len(group) == 3
        assert group["amount_inr"].between(45_000, 49_999).all()
        assert group["amount_inr"].sum() > 50_000
        assert group["vendor_id"].nunique() == 1
        assert group["date"].nunique() == 1

    vendor_ids = set(vendors["vendor_id"])
    ghost_truth = ground_truth.loc[ground_truth["anomaly_type"] == "ghost_vendor"]
    ghost_rows = ghost_truth.merge(ledger, on="entry_id")
    assert ghost_truth["entity_id"].nunique() == 5
    assert set(ghost_rows["vendor_id"]).isdisjoint(vendor_ids)

    shared_truth = ground_truth.loc[
        ground_truth["anomaly_type"] == "shared_bank_account"
    ]
    vendor_banks = vendors.set_index("vendor_id")["bank_account"]
    employee_banks = set(employees["bank_account"])
    assert shared_truth["entity_id"].nunique() == 3
    for vendor_id in shared_truth["entity_id"]:
        assert vendor_banks.loc[vendor_id] in employee_banks

    self_approved = ground_truth.loc[
        ground_truth["anomaly_type"] == "self_approved"
    ].merge(ledger, on="entry_id")
    assert (self_approved["posted_by"] == self_approved["approved_by"]).all()

    sunday_rows = ground_truth.loc[
        ground_truth["anomaly_type"] == "sunday_round_amount"
    ].merge(ledger, on="entry_id")
    sunday_dates = pd.to_datetime(sunday_rows["date"])
    assert (sunday_dates.dt.day_of_week == 6).all()
    assert (sunday_rows["amount_inr"] % 10_000 == 0).all()

    injected_rows = ground_truth.loc[
        ground_truth["anomaly_type"] == "prompt_injection"
    ].merge(ledger, on="entry_id")
    assert injected_rows["description"].str.contains(
        r"ignore|system override|assistant:", case=False, regex=True
    ).all()

    assert (
        trial_balance["debit_inr"].sum() - trial_balance["credit_inr"].sum()
    ) == 1


def test_generation_is_byte_for_byte_deterministic(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"
    script = Path(__file__).resolve().parents[1] / "scripts" / "make_data.py"
    command = [
        sys.executable,
        str(script),
        "--output-dir",
        str(output_dir),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    first_run = {
        filename: (output_dir / filename).read_bytes()
        for filename in OUTPUT_FILENAMES
    }
    subprocess.run(command, check=True, capture_output=True, text=True)

    for filename in OUTPUT_FILENAMES:
        assert first_run[filename] == (output_dir / filename).read_bytes()


def test_generation_preserves_unrelated_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"
    output_dir.mkdir()
    unrelated_file = output_dir / "keep.txt"
    unrelated_file.write_text("unrelated content", encoding="utf-8")

    generate_data(output_dir)

    assert unrelated_file.read_text(encoding="utf-8") == "unrelated content"
