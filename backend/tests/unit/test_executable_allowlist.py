import pytest
from pydantic import ValidationError

from gpupm.agent.processes import group_processes
from gpupm.domain.schemas import SettingsPatch
from gpupm.domain.settings import DEFAULT_SETTINGS
from test_task_defaults import process


XORG = "/usr/lib/xorg/Xorg"


def test_default_exact_executable_filter_and_reversal():
    xorg = dict(process(10), exe=XORG, command=XORG)
    train = dict(process(11), exe="/usr/bin/python", command=f"python train.py {XORG}")
    other = dict(process(12), exe="/opt/Xorg", command="/opt/Xorg")
    tasks = group_processes(
        [xorg, train, other], [], ignored_executables=DEFAULT_SETTINGS["ignored_task_executables"]
    )
    assert {m["pid"] for t in tasks for m in t["members"]} == {11, 12}
    old = group_processes([xorg, train], [], ignored_executables=[])
    hidden = group_processes([xorg, train], old, ignored_executables=[XORG])
    ignored = next(t for t in hidden if t["ignored"])
    assert ignored["members"] == []
    assert ignored["ignored_members"][0]["exe"] == XORG
    restored = group_processes([xorg, train], hidden, ignored_executables=[])
    assert next(t for t in restored if t["id"] == ignored["id"])["members"][0]["pid"] == 10


@pytest.mark.parametrize(
    "value",
    [
        None,
        "Xorg",
        [123],
        ["Xorg"],
        ["/usr//bin/Xorg"],
        ["/usr/../bin/Xorg"],
        ["/usr/*/Xorg"],
        ["/usr/[X]/Xorg"],
        ["/usr/Xorg\n"],
        ["/usr/Xorg\0"],
        ["/" + "x" * 4096],
        ["/x"] * 51,
    ],
)
def test_strict_paths(value):
    with pytest.raises(ValidationError):
        SettingsPatch(ignored_task_executables=value)


def test_empty_list_and_mixed_members():
    assert SettingsPatch(ignored_task_executables=[]).model_dump(exclude_unset=True) == {
        "ignored_task_executables": []
    }
    train = dict(process(10), exe="/usr/bin/python")
    xorg = dict(process(11), exe=XORG, ppid=10)
    old = group_processes([train, xorg], [], ignored_executables=[])
    mixed = group_processes([train, xorg], old, ignored_executables=[XORG])
    assert len(mixed) == 1 and not mixed[0]["ignored"]
    assert [m["pid"] for m in mixed[0]["members"]] == [10]


def test_legacy_first_absolute_token_only():
    from gpupm.domain.settings import ignored_process

    assert ignored_process({"command": XORG + " :0"}, [XORG])
    assert ignored_process({"argv": [XORG, ":0"]}, [XORG])
    assert not ignored_process({"exe": "/usr/bin/python", "argv": [XORG]}, [XORG])
    assert not ignored_process({"exe": None, "argv": [XORG]}, [XORG])
    assert not ignored_process({"command": "python " + XORG}, [XORG])
    assert not ignored_process({"command": "Xorg :0"}, [XORG])
    assert not ignored_process({"command": XORG + "-other"}, [XORG])


def test_host_old_records_change_restarts_and_tokens(tmp_path, monkeypatch):
    from gpupm.agent.host import AgentService
    from gpupm.errors import DomainError

    xorg = dict(process(10), exe=XORG, ppid=2)
    train = dict(process(11), exe="/usr/bin/python", ppid=2)
    gpus = [dict(uuid="gpu", memory_used=20, utilization=35)]
    config = dict(store_path=str(tmp_path / "agent.db"), allow_mutations=True)
    service = AgentService(config, collector=lambda: (gpus, [xorg, train], []))
    monkeypatch.setattr(service.accounts, "is_human", lambda uid: True)
    service.call("configure", {"settings": {"ignored_task_executables": []}})
    before = service.call("snapshot")
    assert len(before["tasks"]) == 2 and before["gpus"] == gpus
    task = next(t for t in before["tasks"] if t["members"][0]["pid"] == 10)
    with service.database() as db:
        state = service.load(db)
        state["tasks"][0]["notes"] = "preserve metadata"
        service.save(db, state)
    token = service.call("preview_termination", {"task_id": task["id"]})["token"]
    service.call("configure", {"settings": {"ignored_task_executables": [XORG]}})
    after = service.call("snapshot")
    assert after["gpus"] == before["gpus"]
    hidden = next(t for t in after["tasks"] if t["id"] == task["id"])
    assert hidden["ignored"] and hidden["members"] == []
    assert next(t for t in after["tasks"] if t["id"] != task["id"])["members"][0]["pid"] == 11
    with pytest.raises(DomainError) as error:
        service.call(
            "execute_termination", {"task_id": task["id"], "token": token, "idempotency_key": "stale-test"}
        )
    assert error.value.code == "invalid_preview"
    with service.database() as db:
        assert service.load(db)["jobs"] == {}
    reopened = AgentService(config, collector=lambda: (gpus, [xorg, train], []))
    assert next(t for t in reopened.call("snapshot")["tasks"] if t["id"] == task["id"])["ignored"]
    reopened.call("configure", {"settings": {"ignored_task_executables": []}})
    restored = next(t for t in reopened.call("snapshot")["tasks"] if t["id"] == task["id"])
    assert not restored["ignored"] and restored["members"][0]["pid"] == 10
    again = AgentService(config, collector=lambda: (gpus, [xorg, train], []))
    with again.database() as db:
        assert again.load(db)["settings"]["ignored_task_executables"] == []


