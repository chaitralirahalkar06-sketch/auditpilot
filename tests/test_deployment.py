from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

import main

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_health_endpoint_returns_only_liveness_status() -> None:
    response = TestClient(main.app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_deployment_shell_scripts_are_syntactically_valid() -> None:
    scripts = (
        PROJECT_ROOT / "scripts" / "deploy_remote.sh",
        PROJECT_ROOT / "scripts" / "aws" / "app_user_data.sh",
        PROJECT_ROOT / "scripts" / "aws" / "jenkins_user_data.sh",
    )
    subprocess.run(
        ["bash", "-n", *(str(script) for script in scripts)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_docker_configuration_excludes_evaluation_labels_and_local_secrets() -> None:
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "data/ground_truth.csv" in dockerignore
    assert "**/.env" in dockerignore
    assert "audit_trail.jsonl" in dockerignore

    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM base AS test" in dockerfile
    assert "FROM base AS runtime" in dockerfile
    assert "rm -f /app/data/ground_truth.csv" in dockerfile
