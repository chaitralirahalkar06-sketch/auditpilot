"""Pure pandas audit checks for the fictional AuditPilot financial dataset."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, TypedDict

import pandas as pd

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

LEDGER_COLUMNS = (
    "entry_id",
    "date",
    "posted_by",
    "approved_by",
    "account_code",
    "account_name",
    "vendor_id",
    "amount_inr",
    "description",
)


class ToolResult(TypedDict):
    """Common result shape returned by public audit tools."""

    test: str
    flagged_ids: list[str]
    stats: dict[str, Any]
    notes: list[str]


def _result(
    test: str,
    flagged_ids: list[str],
    stats: dict[str, Any],
    notes: list[str],
) -> ToolResult:
    """Build the consistent, JSON-serializable public result shape."""
    return {
        "test": test,
        "flagged_ids": sorted(set(flagged_ids)),
        "stats": stats,
        "notes": notes,
    }


def _read_table(
    data_dir: Path | str,
    filename: str,
    required_columns: tuple[str, ...],
    *,
    text_columns: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Read a CSV and reject missing required columns or malformed lines."""
    path = Path(data_dir) / filename
    frame = pd.read_csv(
        path,
        dtype={column: "string" for column in text_columns},
        keep_default_na=False,
        on_bad_lines="error",
    )
    missing_columns = sorted(set(required_columns) - set(frame.columns))
    if missing_columns:
        raise ValueError(
            f"{path} is missing required columns: {', '.join(missing_columns)}"
        )
    return frame


def _require_nonblank(frame: pd.DataFrame, columns: tuple[str, ...], source: str) -> None:
    """Raise an explicit error when required identity fields are blank."""
    for column in columns:
        values = frame[column].astype("string")
        blank = values.isna() | values.str.strip().eq("")
        if blank.any():
            raise ValueError(
                f"{source} contains {int(blank.sum())} blank values in {column!r}"
            )


def _numeric_column(frame: pd.DataFrame, column: str, source: str) -> pd.Series:
    """Parse a numeric column and reject missing or non-finite values."""
    values = pd.to_numeric(frame[column], errors="raise")
    if values.isna().any() or not values.map(math.isfinite).all():
        raise ValueError(f"{source} contains missing or non-finite {column!r} values")
    return values


def _read_ledger_frame(data_dir: Path | str) -> pd.DataFrame:
    """Return a validated ledger DataFrame without removing any rows."""
    ledger = _read_table(
        data_dir,
        "ledger.csv",
        LEDGER_COLUMNS,
        text_columns=(
            "entry_id",
            "date",
            "posted_by",
            "approved_by",
            "account_code",
            "account_name",
            "vendor_id",
            "description",
        ),
    )
    _require_nonblank(
        ledger,
        (
            "entry_id",
            "date",
            "posted_by",
            "approved_by",
            "account_code",
            "account_name",
            "vendor_id",
            "amount_inr",
        ),
        "ledger.csv",
    )
    if ledger["entry_id"].duplicated().any():
        duplicate_ids = sorted(
            ledger.loc[ledger["entry_id"].duplicated(keep=False), "entry_id"]
            .astype(str)
            .unique()
        )
        raise ValueError(f"ledger.csv contains duplicate entry_id values: {duplicate_ids}")

    dates = pd.to_datetime(ledger["date"], errors="raise")
    if dates.isna().any():
        raise ValueError("ledger.csv contains missing or invalid dates")
    amounts = _numeric_column(ledger, "amount_inr", "ledger.csv")
    if (amounts <= 0).any() or (amounts % 1 != 0).any():
        raise ValueError("ledger.csv amount_inr values must be positive whole INR")

    ledger["date"] = dates
    ledger["amount_inr"] = amounts.astype("int64")
    return ledger


def load_ledger(data_dir: Path | str = DEFAULT_DATA_DIR) -> ToolResult:
    """Validate and summarize every ledger row without filtering records."""
    ledger = _read_ledger_frame(data_dir)
    row_count = len(ledger)
    return _result(
        "load_ledger",
        [],
        {
            "rows_loaded": row_count,
            "rows_retained": row_count,
            "columns": list(ledger.columns),
            "min_date": (
                ledger["date"].min().strftime("%Y-%m-%d") if row_count else None
            ),
            "max_date": (
                ledger["date"].max().strftime("%Y-%m-%d") if row_count else None
            ),
        },
        ["All ledger rows were retained; malformed or incomplete data raises an error."],
    )


