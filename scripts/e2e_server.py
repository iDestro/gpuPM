"""Disposable demo API for browser tests; no host actions or fixed production credentials."""

import tempfile
from pathlib import Path

import uvicorn
from gpupm.api.main import create_app
from gpupm.config import Config

with tempfile.TemporaryDirectory(prefix="gpupm-e2e-") as directory:
    base = Path(directory)
    app = create_app(
        Config(
            mode="demo",
            database=base / "app.db",
            agent_database=base / "agent.db",
            frontend_dist=Path(__file__).resolve().parents[1] / "frontend/dist",
        )
    )
    app.state.auth.create_admin("admin", "Strong-admin-pass-42")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
