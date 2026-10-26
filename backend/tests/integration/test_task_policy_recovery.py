import pytest
from test_api import login

from gpupm.db.models import TaskConfig
from gpupm.errors import DomainError

pytest_plugins = ["test_api"]


@pytest.mark.parametrize("applied_before_failure", [False, True])
def test_failed_edit_retains_applied_policy_and_reconciles_without_replay(
    client, app, monkeypatch, applied_before_failure
):
    headers = login(client)
    ctx = app.state.ctx
    ctx.heartbeat()
    task = next(t for t in client.get("/api/tasks").json()["items"] if t["policy_editable"])
    with ctx.sessions() as db:
        previous = db.get(TaskConfig, task["id"]).policy.copy()
    original = ctx.agent.call
    writes = []

    def fail(method, params=None):
        if method == "apply_task_policy":
            writes.append(params)
            if applied_before_failure:
                original(method, params)
            raise DomainError("agent_unavailable", "lost response", 503)
        return original(method, params)

    monkeypatch.setattr(ctx.agent, "call", fail)
    response = client.patch(
        f"/api/tasks/{task['id']}",
        headers=headers,
        json={"revision": task["revision"], "name": "changed-name"},
    )
    assert response.status_code == 503
    with ctx.sessions() as db:
        assert db.get(TaskConfig, task["id"]).policy == previous
    monkeypatch.setattr(ctx.agent, "call", original)
    for _ in range(3):
        ctx.heartbeat()
    assert len(writes) == 1
    result = client.get(f"/api/tasks/{task['id']}").json()
    assert result["name"] == ("changed-name" if applied_before_failure else task["name"])
    assert result["policy_status"] == "applied"
    assert result["revision"] == task["revision"] + int(applied_before_failure)
    with ctx.sessions() as db:
        record = db.get(TaskConfig, task["id"])
        assert record.status == "applied"
        if applied_before_failure:
            assert record.policy_sources["name"] == "task"


def test_legacy_failed_policy_adopts_actual_agent_without_replaying(client, app, monkeypatch):
    login(client)
    ctx = app.state.ctx
    ctx.heartbeat()
    task = next(t for t in client.get("/api/tasks").json()["items"] if t["policy_editable"])
    with ctx.sessions.begin() as db:
        record = db.get(TaskConfig, task["id"])
        record.policy = dict(record.policy, protected=not task["protected"], name="never-applied")
        record.status = "failed"
    original = ctx.agent.call

    def no_writes(method, params=None):
        assert method != "apply_task_policy"
        return original(method, params)

    monkeypatch.setattr(ctx.agent, "call", no_writes)
    ctx.heartbeat()
    result = client.get(f"/api/tasks/{task['id']}").json()
    assert result["name"] == task["name"]
    assert result["protected"] == task["protected"]
    assert result["policy_status"] == "applied"


@pytest.mark.parametrize("apply", [False, True])
def test_pending_edit_survives_api_restart_without_replay(client, app, monkeypatch, apply):
    from gpupm.api.context import Context

    login(client)
    ctx = app.state.ctx
    ctx.heartbeat()
    task = next(t for t in client.get("/api/tasks").json()["items"] if t["policy_editable"])
    with ctx.sessions.begin() as db:
        record = db.get(TaskConfig, task["id"])
        candidate = dict(record.policy, name="crash-edit", priority=74)
        sources = dict(record.policy_sources, name="task", priority="task")
        ctx.audit(
            db,
            "admin",
            "task.policy_attempt",
            task["id"],
            record.policy,
            dict(
                revision=record.revision,
                uid=task["uid"],
                started_at=task["started_at"],
                policy=candidate,
                sources=sources,
                priority_snapshot=None,
            ),
            "pending",
        )
        record.status = "pending"
    if apply:
        ctx.agent.call(
            "apply_task_policy", dict(task_id=task["id"], revision=task["revision"], policy=candidate)
        )
    original = ctx.agent.call

    def no_writes(method, params=None):
        assert method != "apply_task_policy"
        return original(method, params)

    monkeypatch.setattr(ctx.agent, "call", no_writes)
    restarted = Context(ctx.sessions, ctx.agent, ctx.config)
    restarted.heartbeat()
    result = restarted.task(task["id"])
    assert result["name"] == ("crash-edit" if apply else task["name"])
    assert result["priority"] == (74 if apply else task["priority"])
    assert result["policy_status"] == "applied"


def test_old_attempt_does_not_claim_sources_for_different_task_identity(client, app):
    login(client)
    ctx = app.state.ctx
    ctx.heartbeat()
    task = next(t for t in client.get("/api/tasks").json()["items"] if t["policy_editable"])
    with ctx.sessions.begin() as db:
        record = db.get(TaskConfig, task["id"])
        candidate = dict(record.policy, name="changed")
        ctx.audit(
            db,
            "admin",
            "task.policy_attempt",
            task["id"],
            record.policy,
            dict(
                revision=record.revision,
                uid=task["uid"] + 1,
                started_at=task["started_at"],
                policy=candidate,
                sources=dict(record.policy_sources, name="task"),
                priority_snapshot=None,
            ),
            "pending",
        )
        record.status = "failed"
    ctx.agent.call("apply_task_policy", dict(task_id=task["id"], revision=task["revision"], policy=candidate))
    ctx.heartbeat()
    result = ctx.task(task["id"])
    assert result["name"] == "changed"
    assert result["policy_sources"]["name"] == "legacy"


def test_old_failed_unenrolled_host_task_only_registers_observed_policy(tmp_path):
    from gpupm.agent.host import AgentService
    from gpupm.api.context import Context
    from gpupm.config import Config
    from gpupm.db.session import database

    process = dict(
        identity=dict(boot_id="test", pid=2, start_ticks=20),
        pid=2,
        ppid=1,
        uid=1000,
        username="alice",
        command="python train.py",
        status="S",
        create_time="2026-01-01T00:00:00+00:00",
        gpu_memory={"gpu": 10},
        evidence="proc",
    )

    def managed_task_accounts(state):
        state["accounts"].setdefault("1000", {})
        return [
            dict(
                uid=1000,
                username="alice",
                id="1000",
                is_human=True,
                managed=True,
                protected=False,
                status="active",
            )
        ]

    service = AgentService(
        dict(store_path=str(tmp_path / "root.sqlite")),
        collector=lambda: ([], [process], []),
    )
    service.accounts.is_human = lambda uid: uid == 1000
    service.accounts.list = managed_task_accounts
    task = service.call("snapshot")["tasks"][0]
    _, sessions = database(tmp_path / "api.sqlite")
    with sessions.begin() as db:
        db.add(
            TaskConfig(
                task_id=task["id"],
                revision=task["revision"],
                policy={"name": "unapplied", "max_runtime_seconds": 1, "deadline_action": "terminate"},
                status="failed",
            )
        )
    ctx = Context(sessions, service, Config())
    ctx.heartbeat()
    result = service.call("snapshot")["tasks"][0]
    assert result["name"] == task["name"]
    assert result["max_runtime_seconds"] == task["max_runtime_seconds"]
    assert result["deadline_action"] == task["deadline_action"]
    assert result["policy_status"] == "applied"
