"""Disposable demo API for browser tests; no host actions or fixed production credentials."""

import copy
import json
import sqlite3
import tempfile
from datetime import timedelta
from pathlib import Path

import uvicorn
from gpupm.api.main import create_app
from gpupm.config import Config
from gpupm.domain.rules import utcnow

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
    agent = app.state.ctx.agent
    with agent.lock, sqlite3.connect(agent.path) as db:
        state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        task = copy.deepcopy(next(t for t in state["tasks"] if t["id"] == "demo-task-2"))
        leader = task["members"][0]
        leader["identity"] = {"boot_id": "e2e-residual-boot", "pid": 990000, "start_ticks": 99000000}
        task["leader_identities"] = [leader["identity"]]
        worker = task["members"][1]
        worker.update(pid=990001, ppid=1)
        worker["identity"] = {"boot_id": "e2e-residual-boot", "pid": 990001, "start_ticks": 99000100}
        task.update(
            id="e2e-residual-task", name="E2E residual worker", original_name="E2E residual worker",
            members=[worker], finalizing_since=(utcnow() - timedelta(seconds=600)).isoformat(),
            orphan_reminder=True, orphan_wait_seconds=300, protected=False, revision=1,
        )
        state["tasks"].append(task)
        state["system_groups"].append({
            "id": "e2e-project-group", "name": "e2e-project-group", "gid": 9000,
            "members": [], "managed": False, "protected": False, "revision": 1,
        })
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    app.state.auth.create_admin("admin", "Strong-admin-pass-42")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