@pytest.mark.parametrize(
    "value", [None, "/x", [1], ["relative"], ["/x/*"], ["/x/../y"], ["/x\n"], ["/x"] * 51]
)
def test_root_rejects_invalid_allowlist(tmp_path, value):
    from gpupm.agent.host import AgentService
    from gpupm.errors import DomainError

    service = AgentService({"store_path": str(tmp_path / "agent.db")}, collector=lambda: ([], [], []))
    with pytest.raises(DomainError) as error:
        service.call("configure", {"settings": {"ignored_task_executables": value}})
    assert error.value.code == "invalid_settings"


def test_native_signal_rechecks_exe_after_collection(tmp_path, monkeypatch):
    import signal
    from types import SimpleNamespace
    import gpupm.agent.processes as module
    from gpupm.agent.host import AgentService

    service = AgentService({"store_path": str(tmp_path / "agent.db")}, collector=lambda: ([], [], []))
    member = dict(process(10), exe="/usr/bin/python", ppid=2)
    calls = []
    monkeypatch.setattr(module.os, "pidfd_open", lambda pid: 42, raising=False)
    monkeypatch.setattr(module.os, "close", lambda fd: calls.append(("close", fd)))
    monkeypatch.setattr(
        signal, "pidfd_send_signal", lambda *args: calls.append(("signal", args)), raising=False
    )
    monkeypatch.setattr(module, "proc_identity", lambda pid: member["identity"])
    monkeypatch.setattr(
        module.psutil,
        "Process",
        lambda pid: SimpleNamespace(
            cmdline=lambda: ["python", "train.py"], uids=lambda: SimpleNamespace(real=1000), exe=lambda: XORG
        ),
    )
    monkeypatch.setattr(service.accounts, "is_human", lambda uid: True)
    assert service.signal_member(member, signal.SIGTERM) == "ignored_executable"
    assert calls == [("close", 42)]


def test_queued_targets_and_deadlines_revoked(tmp_path, monkeypatch):
    from gpupm.agent.host import AgentService

    member = dict(process(10), exe=XORG, ppid=2)
    calls = []
    service = AgentService(
        {"store_path": str(tmp_path / "agent.db"), "allow_mutations": True},
        collector=lambda: ([], [member], []),
        signaler=lambda *args: calls.append(args) or "signaled",
        process_checker=lambda identity: "alive",
    )
    monkeypatch.setattr(service.accounts, "is_human", lambda uid: True)
    monkeypatch.setattr(service.accounts, "list", lambda state: [])
    monkeypatch.setattr(service.stop, "wait", lambda seconds: False)
    service.call("configure", {"settings": {"ignored_task_executables": []}})
    task = service.call("snapshot")["tasks"][0]
    with service.database() as db:
        state = service.load(db)
        state["tasks"][0].update(
            policy_status="applied", confirmed_revision=task["revision"], max_runtime_seconds=1
        )
        state["last_heartbeat"] = "2026-10-14T00:00:00+00:00"
        state["jobs"]["queued"] = dict(
            id="queued",
            status="queued",
            task_id=task["id"],
            task_revision=task["revision"],
            targets=[member],
            results=[],
            actor="admin",
        )
        service.save(db, state)
    service.call("configure", {"settings": {"ignored_task_executables": [XORG]}})
    service.execute_job("queued")
    service.tick()
    assert calls == []
    with service.database() as db:
        state = service.load(db)
        assert state["jobs"]["queued"]["results"][0]["term"] == "scope_changed"
        assert not any(e["action"] == "task.deadline" for e in state["events"])