def _ledger_frame(data_dir: Path | str) -> pd.DataFrame:
    """Load the validated ledger used by transaction-level checks."""
    return _read_ledger_frame(data_dir)


def _policy_text(data_dir: Path | str) -> str:
    """Read the non-empty company policy document."""
    path = Path(data_dir) / "policy.md"
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"{path} is empty")
    return text


def _approval_limit(data_dir: Path | str) -> int:
    """Extract the single-approver INR limit from the company policy."""
    policy = _policy_text(data_dir)
    match = re.search(r"\bbelow\s+INR\s+([\d,]+)", policy, flags=re.IGNORECASE)
    if match is None:
        raise ValueError(
            "policy.md must specify the single-approver limit as 'below INR <amount>'"
        )
    limit = int(match.group(1).replace(",", ""))
    if limit <= 0:
        raise ValueError("policy.md approval limit must be greater than zero")
    return limit


def check_trial_balance(data_dir: Path | str = DEFAULT_DATA_DIR) -> ToolResult:
    """Compare trial-balance totals and account balances to the ledger."""
    ledger = _ledger_frame(data_dir)
    trial_balance = _read_table(
        data_dir,
        "trial_balance.csv",
        ("account_code", "account_name", "debit_inr", "credit_inr"),
        text_columns=("account_code", "account_name"),
    )
    _require_nonblank(trial_balance, ("account_code", "account_name"), "trial_balance.csv")
    for column in ("debit_inr", "credit_inr"):
        trial_balance[column] = _numeric_column(
            trial_balance, column, "trial_balance.csv"
        )
        if (trial_balance[column] < 0).any():
            raise ValueError(f"trial_balance.csv {column} values cannot be negative")

    actual = trial_balance.groupby("account_code", dropna=False)[
        ["debit_inr", "credit_inr"]
    ].sum()
    ledger_totals = ledger.groupby("account_code")["amount_inr"].sum().to_dict()
    revenue = int(ledger_totals.get("4000", 0))
    expenses = {
        str(code): int(amount)
        for code, amount in ledger_totals.items()
        if str(code) != "4000"
    }
    expected: dict[str, tuple[int, int]] = {
        "1010": (revenue, sum(expenses.values())),
        "4000": (0, revenue),
    }
    expected.update({code: (amount, 0) for code, amount in expenses.items()})

    flagged_accounts: list[str] = []
    account_differences: dict[str, dict[str, int]] = {}
    for account_code, (expected_debit, expected_credit) in expected.items():
        if account_code not in actual.index:
            flagged_accounts.append(account_code)
            account_differences[account_code] = {
                "expected_debit_inr": expected_debit,
                "expected_credit_inr": expected_credit,
                "actual_debit_inr": 0,
                "actual_credit_inr": 0,
            }
            continue
        actual_debit = int(actual.loc[account_code, "debit_inr"])
        actual_credit = int(actual.loc[account_code, "credit_inr"])
        if (actual_debit, actual_credit) != (expected_debit, expected_credit):
            flagged_accounts.append(account_code)
            account_differences[account_code] = {
                "expected_debit_inr": expected_debit,
                "expected_credit_inr": expected_credit,
                "actual_debit_inr": actual_debit,
                "actual_credit_inr": actual_credit,
            }

    unknown_accounts = sorted(set(actual.index.astype(str)) - set(expected))
    flagged_accounts.extend(unknown_accounts)
    debit_total = int(trial_balance["debit_inr"].sum())
    credit_total = int(trial_balance["credit_inr"].sum())
    difference = debit_total - credit_total
    notes = [
        "Trial-balance rows have no entry_id; account findings are reported by account_code."
    ]
    if difference == 0 and not flagged_accounts:
        notes.append("Debit and credit totals agree and account balances match the ledger.")

    return _result(
        "check_trial_balance",
        [],
        {
            "debit_total_inr": debit_total,
            "credit_total_inr": credit_total,
            "difference_inr": difference,
            "is_balanced": difference == 0,
            "flagged_accounts": sorted(set(flagged_accounts)),
            "account_differences": account_differences,
            "unknown_accounts": unknown_accounts,
        },
        notes,
    )


