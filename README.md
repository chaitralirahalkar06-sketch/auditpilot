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
The Web server is for trusted local development only.
