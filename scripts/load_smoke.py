"""Synthetic1000-process/100-task smoke; no host process or GPU changes."""

from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time

from fastapi.testclient import TestClient
from gpupm.agent.processes import group_processes
from gpupm.api.main import create_app
from gpupm.config import Config

processes = []
now = datetime.now(timezone.utc).isoformat()
for task in range(100):
    root = 10000 + task * 10
    for child in range(10):
        pid = root + child
        processes.append(
            dict(
                identity=dict(boot_id="synthetic", pid=pid, start_ticks=pid * 10),
                pid=pid,
                ppid=1 if child == 0 else root,
                uid=1001,
                username="alice",
                command="python train.py" if child == 0 else "python DataLoader",
                status="sleeping",
                create_time=now,
                gpu_memory={"demo-gpu-0": 1024} if child == 0 else {},
                evidence="synthetic",
            )
        )
scans = []
tasks = []
for _ in range(20):
    started = time.perf_counter()
    tasks = group_processes(processes, tasks)
    scans.append((time.perf_counter() - started) * 1000)
assert len(tasks) == 100 and sum(len(t["members"]) for t in tasks) == 1000
with tempfile.TemporaryDirectory() as directory:
    app = create_app(
        Config(
            mode="demo",
            database=Path(directory) / "app.sqlite",
            agent_database=Path(directory) / "agent.sqlite",
        )
    )
    agent = app.state.ctx.agent
    with agent.lock, sqlite3.connect(agent.path) as db:
        state = json.loads(
            db.execute("SELECT data FROM state WHERE id=1").fetchone()[0]
        )
        state["tasks"] = tasks
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    password = secrets.token_urlsafe(24)
    app.state.auth.create_admin("qa", password)
    client = TestClient(app)
    assert (
        client.post(
            "/api/auth/login", json={"username": "qa", "password": password}
        ).status_code
        == 200
    )
    queries = []
    for _ in range(30):
        started = time.perf_counter()
        result = client.get("/api/tasks?page_size=100")
        queries.append((time.perf_counter() - started) * 1000)
        assert result.status_code == 200 and result.json()["total"] == 100, result.text
    snapshot = agent.call("snapshot", {})
    encoded = len(json.dumps(snapshot).encode())
    assert encoded < 1024 * 1024, encoded
    p95 = sorted(queries)[int(len(queries) * 0.95) - 1]
    assert p95 < 500, p95
    print(
        json.dumps(
            {
                "processes": 1000,
                "tasks": 100,
                "scan_p95_ms": round(sorted(scans)[18], 2),
                "cached_API_p95_ms": round(p95, 2),
                "snapshot_bytes": encoded,
            }
        )
    )