def benford_test(data_dir: Path | str = DEFAULT_DATA_DIR) -> ToolResult:
    """Compare positive ledger amount first digits with Benford proportions."""
    ledger = _ledger_frame(data_dir)
    first_digits = ledger["amount_inr"].map(lambda amount: int(str(int(amount))[0]))
    row_count = len(first_digits)
    observed_counts = first_digits.value_counts().reindex(range(1, 10), fill_value=0)
    expected_probabilities = {
        digit: math.log10(1 + 1 / digit) for digit in range(1, 10)
    }
    expected_counts = {
        digit: row_count * probability
        for digit, probability in expected_probabilities.items()
    }
    chi_square = sum(
        (int(observed_counts.loc[digit]) - expected_counts[digit]) ** 2
        / expected_counts[digit]
        for digit in range(1, 10)
    )
    standardized_residuals = {
        digit: (
            int(observed_counts.loc[digit]) - expected_counts[digit]
        )
        / math.sqrt(expected_counts[digit])
        for digit in range(1, 10)
    }
    flagged_digits = sorted(
        digit
        for digit, residual in standardized_residuals.items()
        if abs(residual) >= 2
    )
    flagged_ids = ledger.loc[
        first_digits.isin(flagged_digits), "entry_id"
    ].astype(str).tolist()
    return _result(
        "benford_test",
        flagged_ids,
        {
            "rows_analyzed": row_count,
            "observed_counts": {
                str(digit): int(observed_counts.loc[digit])
                for digit in range(1, 10)
            },
            "expected_probabilities": {
                str(digit): probability
                for digit, probability in expected_probabilities.items()
            },
            "chi_square_statistic": chi_square,
            "chi_square_critical_value_5pct_df8": 15.507,
            "flagged_leading_digits": flagged_digits,
            "standardized_residuals": {
                str(digit): residual
                for digit, residual in standardized_residuals.items()
            },
        },
        [
            "Benford is a population-level screening test, not proof that an individual entry is fraudulent.",
            "flagged_ids identify entries contributing to leading digits with an absolute standardized residual of at least 2.",
        ],
    )


def find_duplicates(data_dir: Path | str = DEFAULT_DATA_DIR) -> ToolResult:
    """Find later ledger rows matching vendor, date, and amount."""
    ledger = _ledger_frame(data_dir)
    duplicate_mask = ledger.duplicated(
        subset=["vendor_id", "date", "amount_inr"], keep="first"
    )
    duplicate_rows = ledger.loc[duplicate_mask]
    duplicate_groups = int(
        ledger.loc[duplicate_mask]
        .groupby(["vendor_id", "date", "amount_inr"], dropna=False)
        .ngroups
    )
    return _result(
        "find_duplicates",
        duplicate_rows["entry_id"].astype(str).tolist(),
        {
            "duplicate_entry_count": len(duplicate_rows),
            "duplicate_group_count": duplicate_groups,
            "matching_fields": ["vendor_id", "date", "amount_inr"],
        },
        [
            "Invoice identifiers are not present in the ledger; vendor, date, and amount are used as the duplicate key, per policy."
        ],
    )


def find_split_payments(data_dir: Path | str = DEFAULT_DATA_DIR) -> ToolResult:
    """Find same-vendor, same-day groups of sub-limit payments totaling the limit."""
    ledger = _ledger_frame(data_dir)
    limit = _approval_limit(data_dir)
    candidates = ledger.loc[ledger["amount_inr"] < limit]
    groups = candidates.groupby(["vendor_id", "date"], dropna=False, sort=True)
    flagged_groups: list[pd.DataFrame] = []
    for _, group in groups:
        if len(group) >= 3 and int(group["amount_inr"].sum()) >= limit:
            flagged_groups.append(group)

    if flagged_groups:
        flagged_rows = pd.concat(flagged_groups, ignore_index=False)
    else:
        flagged_rows = ledger.iloc[0:0]
    return _result(
        "find_split_payments",
        flagged_rows["entry_id"].astype(str).tolist(),
        {
            "approval_limit_inr": limit,
            "candidate_group_count": len(flagged_groups),
            "flagged_entry_count": len(flagged_rows),
            "grouping_fields": ["vendor_id", "date"],
        },
        [
            "Groups require at least three same-vendor, same-day payments below the policy limit whose combined amount reaches that limit."
        ],
    )


