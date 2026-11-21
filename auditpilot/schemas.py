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