def test_host_default_discovery_and_incomplete_collection_still_filters(tmp_path, monkeypatch):
    from gpupm.agent.host import AgentService

    members = [dict(process(10), exe=XORG), dict(process(11), exe="/usr/bin/python")]
    config = {"store_path": str(tmp_path / "agent.db")}
    service = AgentService(config, collector=lambda: ([], members, []))
    monkeypatch.setattr(service.accounts, "is_human", lambda uid: True)
    assert [t["members"][0]["pid"] for t in service.call("snapshot")["tasks"]] == [11]
    service.call("configure", {"settings": {"ignored_task_executables": []}})
    xorg_task = next(t for t in service.call("snapshot")["tasks"] if t["members"][0]["pid"] == 10)
    service.collector = lambda: ([], [], [{"code": "incomplete"}])
    service.call("configure", {"settings": {"ignored_task_executables": [XORG]}})
    snapshot = service.call("snapshot")
    hidden = next(t for t in snapshot["tasks"] if t["id"] == xorg_task["id"])
    assert snapshot["stale"] and hidden["ignored"] and not hidden["overdue"]
    assert hidden["members"] == [] and hidden["status"] == "finished"


def test_native_collection_keeps_graphics_process_and_metrics(monkeypatch):
    import sys
    from types import SimpleNamespace
    import gpupm.agent.processes as module

    nv = SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlShutdown=lambda: None,
        nvmlDeviceGetCount=lambda: 1,
        nvmlDeviceGetHandleByIndex=lambda index: index,
        nvmlDeviceGetUUID=lambda handle: "gpu",
        nvmlDeviceGetName=lambda handle: "GPU",
        nvmlDeviceGetMemoryInfo=lambda handle: SimpleNamespace(total=100, used=40),
        nvmlDeviceGetUtilizationRates=lambda handle: SimpleNamespace(gpu=25),
        nvmlDeviceGetComputeRunningProcesses=lambda handle: [],
        nvmlDeviceGetGraphicsRunningProcesses=lambda handle: [SimpleNamespace(pid=10, usedGpuMemory=40)],
        NVMLError=RuntimeError,
    )
    native = SimpleNamespace(
        pid=10,
        ppid=lambda: 2,
        info=dict(
            pid=10,
            ppid=2,
            uids=SimpleNamespace(real=1000),
            cmdline=[XORG, ":0"],
            name="Xorg",
            exe=XORG,
            create_time=1,
            status="S",
        ),
    )
    monkeypatch.setitem(sys.modules, "pynvml", nv)
    monkeypatch.setattr(module.Path, "read_text", lambda *args: "boot")
    monkeypatch.setattr(module.psutil, "process_iter", lambda fields: [native])
    monkeypatch.setattr(module, "proc_identity", lambda pid: dict(boot_id="boot", pid=pid, start_ticks=100))
    gpus, members, errors = module.collect()
    assert errors == [] and members[0]["exe"] == XORG
    assert members[0]["gpu_memory"] == {"gpu": 40}
    assert gpus[0]["memory_used"] == 40 and gpus[0]["utilization"] == 25
    assert group_processes(members, [], ignored_executables=[XORG]) == []


def test_ignored_live_leader_does_not_invent_residual_cleanup():
    leader = dict(process(10), exe=XORG)
    child = dict(process(11), exe="/usr/bin/python", ppid=10, gpu_memory={})
    original = group_processes([leader, child], [], ignored_executables=[])
    mixed = group_processes([leader, child], original, ignored_executables=[XORG])[0]
    assert mixed["members"][0]["pid"] == 11
    assert mixed["leaders_present"]
    assert not mixed["orphan_cleanup_due"]


def test_demo_mixed_live_ignored_leader_is_not_residual(tmp_path):
    import json
    import sqlite3
    from gpupm.agent.demo import DemoAgent

    agent = DemoAgent(tmp_path / "demo.db")
    with sqlite3.connect(agent.path) as db:
        state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        state["tasks"][0]["members"][0]["exe"] = XORG
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    task = agent.call("snapshot")["tasks"][0]
    assert not task["ignored"] and len(task["members"]) == 1
    assert task["leaders_present"] and task["status"] == "running"
    assert task["ignored_members"][0]["exe"] == XORG