def find_weekend_round(data_dir: Path | str = DEFAULT_DATA_DIR) -> ToolResult:
    """Flag weekend payments whose amount is a multiple of INR 10,000."""
    ledger = _ledger_frame(data_dir)
    weekend_mask = ledger["date"].dt.day_of_week >= 5
    round_mask = ledger["amount_inr"] % 10_000 == 0
    flagged = ledger.loc[weekend_mask & round_mask]
    return _result(
        "find_weekend_round",
        flagged["entry_id"].astype(str).tolist(),
        {
            "weekend_entry_count": int(weekend_mask.sum()),
            "round_amount_entry_count": int(round_mask.sum()),
            "flagged_entry_count": len(flagged),
            "weekend_definition": "Saturday or Sunday",
            "round_amount_multiple_inr": 10_000,
        },
        [
            "Policy specifically requires documented authorization for Sunday payments; Saturday round payments are also included for weekend review."
        ],
    )


def check_approval_limits(data_dir: Path | str = DEFAULT_DATA_DIR) -> ToolResult:
    """Flag self-approval, large payments, and related split payments."""
    ledger = _ledger_frame(data_dir)
    limit = _approval_limit(data_dir)
    self_approved = ledger["posted_by"] == ledger["approved_by"]
    at_or_above_limit = ledger["amount_inr"] >= limit
    split_payment_result = find_split_payments(data_dir)
    self_approved_ids = ledger.loc[self_approved, "entry_id"].astype(str).tolist()
    large_payment_ids = ledger.loc[
        at_or_above_limit, "entry_id"
    ].astype(str).tolist()
    split_payment_ids = split_payment_result["flagged_ids"]
    flagged_ids = self_approved_ids + large_payment_ids + split_payment_ids
    return _result(
        "check_approval_limits",
        flagged_ids,
        {
            "approval_limit_inr": limit,
            "self_approved_count": int(self_approved.sum()),
            "self_approved_ids": self_approved_ids,
            "at_or_above_limit_count": int(at_or_above_limit.sum()),
            "at_or_above_limit_ids": large_payment_ids,
            "split_payment_group_count": split_payment_result["stats"][
                "candidate_group_count"
            ],
            "split_payment_entry_count": len(split_payment_ids),
            "split_payment_ids": split_payment_ids,
            "flagged_entry_count": len(set(flagged_ids)),
        },
        [
            "Self-approval is prohibited by policy.",
            "Amounts at or above the limit require additional finance review; the ledger has only one approver field, so the additional review cannot be verified from this file.",
            "Related same-vendor, same-day payments below the limit are considered together when three or more payments total at least the limit.",
        ],
    )


