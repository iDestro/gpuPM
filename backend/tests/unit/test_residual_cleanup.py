from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from gpupm.agent.host import AgentService
from gpupm.domain.schemas import SettingsPatch, TaskPatch
from test_host_agent import process


def test_residual_lifecycle_and_legacy_never_signals(tmp_path, monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr("gpupm.agent.host.utcnow", lambda: now)
    members = [process(10, 2, True), process(11, 10)]
    errors = []
    signals = []
    service = AgentService(
        dict(store_path=str(tmp_path / "agent.sqlite"), allow_mutations=True),
        collector=lambda: ([], members, errors),
        signaler=lambda *a: signals.append(a),
    )
    service.accounts.is_human = lambda uid: True
    service.accounts.list = lambda state: []
    task = service.call("snapshot")["tasks"][0]
    service.call(
        "apply_task_policy",
        dict(
            task_id=task["id"],
            revision=task["revision"],
            policy=dict(
                cleanup_orphans=True,
                deadline_action="terminate",
                max_runtime_seconds=1,
                orphan_wait_seconds=10,
            ),
        ),
    )
    members[:] = [process(11, 1)]
    task = service.call("snapshot")["tasks"][0]
    assert task["status"] == "finalizing"
    since = task["finalizing_since"]
    now += timedelta(seconds=10)
    errors[:] = [dict(code="nvml_unavailable")]
    assert service.call("snapshot")["tasks"][0]["status"] == "finalizing"
    errors.clear()
    task = service.call("snapshot")["tasks"][0]
    assert task["status"] == "awaiting_cleanup"
    assert task["finalizing_since"] == since
    service.call("heartbeat", dict(policy_versions={task["id"]: task["revision"]}))
    service.tick()
    assert task["deadline_at"] <= now.isoformat()
    assert not signals
    preview = service.call("preview_termination", dict(task_id=task["id"], residual_only=True))
    assert [m["pid"] for m in preview["targets"]] == [11]
    assert preview["residual_only"] is True
    members[:] = [process(11, 1, True)]
    with pytest.raises(Exception):
        service.call(
            "execute_termination",
            dict(task_id=task["id"], token=preview["token"], reason="manual", idempotency_key="manual-test"),
        )
    assert not signals
    members[:] = [process(10, 2, True), process(11, 10)]
    assert service.call("snapshot")["tasks"][0]["finalizing_since"] is None
    members.clear()
    assert service.call("snapshot")["tasks"][0]["status"] == "finished"


@pytest.mark.parametrize("value", [True, 0, 86401, 1.5, "300"])
def test_wait_is_strict(value):
    with pytest.raises(ValidationError):
        TaskPatch(revision=1, orphan_wait_seconds=value)
    with pytest.raises(ValidationError):
        SettingsPatch(default_orphan_wait_seconds=value)


def ready_service(tmp_path, monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr("gpupm.agent.host.utcnow", lambda: now)
    members = [process(10, 2, True), process(11, 10), process(12, 10)]
    service = AgentService(
        dict(
            store_path=str(tmp_path / "ready.sqlite"),
            allow_mutations=True,
            term_grace_seconds=0,
            termination_recheck_seconds=0,
        ),
        collector=lambda: ([], members, []),
        process_checker=lambda i: "alive",
    )
    service.accounts.is_human = lambda uid: True
    service.accounts.list = lambda state: []
    service.call("snapshot")
    members[:] = [process(11, 1), process(12, 1)]
    service.call("snapshot")
    now += timedelta(seconds=301)
    return service, members, service.call("snapshot")["tasks"][0]


@pytest.mark.parametrize("change", ["gpu", "protected", "nonhuman", "uid", "identity"])
def test_queued_residual_rechecks_before_signal(tmp_path, monkeypatch, change):
    service, members, task = ready_service(tmp_path, monkeypatch)
    monkeypatch.setattr("gpupm.agent.host.threading.Thread.start", lambda self: None)
    preview = service.call("preview_termination", dict(task_id=task["id"], residual_only=True))
    job = service.call(
        "execute_termination",
        dict(
            task_id=task["id"],
            token=preview["token"],
            reason="confirmed manual",
            idempotency_key="queued-test",
        ),
    )
    assert service.call("snapshot")["tasks"][0]["status"] == "cleaning"
    if change == "gpu":
        members[0]["gpu_memory"] = {"gpu": 0}
    elif change == "protected":
        with service.database() as db:
            state = service.load(db)
            state["tasks"][0]["protected"] = True
            service.save(db, state)
    elif change == "nonhuman":
        service.accounts.is_human = lambda uid: False
    elif change == "uid":
        members[0]["uid"] = 2000
    else:
        members[0]["identity"] = dict(members[0]["identity"], start_ticks=999)
    signals = []
    service.signaler = lambda *a: signals.append(a) or "signaled"
    service.execute_job(job["id"])
    # UID change excludes that identity; unchanged confirmed targets may still be signaled.
    if change == "uid":
        assert all(args[0]["pid"] != 11 for args in signals)
    else:
        assert not signals
    assert service.call("snapshot")["tasks"][0]["status"] != "cleaning"


def test_residual_shrink_stops_job_with_partial_scope(tmp_path, monkeypatch):
    service, members, task = ready_service(tmp_path, monkeypatch)
    monkeypatch.setattr("gpupm.agent.host.threading.Thread.start", lambda self: None)
    preview = service.call("preview_termination", dict(task_id=task["id"], residual_only=True))
    job = service.call(
        "execute_termination",
        dict(
            task_id=task["id"],
            token=preview["token"],
            reason="confirmed manual",
            idempotency_key="shrinking-test",
        ),
    )
    calls = []

    def signaler(identity, sig, protected):
        calls.append(identity)
        members[:] = [m for m in members if m["identity"] != identity]
        return "signaled"

    service.signaler = signaler
    service.execute_job(job["id"])
    assert len(calls) == 1
    result = service.call("job_status", {"id": job["id"]})
    assert result["status"] == "partial"
    assert result["results"][1]["term"] == "scope_changed"
    assert service.call("snapshot")["tasks"][0]["status"] == "awaiting_cleanup"


def test_restart_retains_timer_and_leaderless_cannot_authorize(tmp_path, monkeypatch):
    service, members, task = ready_service(tmp_path, monkeypatch)
    restarted = AgentService(service.config, collector=lambda: ([], members, []))
    restarted.accounts.is_human = lambda uid: True
    updated = restarted.call("snapshot")["tasks"][0]
    assert updated["finalizing_since"] == task["finalizing_since"]
    assert updated["status"] == "awaiting_cleanup"
    with restarted.database() as db:
        state = restarted.load(db)
        state["tasks"][0]["leader_identities"] = []
        restarted.save(db, state)
    from gpupm.errors import DomainError

    with pytest.raises(DomainError):
        restarted.call("preview_termination", dict(task_id=task["id"], residual_only=True))


def test_valid_reminder_fields_and_strict_bool():
    assert TaskPatch(revision=1, orphan_reminder=True, orphan_wait_seconds=300).orphan_wait_seconds == 300
    assert SettingsPatch(default_orphan_reminder=False, default_orphan_wait_seconds=86400)
    for value in ["true", 1, 0]:
        with pytest.raises(ValidationError):
            TaskPatch(revision=1, orphan_reminder=value)
        with pytest.raises(ValidationError):
            SettingsPatch(default_orphan_reminder=value)


@pytest.mark.parametrize("failure,stale", [("denied", True), ("changed", True), ("exited", False)])
def test_collection_distinguishes_unreadable_from_exit(monkeypatch, failure, stale):
    from types import SimpleNamespace
    import psutil
    import gpupm.agent.processes as module

    class NV:
        def nvmlInit(self):
            pass

        def nvmlDeviceGetCount(self):
            return 0

        def nvmlShutdown(self):
            pass

    import sys

    monkeypatch.setitem(sys.modules, "pynvml", NV())
    monkeypatch.setattr(module.Path, "read_text", lambda *a, **kw: "boot")
    item = SimpleNamespace(
        pid=10,
        info=dict(
            pid=10,
            ppid=2,
            uids=SimpleNamespace(real=1000),
            cmdline=["python", "train.py"],
            exe="/usr/bin/python",
            name="python",
            create_time=1,
            status="S",
        ),
    )
    item.ppid = lambda: 99 if failure == "changed" else 2
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [item])

    def identity(pid):
        if failure == "denied":
            raise psutil.AccessDenied(pid)
        if failure == "exited":
            raise psutil.NoSuchProcess(pid)
        return dict(boot_id="boot", pid=pid, start_ticks=1)

    monkeypatch.setattr(module, "proc_identity", identity)
    _, members, errors = module.collect()
    assert not members
    assert bool(errors) == stale


def test_native_signaling_rechecks_authorized_uid(monkeypatch):
    import os
    import signal
    from types import SimpleNamespace
    import gpupm.agent.processes as module

    identity = dict(boot_id="boot", pid=10, start_ticks=100)
    monkeypatch.setattr(os, "pidfd_open", lambda pid: 42, raising=False)
    monkeypatch.setattr(os, "close", lambda fd: None)
    calls = []
    monkeypatch.setattr(signal, "pidfd_send_signal", lambda *a: calls.append(a), raising=False)
    monkeypatch.setattr(module, "proc_identity", lambda pid: identity)
    uids = iter([1000, 2000])
    monkeypatch.setattr(
        module.psutil,
        "Process",
        lambda pid: SimpleNamespace(
            cmdline=lambda: ["python", "worker.py"], uids=lambda: SimpleNamespace(real=next(uids))
        ),
    )
    assert (
        module.signal_identity(identity, signal.SIGTERM, expected_uid=1000, human_check=lambda uid: True)
        == "scope_changed"
    )
    assert not calls


def test_gpu_return_after_term_suppresses_kill(tmp_path, monkeypatch):
    service, members, task = ready_service(tmp_path, monkeypatch)
    monkeypatch.setattr("gpupm.agent.host.threading.Thread.start", lambda self: None)
    preview = service.call("preview_termination", dict(task_id=task["id"], residual_only=True))
    job = service.call(
        "execute_termination",
        dict(task_id=task["id"], token=preview["token"], reason="manual", idempotency_key="gpu-resume"),
    )
    calls = []

    def signaler(identity, sig, protected):
        calls.append(sig)
        members[0]["gpu_memory"] = {"gpu": 0}
        return "signaled"

    service.signaler = signaler
    service.execute_job(job["id"])
    import signal

    assert calls == [signal.SIGTERM]
    assert service.call("snapshot")["tasks"][0]["status"] == "finalizing"


def test_queued_deadline_cannot_signal_after_leader_exit(tmp_path, monkeypatch):
    members = [process(10, 2, True), process(11, 10)]
    service = AgentService(
        dict(store_path=str(tmp_path / "deadline.sqlite"), allow_mutations=True, term_grace_seconds=0),
        collector=lambda: ([], members, []),
    )
    service.accounts.is_human = lambda uid: True
    monkeypatch.setattr("gpupm.agent.host.threading.Thread.start", lambda self: None)
    task = service.call("snapshot")["tasks"][0]
    task = service.call(
        "apply_task_policy",
        dict(
            task_id=task["id"],
            revision=task["revision"],
            policy=dict(cleanup_orphans=True, deadline_action="terminate", max_runtime_seconds=1),
        ),
    )
    service.call("heartbeat", dict(policy_versions={task["id"]: task["revision"]}))
    preview = service.call("preview_termination", dict(task_id=task["id"]))
    job = service.call(
        "execute_termination",
        dict(
            task_id=task["id"],
            token=preview["token"],
            reason="deadline",
            actor="policy",
            idempotency_key="queued-deadline",
        ),
    )
    members[:] = [process(11, 1)]
    service.signaler = lambda *a: pytest.fail("cannot signal finalizing worker")
    service.execute_job(job["id"])
    assert service.call("snapshot")["tasks"][0]["status"] == "finalizing"


@pytest.mark.parametrize("leader", [{}, {"boot_id": "boot", "pid": "10", "start_ticks": 100}])
def test_bad_leader_metadata_holds_state_and_blocks_cleanup(tmp_path, monkeypatch, leader):
    service, members, task = ready_service(tmp_path, monkeypatch)
    with service.database() as db:
        state = service.load(db)
        state["tasks"][0]["leader_identities"] = [leader]
        service.save(db, state)
    snapshot = service.call("snapshot")
    assert snapshot["stale"]
    assert snapshot["tasks"][0]["members"]
    from gpupm.errors import DomainError

    with pytest.raises(DomainError):
        service.call("preview_termination", dict(task_id=task["id"], residual_only=True))
    service.tick()
    with service.database() as db:
        assert not service.load(db)["jobs"]


@pytest.mark.parametrize("restart", [False, True])
def test_inactive_cleanup_job_stale_collection_leaves_finalizing(tmp_path, monkeypatch, restart):
    service, members, task = ready_service(tmp_path, monkeypatch)
    monkeypatch.setattr("gpupm.agent.host.threading.Thread.start", lambda self: None)
    preview = service.call("preview_termination", dict(task_id=task["id"], residual_only=True))
    job = service.call(
        "execute_termination",
        dict(task_id=task["id"], token=preview["token"], reason="manual", idempotency_key="terminal-stale"),
    )

    def failed_collect():
        raise RuntimeError("collection unavailable")

    service.collector = failed_collect
    if restart:
        service = AgentService(service.config, collector=failed_collect, process_checker=lambda i: "alive")
        service.accounts.is_human = lambda uid: True
    else:
        with service.database() as db:
            state = service.load(db)
            state["jobs"][job["id"]]["status"] = "partial"
            service.save(db, state)
    snapshot = service.call("snapshot")
    assert snapshot["stale"]
    updated = snapshot["tasks"][0]
    assert updated["status"] == "finalizing"
    assert updated["finalizing_since"] == task["finalizing_since"]
    assert service.call("job_status", {"id": job["id"]})["status"] not in {"queued", "running"}
