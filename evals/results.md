# AuditPilot Evaluation Results

Evaluation uses deterministic Python audit tools; no Gemini/API calls are made.
Ground truth is read only after the three tool-pipeline runs and is never passed to agents.

- Three repeated runs identical: **PASS**

| Anomaly type | TP | FP | FN | Precision | Recall | Recall >= 90% |
|---|---:|---:|---:|---:|---:|---|
| duplicate_payment | 10 | 0 | 0 | 100.0% | 100.0% | PASS |
| split_payment | 18 | 16 | 0 | 52.9% | 100.0% | PASS |
| ghost_vendor | 5 | 0 | 0 | 100.0% | 100.0% | PASS |
| shared_bank_account | 3 | 0 | 0 | 100.0% | 100.0% | PASS |
| self_approved | 8 | 0 | 0 | 100.0% | 100.0% | PASS |
| sunday_round_amount | 12 | 0 | 0 | 100.0% | 100.0% | PASS |
| prompt_injection | 4 | 0 | 0 | 100.0% | 100.0% | PASS |
| trial_balance_gap | 1 | 0 | 0 | 100.0% | 100.0% | PASS |

The `prompt_injection` row measures the evaluator's deterministic detector for the four planted instruction-like descriptions; the text remains untrusted and is not an agent instruction.

- Memo amount consistency: **SKIPPED** — No audit memo was present; the check is covered by tests and will run when a pipeline memo is available.
