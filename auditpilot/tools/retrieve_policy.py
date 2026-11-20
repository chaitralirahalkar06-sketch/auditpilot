"""TF-IDF retrieval over numbered clauses in the company policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer

from .audit_tools import DEFAULT_DATA_DIR

_HEADING = re.compile(
    r"^#{1,6}\s+(?:(\d+(?:\.\d+)*)\s+)?(.+?)\s*$",
    flags=re.MULTILINE,
)
_CLAUSE_ID = re.compile(r"^\d+(?:\.\d+)*$")
_MAX_QUOTE_LENGTH = 240


@dataclass(frozen=True)
class PolicyClause:
    """One numbered policy clause and its searchable text."""

    clause_id: str
    title: str
    text: str

    @property
    def searchable_text(self) -> str:
        return f"{self.title}. {self.text}"

    @property
    def quote(self) -> str:
        text = " ".join(self.text.split())
        if len(text) <= _MAX_QUOTE_LENGTH:
            return text
        return text[: _MAX_QUOTE_LENGTH - 1].rsplit(" ", 1)[0] + "..."


def _read_clauses(data_dir: Path | str) -> list[PolicyClause]:
    path = Path(data_dir) / "policy.md"
    text = path.read_text(encoding="utf-8")
    headings = list(_HEADING.finditer(text))
    clauses: list[PolicyClause] = []
    seen_ids: set[str] = set()

    for index, heading in enumerate(headings):
        clause_id, title = heading.groups()
        if clause_id is None or not _CLAUSE_ID.fullmatch(clause_id):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = text[heading.end() : end].strip()
        if not body:
            raise ValueError(f"{path} has an empty policy clause {clause_id}")
        if clause_id in seen_ids:
            raise ValueError(f"{path} contains duplicate clause ID {clause_id}")
        seen_ids.add(clause_id)
        clauses.append(PolicyClause(clause_id, title, body))

    if not clauses:
        raise ValueError(f"{path} contains no numbered policy clauses")
    return clauses


def _rank_tfidf(
    query: str, clauses: list[PolicyClause], k: int
) -> list[tuple[PolicyClause, float]]:
    """Rank clauses with a backend isolated for future retrieval replacement."""
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        sublinear_tf=True,
    )
    clause_vectors = vectorizer.fit_transform(
        [clause.searchable_text for clause in clauses]
    )
    query_vector = vectorizer.transform([query])
    scores = (clause_vectors @ query_vector.T).toarray().ravel()
    ranked_indices = sorted(
        range(len(clauses)), key=lambda index: (-scores[index], index)
    )
    return [
        (clauses[index], float(scores[index]))
        for index in ranked_indices[:k]
        if scores[index] > 0
    ]


def retrieve_policy(
    query: str,
    k: int = 3,
    *,
    data_dir: Path | str = DEFAULT_DATA_DIR,
) -> dict[str, Any]:
    """Return the top matching numbered policy clauses with exact quotations."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")

    clauses = _read_clauses(data_dir)
    ranked = _rank_tfidf(query.strip(), clauses, k)
    return {
        "test": "retrieve_policy",
        "clauses": [
            {
                "clause_id": clause.clause_id,
                "title": clause.title,
                "quote": clause.quote,
                "score": score,
            }
            for clause, score in ranked
        ],
        "stats": {
            "retrieval_method": "tfidf",
            "available_clause_count": len(clauses),
            "returned_clause_count": len(ranked),
        },
        "notes": [
            "Quotes are exact excerpts from numbered clauses in data/policy.md."
        ],
    }