def vendor_bank_overlap(data_dir: Path | str = DEFAULT_DATA_DIR) -> ToolResult:
    """Find ledger entries for unregistered vendors and shared vendor-employee banks."""
    ledger = _ledger_frame(data_dir)
    vendors = _read_table(
        data_dir,
        "vendors.csv",
        ("vendor_id", "bank_account"),
        text_columns=("vendor_id", "bank_account"),
    )
    employees = _read_table(
        data_dir,
        "employees.csv",
        ("employee_id", "bank_account"),
        text_columns=("employee_id", "bank_account"),
    )
    _require_nonblank(vendors, ("vendor_id",), "vendors.csv")
    _require_nonblank(employees, ("employee_id",), "employees.csv")
    if vendors["vendor_id"].duplicated().any():
        raise ValueError("vendors.csv contains duplicate vendor_id values")
    if employees["employee_id"].duplicated().any():
        raise ValueError("employees.csv contains duplicate employee_id values")

    def normalize_account(value: object) -> str:
        """Normalize a bank-account token for exact, case-insensitive matching."""
        return str(value).strip().casefold()

    employee_accounts: dict[str, list[str]] = {}
    for employee_id, account in employees[
        ["employee_id", "bank_account"]
    ].itertuples(index=False, name=None):
        normalized = normalize_account(account)
        if normalized:
            employee_accounts.setdefault(normalized, []).append(str(employee_id))

    shared_matches: list[dict[str, object]] = []
    for vendor_id, account in vendors[
        ["vendor_id", "bank_account"]
    ].itertuples(index=False, name=None):
        normalized = normalize_account(account)
        if normalized and normalized in employee_accounts:
            shared_matches.append(
                {
                    "vendor_id": str(vendor_id),
                    "employee_ids": sorted(employee_accounts[normalized]),
                }
            )

    vendor_ids = set(vendors["vendor_id"].astype(str))
    ledger_vendor_ids = ledger["vendor_id"].astype(str)
    ghost_rows = ledger.loc[~ledger_vendor_ids.isin(vendor_ids)]
    shared_vendor_ids = sorted(
        str(match["vendor_id"]) for match in shared_matches
    )
    shared_rows = ledger.loc[ledger_vendor_ids.isin(shared_vendor_ids)]
    flagged_ids = (
        ghost_rows["entry_id"].astype(str).tolist()
        + shared_rows["entry_id"].astype(str).tolist()
    )
    blank_vendor_accounts = int(
        vendors["bank_account"].astype("string").str.strip().eq("").sum()
    )
    blank_employee_accounts = int(
        employees["bank_account"].astype("string").str.strip().eq("").sum()
    )
    notes = [
        "Ledger entries for vendor IDs absent from vendors.csv are treated as unregistered-vendor findings."
    ]
    if shared_matches:
        notes.append("Vendor bank accounts were compared to employee bank accounts.")
    if blank_vendor_accounts or blank_employee_accounts:
        notes.append(
            "Blank bank-account values were retained but cannot participate in overlap matching."
        )
    return _result(
        "vendor_bank_overlap",
        flagged_ids,
        {
            "unregistered_vendor_ids": sorted(
                ghost_rows["vendor_id"].astype(str).unique().tolist()
            ),
            "unregistered_vendor_entry_count": len(ghost_rows),
            "shared_account_matches": shared_matches,
            "shared_vendor_ids": shared_vendor_ids,
            "shared_account_entry_ids": shared_rows["entry_id"]
            .astype(str)
            .tolist(),
            "blank_vendor_bank_accounts": blank_vendor_accounts,
            "blank_employee_bank_accounts": blank_employee_accounts,
        },
        notes,
    )


def ratio_table(data_dir: Path | str = DEFAULT_DATA_DIR) -> ToolResult:
    """Calculate monthly net margin and expense-to-revenue ratios."""
    financials = _read_table(
        data_dir,
        "financials.csv",
        ("month", "revenue_inr", "expenses_inr", "net_income_inr"),
        text_columns=("month",),
    )
    _require_nonblank(financials, ("month",), "financials.csv")
    for column in ("revenue_inr", "expenses_inr", "net_income_inr"):
        financials[column] = _numeric_column(
            financials, column, "financials.csv"
        )

    rows: list[dict[str, str | float | None]] = []
    undefined_months: list[str] = []
    for row in financials.itertuples(index=False):
        month = str(row.month)
        revenue = float(row.revenue_inr)
        expenses = float(row.expenses_inr)
        net_income = float(row.net_income_inr)
        if revenue == 0:
            net_margin: float | None = None
            expense_ratio: float | None = None
            undefined_months.append(month)
        else:
            net_margin = net_income / revenue
            expense_ratio = expenses / revenue
        rows.append(
            {
                "month": month,
                "net_margin": net_margin,
                "expense_to_revenue": expense_ratio,
            }
        )

    notes = [
        "Ratios are monthly aggregates; financials.csv contains no entry_id values."
    ]
    if undefined_months:
        notes.append(
            f"Ratios are undefined for zero-revenue months: {', '.join(undefined_months)}."
        )
    return _result(
        "ratio_table",
        [],
        {
            "period_count": len(rows),
            "ratios": rows,
            "undefined_ratio_months": undefined_months,
        },
        notes,
    )
