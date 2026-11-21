"""ADK audit callbacks and model-facing sensitive-data masking."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import re
import threading
from collections.abc import Mapping
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.context import Context
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.genai import types

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
AUDIT_TRAIL_PATH = Path(__file__).resolve().parents[1] / "audit_trail.jsonl"

_AUDIT_LOCK = threading.Lock()
_ACCOUNT_NUMBER_PATTERN = re.compile(r"(?<!\d)(?:\d[ ]?){8,18}(?!\d)")
_API_CREDENTIAL_PATTERN = re.compile(
    r"\b(?:AIza[0-9A-Za-z_-]{20,}|"
    r"(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{20,})\b"
)
_LABELED_SECRET_PATTERN = re.compile(
    r"(?i)(\b(?:api[_ -]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+"
)


def _canonical_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _load_bank_accounts(data_dir: Path | str) -> set[str]:
    accounts: set[str] = set()
    for filename in ("vendors.csv", "employees.csv"):
        path = Path(data_dir) / filename
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if "bank_account" not in (reader.fieldnames or []):
                raise ValueError(f"{path} is missing the bank_account column")
            accounts.update(
                value.strip()
                for row in reader
                if (value := row["bank_account"]).strip()
            )
    return accounts


def mask_sensitive_text(
    text: str, bank_accounts: set[str] | frozenset[str] = frozenset()
) -> str:
    """Mask known bank accounts, numeric account strings, and API credentials."""
    masked = text
    for account in sorted(bank_accounts, key=len, reverse=True):
        masked = masked.replace(account, "[BANK_ACCOUNT_REDACTED]")
    masked = _ACCOUNT_NUMBER_PATTERN.sub("[BANK_ACCOUNT_REDACTED]", masked)
    masked = _API_CREDENTIAL_PATTERN.sub("[API_CREDENTIAL_REDACTED]", masked)
    return _LABELED_SECRET_PATTERN.sub(
        r"\1[API_CREDENTIAL_REDACTED]", masked
    )


def _mask_nested(value: Any, bank_accounts: set[str]) -> Any:
    if isinstance(value, str):
        return mask_sensitive_text(value, bank_accounts)
    if isinstance(value, list):
        return [_mask_nested(item, bank_accounts) for item in value]
    if isinstance(value, dict):
        return {
            key: _mask_nested(item, bank_accounts)
            for key, item in value.items()
        }
    if isinstance(value, types.Content):
        content = copy.deepcopy(value)
        for part in content.parts or []:
            if part.text is not None:
                part.text = mask_sensitive_text(part.text, bank_accounts)
            if part.function_call is not None:
                part.function_call.args = _mask_nested(
                    part.function_call.args or {}, bank_accounts
                )
            if part.function_response is not None:
                part.function_response.response = _mask_nested(
                    part.function_response.response or {}, bank_accounts
                )
        return content
    if isinstance(value, types.Part):
        part = copy.deepcopy(value)
        if part.text is not None:
            part.text = mask_sensitive_text(part.text, bank_accounts)
        if part.function_call is not None:
            part.function_call.args = _mask_nested(
                part.function_call.args or {}, bank_accounts
            )
        if part.function_response is not None:
            part.function_response.response = _mask_nested(
                part.function_response.response or {}, bank_accounts
            )
        return part
    return value


def _safe_argument_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {
            "type": "object",
            "keys": sorted(str(key) for key in value),
        }
    if isinstance(value, (list, tuple)):
        return {"type": "array", "length": len(value)}
    if value is None:
        return {"type": "null"}
    return {"type": type(value).__name__, "value": "[REDACTED]"}


def _write_record(
    *,
    agent: str,
    tool: str,
    args: Mapping[str, Any],
    result_hash: str,
    phase: str,
) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "tool": tool,
        "args": dict(args),
        "result_hash": result_hash,
        "phase": phase,
    }
    line = json.dumps(record, sort_keys=True, separators=(",", ":"))
    AUDIT_TRAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _AUDIT_LOCK, AUDIT_TRAIL_PATH.open("a", encoding="utf-8") as trail:
        trail.write(f"{line}\n")


def _request_args(request: LlmRequest) -> dict[str, Any]:
    return {
        "model": request.model,
        "content_count": len(request.contents),
        "request_sha256": _sha256(request.contents),
    }


def before_model_callback(
    context: Context, llm_request: LlmRequest
) -> None:
    """Mask model-facing content and record a hash-only model-call start."""
    bank_accounts = _load_bank_accounts(DATA_DIR)
    contents = copy.deepcopy(llm_request.contents)
    for content in contents:
        for part in content.parts or []:
            if part.text is not None:
                part.text = mask_sensitive_text(part.text, bank_accounts)
            if part.function_call is not None:
                part.function_call.args = _mask_nested(
                    part.function_call.args or {}, bank_accounts
                )
            if part.function_response is not None:
                part.function_response.response = _mask_nested(
                    part.function_response.response or {}, bank_accounts
                )
    llm_request.contents = contents
    if llm_request.config is not None:
        config = copy.deepcopy(llm_request.config)
        if config.system_instruction is not None:
            config.system_instruction = _mask_nested(
                config.system_instruction, bank_accounts
            )
        llm_request.config = config
    _write_record(
        agent=context.agent_name,
        tool="model",
        args=_request_args(llm_request),
        result_hash=_sha256({"status": "started"}),
        phase="started",
    )


def after_model_callback(
    context: Context, llm_response: LlmResponse
) -> None:
    """Record a model response hash without retaining its content."""
    _write_record(
        agent=context.agent_name,
        tool="model",
        args={"response_content_count": len(llm_response.content.parts or [])}
        if llm_response.content is not None
        else {"response_content_count": 0},
        result_hash=_sha256(llm_response),
        phase="completed",
    )


def on_model_error_callback(
    context: Context, llm_request: LlmRequest, error: Exception
) -> None:
    """Record a model error using hashes and non-sensitive metadata only."""
    _write_record(
        agent=context.agent_name,
        tool="model",
        args=_request_args(llm_request),
        result_hash=_sha256(
            {"error_type": type(error).__name__, "message": str(error)}
        ),
        phase="error",
    )


def before_tool_callback(
    tool: BaseTool, args: dict[str, Any], context: Context
) -> None:
    """Record a tool invocation without recording argument values."""
    _write_record(
        agent=context.agent_name,
        tool=tool.name,
        args={key: _safe_argument_summary(value) for key, value in args.items()},
        result_hash=_sha256({"status": "started"}),
        phase="started",
    )


def after_tool_callback(
    tool: BaseTool,
    args: dict[str, Any],
    context: Context,
    tool_response: dict[str, Any],
) -> None:
    """Record a tool result hash without retaining its financial data."""
    _write_record(
        agent=context.agent_name,
        tool=tool.name,
        args={key: _safe_argument_summary(value) for key, value in args.items()},
        result_hash=_sha256(tool_response),
        phase="completed",
    )


def on_tool_error_callback(
    tool: BaseTool,
    args: dict[str, Any],
    context: Context,
    error: Exception,
) -> None:
    """Record a failed tool invocation without retaining its error text."""
    _write_record(
        agent=context.agent_name,
        tool=tool.name,
        args={key: _safe_argument_summary(value) for key, value in args.items()},
        result_hash=_sha256(
            {"error_type": type(error).__name__, "message": str(error)}
        ),
        phase="error",
    )


def install_audit_callbacks(agent: BaseAgent) -> None:
    """Install masking and audit callbacks on every LlmAgent in a tree."""
    if isinstance(agent, LlmAgent):
        agent.before_model_callback = before_model_callback
        agent.after_model_callback = after_model_callback
        agent.on_model_error_callback = on_model_error_callback
        agent.before_tool_callback = before_tool_callback
        agent.after_tool_callback = after_tool_callback
        agent.on_tool_error_callback = on_tool_error_callback
    for sub_agent in agent.sub_agents:
        install_audit_callbacks(sub_agent)
