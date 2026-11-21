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

## Phase 9 guardrails and evaluation

The production ADK tree masks known vendor/employee bank-account values in
model-facing request content while leaving deterministic tool inputs unchanged.
Model and tool callbacks append hash-only activity records to the ignored
`audit_trail.jsonl`; raw prompts, results, API credentials, and financial
argument values are not written to that file.

Run the deterministic evaluation from the project root:

```sh
python -m evals.run_eval
```

It executes the audit tools three times, then reads `data/ground_truth.csv`
inside the evaluator only and writes per-type precision/recall to
`evals/results.md`. The planted trial-balance gap intentionally blocks normal
intake, and no audit memo is included in a fresh checkout; until a memo exists,
the evaluation reports its amount-consistency check as `SKIPPED` rather than
creating or altering a memo. Existing specialist tests verify that all four
planted prompt-injection descriptions do not alter the deterministic findings.

How System Work
            <img width="1160" height="2264" alt="mermaid-diagram" src="https://github.com/user-attachments/assets/2afd8236-3b4d-48d2-9472-41054b67a8b9" />

## Part 2: Docker, Jenkins, and AWS deployment

The deployment files follow the supplied Part 2 guide:

- `main.py` serves the ADK agent UI/API and a minimal `/health` endpoint.
- `Dockerfile` has separate `test` and `runtime` targets. The test target
  regenerates the fictional evaluation data before running pytest. The runtime
  target generates the synthetic app data but removes `ground_truth.csv`.
- `.dockerignore` excludes local environment files, ADK state, audit logs,
  generated memos, and the evaluation labels from the Docker build context.
- `Jenkinsfile` builds and tests on every branch, then pushes a numbered image
  and deploys only from `main`.
- `scripts/aws/jenkins_user_data.sh` and
  `scripts/aws/app_user_data.sh` bootstrap the two EC2 hosts.
- `scripts/deploy_remote.sh` tells the running app host to pull and health-check
  a numbered ECR image through Systems Manager (SSM).

### Run and test locally with Docker

Build and run the test target:

```sh
docker build --target test -t auditpilot:test .
docker run --rm auditpilot:test
```

Build and start the runtime target. Provide the key through a local ignored
environment file; never add that file to the image or Git:

```sh
docker build --target runtime -t auditpilot:local .
docker run --rm -p 8080:8080 \
  --env-file auditpilot/.env \
  -e ADK_ALLOWED_ORIGINS=http://localhost:8080 \
  auditpilot:local
curl http://localhost:8080/health
```

Open `http://localhost:8080/dev-ui/` for the ADK UI. The `/health` response
only confirms that the web process is alive; it does not call Gemini.

### AWS and Jenkins prerequisites

This repository contains the app, pipeline, and host bootstrap scripts; it does
not automatically provision AWS resources. Provision them in `ap-south-1`
(Mumbai) using an AWS account you control. Set an AWS budget alert before
starting. EC2 instances, EBS volumes, ECR storage, Secrets Manager, and
CloudWatch may incur charges.

1. Create a private ECR repository named `auditpilot` with image scanning on
   push.
2. Store the Gemini key in Secrets Manager as `auditpilot/google_api_key`.
   Do not put it in Jenkins credentials, user data, Git, or a Docker build
   argument.
3. Give the app EC2 instance profile `AmazonSSMManagedInstanceCore` and
   `AmazonEC2ContainerRegistryReadOnly`. Add a narrowly scoped inline policy
   permitting `secretsmanager:GetSecretValue` only for this secret and the
   CloudWatch Logs actions needed to create/write the `auditpilot` log group.
4. Give Jenkins its own EC2 instance profile with
   `AmazonSSMManagedInstanceCore` and `AmazonEC2ContainerRegistryPowerUser`.
   Add only the SSM send/read command actions and EC2 `DescribeInstances`
   needed by `scripts/deploy_remote.sh`. Do not create long-lived AWS access
   keys.
5. Create separate security groups. Allow Jenkins TCP `8080` and app TCP `80`
   only from your current public IP as `/32`; do not open SSH or use
   `0.0.0.0/0`. Both hosts need outbound access to AWS services. Jenkins must
   be able to use Docker and its EC2 role; the app host must be SSM-managed.
6. Launch an Ubuntu 24.04 `t3.medium` Jenkins host with the Jenkins instance
   profile and `scripts/aws/jenkins_user_data.sh`. Launch an Amazon Linux 2023
   `t3.small` app host with the app profile and
   `scripts/aws/app_user_data.sh`. Use the default VPC's public subnet for
   this learning setup, and enable public IPv4 only with the IP-restricted
   security groups above. Wait for both user-data scripts and SSM registration
   to finish.
7. Open Jenkins from your allowlisted IP, complete the initial setup, and
   create a Multibranch Pipeline for this repository.
   For a private repository, configure a GitHub access token as a Jenkins SCM
   credential in Jenkins itself; the `Jenkinsfile` does not contain a token.
   Ensure the job builds `main` and add a GitHub webhook if automatic
   push-triggered builds are required.

The Jenkins role must be attached to the Jenkins host before it runs a build.
The app role must be attached before launching the app host. The scripts use
SSM rather than SSH and expect exactly one running EC2 instance tagged
`Name=auditpilot_app`.

### Deployment, verification, rollback, and cleanup

The Jenkins pipeline runs these stages: checkout, build the test image, run
pytest inside it, build the runtime image, push a build-number tag plus
`latest` to ECR, then deploy the numbered tag over SSM. The app host retrieves
the key from Secrets Manager at deploy time, starts the container with
CloudWatch logging, and checks `/health`. On health-check failure it restores
the previous container and fails the Jenkins build.

After a successful build, check `http://<app-public-ip>/health` and then
`http://<app-public-ip>/dev-ui/` from the allowlisted IP. Inspect Jenkins
console output, `docker logs auditpilot` through an SSM session, or the
CloudWatch log group named `auditpilot`. The app host keeps
`audit_trail.jsonl` and generated memos under `/var/lib/auditpilot/`, across
container replacements; review them through an SSM session. To roll back, run the app host's
`/opt/auditpilot/deploy.sh <BUILD_NUMBER>` with SSM, choosing an existing
numbered ECR image tag.

The included synthetic trial balance intentionally has a one-INR gap, so
intake blocks the audit workflow until the source data is reconciled. The
deployment health check does not imply that an audit run passed.

This is a restricted learning deployment, not a production security boundary:
the ADK dev UI and API have no application login, and the example serves HTTP
without TLS. The EC2 security group must remain restricted to your IP. Do not
make the app or Jenkins publicly reachable; production use needs authentication,
HTTPS, and a hardened network entry point. Docker administrators on the app
host can inspect container configuration, so host access remains sensitive.

When finished, terminate both EC2 instances first. Then delete the ECR
repository and images, the Secrets Manager secret, the `auditpilot` CloudWatch
log group, both security groups, both instance profiles, inline and attached
IAM policies, and both IAM roles. Check the EC2 volumes/snapshots and AWS
Billing console afterward to confirm no billable resources remain.
