"""Validated data models shared by AuditPilot agents."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

RiskRating = Annotated[int, Field(strict=True, ge=1, le=5)]
RiskScore = Annotated[int, Field(strict=True, ge=1, le=25)]


class Finding(BaseModel):
    """A transaction finding with evidence-backed and validated risk values."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    title: str = Field(min_length=1)
    entry_ids: list[str] = Field(min_length=1)
    evidence: list[str]
    amount_at_risk_inr: int = Field(strict=True, ge=0)
    likelihood: RiskRating
    impact: RiskRating
    score: RiskScore
    rationale: str = Field(min_length=1)
    status: Literal["open", "in_review", "closed"] = "open"

    @field_validator("entry_ids")
    @classmethod
    def require_nonblank_entry_ids(cls, values: list[str]) -> list[str]:
        if any(not entry_id.strip() for entry_id in values):
            raise ValueError("entry_ids must not contain blank IDs")
        if len(values) != len(set(values)):
            raise ValueError("entry_ids must be unique")
        return values

    @model_validator(mode="after")
    def score_must_match_ratings(self) -> Finding:
        if self.score != self.likelihood * self.impact:
            raise ValueError("score must equal likelihood multiplied by impact")
        return self


class RankedFindings(BaseModel):
    """Risk-ranked findings plus explicit explanations for excluded inputs."""

    model_config = ConfigDict(extra="forbid")

    findings: list[Finding]
    excluded_findings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def findings_are_ranked(self) -> RankedFindings:
        scores = [finding.score for finding in self.findings]
        if scores != sorted(scores, reverse=True):
            raise ValueError("findings must be sorted by descending risk score")
        return self


class VerificationChecks(BaseModel):
    """Deterministic checks performed for a risk finding."""

    entry_ids_exist: bool
    evidence_supports_claim: bool
    innocent_explanation_plausible: bool
    unsupported_financial_claims: list[str] = Field(default_factory=list)


class VerificationFinding(BaseModel):
    """A risk finding with a skeptical status and an auditable reason."""

    id: str
    finding: dict[str, object]
    entry_ids: list[str] = Field(default_factory=list)
    status: Literal["confirmed", "needs_evidence", "dropped"]
    reason: str = Field(min_length=1)
    checks: VerificationChecks

    @field_validator("reason")
    @classmethod
    def require_single_line_reason(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("verification reason must be one line")
        return value


class VerificationReport(BaseModel):
    """Verification results with dropped findings retained in an appendix."""

    iteration: Annotated[int, Field(strict=True, ge=1, le=3)]
    findings: list[VerificationFinding]
    dropped_appendix: list[VerificationFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def partition_dropped_findings(self) -> VerificationReport:
        if any(finding.status == "dropped" for finding in self.findings):
            raise ValueError("dropped findings must be kept in dropped_appendix")
        if any(
            finding.status != "dropped" for finding in self.dropped_appendix
        ):
            raise ValueError("dropped_appendix may contain only dropped findings")
        return self
