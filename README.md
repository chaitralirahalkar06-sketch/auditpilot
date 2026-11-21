# AuditPilot

The agent uses Google's Gemini 3.1 Flash Lite model through Google ADK.

Set your Gemini API key as `GOOGLE_API_KEY` in `auditpilot/.env`. The agent
loads that file automatically when it starts; keep it local because it contains
your secret and is ignored by Git.

Run the agent from the project root with:

```sh
adk run auditpilot
```

## Audit tools

The deterministic pandas tools are available from `auditpilot.tools`:

```python
from auditpilot.tools import find_duplicates

result = find_duplicates()
```

Tools read CSVs and `policy.md` from `data/` by default; pass a directory path
to use another dataset. Results contain `test`, `flagged_ids`, `stats`, and
`notes`. The evaluation-only `data/ground_truth.csv` is not loaded by the tools
and is excluded from version control.

## Intake validation

The ADK Web root is `audit_lead`, with intake validation first. Start the local
Web UI from the project root with:

```sh
adk web auditpilot
```

The included synthetic dataset intentionally contains a one-INR trial-balance
gap, so intake should report `FAILED` until the trial balance is reconciled.
Once intake passes, the `specialists` ParallelAgent runs anomaly, vendor, and
ratio analysis and policy review in parallel and stores results under
`anomaly_findings`, `vendor_findings`, `ratio_findings`, and `policy_findings`.
Policy retrieval uses TF-IDF over the numbered clauses in `data/policy.md`;
policy findings must cite a clause ID and an exact supporting quote. Each
specialist has only its assigned deterministic audit tools; ledger descriptions
are treated as untrusted data.

## Risk ranking

After the specialists finish, `risk_agent` deterministically ranks findings
using the evidence and transaction amounts in the ledger. Likelihood is 5 for
direct prohibited-control evidence, 4 for strong transaction patterns, 3 for
review triggers that do not establish failure, and 2 for population screening.
Impact is based on total listed transaction exposure: below INR 10,000 (1),
INR 10,000–49,999 (2), INR 50,000–99,999 (3), INR 100,000–499,999 (4), and
INR 500,000 or more (5). The score is likelihood multiplied by impact.
Aggregate-only ratio findings without entry IDs are excluded with an explicit
reason rather than assigned invented transaction identifiers.

## Skeptical verification

After risk scoring, the `verification_loop` checks each finding against the
ledger and the applicable deterministic audit checks. Missing IDs and
unsupported financial claims are retained in `dropped_appendix`; supported
indicators that still have plausible innocent explanations remain
`needs_evidence`. The loop stops when no findings need more evidence or after
three rounds.

## Audit memo and human sign-off

After verification, `report_agent` writes `docs/audit_memo.md` as DRAFT using
only session-state tool outputs. In the same ADK session, reply exactly
`APPROVE`, `REQUEST CHANGES`, or `REJECT`. Only `APPROVE` changes the memo to
FINAL; the other choices keep it DRAFT. Sign-off choices are checked against
the current human message, not inferred from the model's response.
The Web server is for trusted local development only.
