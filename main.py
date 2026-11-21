"""Serve AuditPilot agents with the Google ADK FastAPI application."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app

APP_DIR = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8080"))
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("ADK_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

app: FastAPI = get_fast_api_app(
    agents_dir=str(APP_DIR),
    allow_origins=ALLOWED_ORIGINS,
    web=True,
    bind_host="0.0.0.0",
    port=PORT,
)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    """Return a minimal liveness response for container and load-balancer checks."""
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
