import socket
import struct

import pytest

from gpupm.agent.host import AgentService, identity_key, group_processes
from gpupm.agent.accounts import restriction_active
from gpupm.agent.protocol import read_frame, write_frame, MAX_FRAME
from gpupm.errors import DomainError


def process(pid, ppid, gpu=False, command="python train.py", uid=1000):
    return dict(
        identity=dict(boot_id="boot", pid=pid, start_ticks=pid * 10),
        pid=pid,
        ppid=ppid,
        uid=uid,
        username="alice",
        command=command,
        status="S",
        create_time="2026-01-01T00:00:00+00:00",
        gpu_memory={"gpu": 10} if gpu else {},
        evidence="proc",
    )


def test_grouping_does_not_merge_shell_siblings():
    tasks = group_processes(
        [process(1, 0, command="/bin/bash"), process(2, 1, True), process(3, 1, True), process(4, 2)], []
    )
    assert sorted(sorted(m["pid"] for m in t["members"]) for t in tasks) == [[2, 4], [3]]


def test_historic_member_identity_and_orphan_are_preserved():
    tasks = group_processes([process(2, 1, True), process(4, 2)], [])
    old_id = tasks[0]["id"]
    updated = group_processes([process(4, 1)], tasks)
    assert updated[0]["id"] == old_id
    assert updated[0]["members"][0]["pid"] == 4
    assert "orphan" in updated[0]["anomalies"]
    assert len(updated[0]["historic_identities"]) == 2
    reused = group_processes(
        [dict(process(4, 1, True), identity=dict(boot_id="boot", pid=4, start_ticks=999))], updated
    )
    assert reused[-1]["id"] != old_id


def test_restrictions_cannot_cancel_other_causes():
    assert restriction_active({"disabled": False, "deleted_at": "date", "expires_on": None}, False)
    assert restriction_active({"disabled": False, "deleted_at": None, "expires_on": None}, True)
    assert not restriction_active({"disabled": False, "deleted_at": None, "expires_on": None}, False)


def test_frames_limit_and_roundtrip():
    a, b = socket.socketpair()
    try:
        write_frame(a, {"version": 1, "result": {"ok": True}})
        assert read_frame(b)["result"]["ok"]
        a.sendall(struct.pack("!I", MAX_FRAME + 1))
        with pytest.raises(DomainError, match="frame"):
            read_frame(b)
    finally:
        a.close()
        b.close()


def test_readonly_agent_refuses_mutation_and_persists(tmp_path):
    service = AgentService(dict(store_path=str(tmp_path / "state.sqlite")), collector=lambda: ([], [], []))
    with pytest.raises(DomainError) as error:
        service.call("execute_account_change", {"action": "create", "changes": {"username": "alice"}})
    assert error.value.code == "mutations_disabled"
    assert service.call("snapshot")["source"] == "host"
    assert identity_key({"boot_id": "b", "pid": 1, "start_ticks": 2}) == "b:1:2"


def test_safe_paths_reject_links_and_insecure_ancestors(tmp_path):
    from gpupm.agent.accounts import secure_directory

    target = tmp_path / "root"
    target.mkdir(mode=0o700)
    (target / "link").symlink_to(tmp_path)
    with pytest.raises(DomainError):
        secure_directory(target / "link", owner=target.stat().st_uid)
    target.chmod(0o777)
    with pytest.raises(DomainError):
        secure_directory(target, owner=target.stat().st_uid)


def test_sensitive_group_grants_and_keys_are_validated():
    from gpupm.agent.accounts import validate_groups, validate_keys

    with pytest.raises(DomainError):
        validate_groups(["sudo"])
    with pytest.raises(DomainError):
        validate_keys(['command="evil" ssh-ed25519 AAAA'])
    with pytest.raises(DomainError):
        validate_keys(["ssh-ed25519 broken"])


def test_quota_units_and_native_readback():
    from gpupm.agent.storage import quota_blocks, validate_quota

    assert quota_blocks(1025) == 2
    assert quota_blocks(0) == 0
    with pytest.raises(DomainError):
        validate_quota({"soft_bytes": 4096, "hard_bytes": 1024})
    with pytest.raises(DomainError):
        validate_quota({"soft_inodes": -1})
    with pytest.raises(DomainError):
        validate_quota({"hard_bytes": True})


def test_directory_stats_never_follow_links(tmp_path):
    from gpupm.agent.storage import directory_usage

    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "file").write_bytes(b"1234")
    (folder / "outside").symlink_to("/etc")
    result = directory_usage(folder)
    assert result["bytes"] == 4
    assert result["files"] == 2


def test_auth_parser_only_accepts_genuine_numeric_ip():
    from gpupm.agent.login import parse_auth_line

    event = parse_auth_line(
        "Oct 14 12:00:00 server sshd[43]: Accepted publickey for alice from 192.0.2.1 port 4312 ssh2: ED25519 SHA256:abc",
        year=2026,
    )
    assert event["ip"] == "192.0.2.1" and event["result"] == "success"
    assert (
        parse_auth_line(
            "Oct 14 12:00:00 host sshd[1]: Failed password for invalid user bob from evil.example port 1 ssh2",
            year=2026,
        )
        is None
    )


def test_external_password_lock_is_never_unlocked_on_restore():
    from gpupm.agent.accounts import Accounts

    calls = []
    accounts = Accounts({}, lambda argv, **kwargs: calls.append(argv) or "")
    meta = dict(
        disabled=False,
        deleted_at=None,
        expires_on=None,
        agent_restricted=True,
        baseline=dict(shell="/bin/bash", expire="", password="hash", restricted=False),
    )
    accounts.shadow_baseline = lambda name: dict(
        shell="/usr/sbin/nologin", expire="1", password="!!hash", restricted=True
    )
    with pytest.raises(DomainError):
        accounts.apply_login({"username": "alice"}, meta)
    assert not calls


def test_rename_never_overwrites_existing_directory(tmp_path):
    from gpupm.agent.accounts import rename_noreplace

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    fd = __import__("os").open(tmp_path, __import__("os").O_RDONLY)
    try:
        with pytest.raises(DomainError):
            rename_noreplace(fd, "a", fd, "b")
        assert (tmp_path / "a").is_dir() and (tmp_path / "b").is_dir()
    finally:
        __import__("os").close(fd)


def test_new_descendants_join_existing_confirmed_task():
    original = group_processes([process(10, 1, True)], [])
    updated = group_processes([process(10, 1, True), process(11, 10)], original)
    assert len(updated) == 1
    assert {p["pid"] for p in updated[0]["members"]} == {10, 11}
    assert updated[0]["revision"] == original[0]["revision"] + 1


def test_preview_cannot_be_submitted_for_different_task(tmp_path):
    service = AgentService(
        dict(store_path=str(tmp_path / "agent.sqlite"), allow_mutations=True),
        collector=lambda: ([], [process(2, 1, True), process(3, 1, True)], []),
    )
    service.accounts.is_human = lambda uid: uid == 1000
    snapshot = service.call("snapshot")
    tasks = snapshot["tasks"]
    service.call(
        "apply_task_policy",
        dict(task_id=tasks[0]["id"], revision=tasks[0]["revision"], policy={"cleanup_orphans": True}),
    )
    preview = service.call("preview_termination", dict(task_id=tasks[0]["id"]))
    with pytest.raises(DomainError) as error:
        service.call(
            "execute_termination",
            dict(task_id=tasks[1]["id"], token=preview["token"], reason="test", idempotency_key="key"),
        )
    assert error.value.code == "scope_changed"


def test_audit_is_bounded_and_redacts_credentials(tmp_path):
    service = AgentService(dict(store_path=str(tmp_path / "agent.sqlite")), collector=lambda: ([], [], []))
    with service.database() as db:
        state = service.load(db)
        for i in range(103):
            service.event(
                state, {}, "test", i, None, {"password": "secret", "public_keys": ["secret"], "notes": "ok"}
            )
        service.save(db, state)
    first = service.call("audit_since")
    assert len(first["items"]) == 100 and first["has_more"]
    assert first["items"][0]["after"] == {"notes": "ok"}
    assert len(service.call("audit_since", {"cursor": first["cursor"]})["items"]) == 3


def test_signal_uses_pinned_pidfd_and_refuses_reused_pid(monkeypatch):
    import gpupm.agent.processes as module

    identity = {"boot_id": "b", "pid": 55, "start_ticks": 5}
    calls = []
    monkeypatch.setattr(module.os, "pidfd_open", lambda pid: 77, raising=False)
    monkeypatch.setattr(module.os, "close", lambda fd: calls.append(("close", fd)))
    monkeypatch.setattr(module, "proc_identity", lambda pid: {**identity, "start_ticks": 6})
    monkeypatch.setattr(
        __import__("signal"), "pidfd_send_signal", lambda *args: calls.append(("signal", args)), raising=False
    )
    assert module.signal_identity(identity, 15) == "identity_changed"
    assert calls == [("close", 77)]


def test_socket_rejects_unauthorized_peer_before_reading(monkeypatch):
    from gpupm.agent import protocol

    class Socket:
        def settimeout(self, value):
            pass

        def recv(self, count):
            pytest.fail("must not read unauthorized peer")

    monkeypatch.setattr(protocol, "peer_uid", lambda sock: 1111)
    with pytest.raises(DomainError) as exc:
        protocol.handle_connection(Socket(), None, 2222)
    assert exc.value.code == "peer_forbidden"


def test_journal_auth_parser_uses_native_timestamp():
    from gpupm.agent.login import parse_journal_record

    event = parse_journal_record(
        {
            "MESSAGE": "Accepted password for alice from 2001:db8::1 port 3322 ssh2",
            "SYSLOG_IDENTIFIER": "sshd",
            "__REALTIME_TIMESTAMP": "1700000000000000",
        }
    )
    assert event["time"] == "2023-11-14T22:13:20+00:00"
    assert event["ip"] == "2001:db8::1"
    assert parse_journal_record({"MESSAGE": "arbitrary forged text", "SYSLOG_IDENTIFIER": "evil"}) is None


def test_softdelete_retains_identity_and_files_and_other_restrictions():
    from gpupm.agent.accounts import Accounts

    calls = []
    accounts = Accounts({}, lambda argv, **kwargs: calls.append(argv) or "")
    accounts.is_human = lambda uid: uid == 1000
    account = dict(
        id="1000",
        uid=1000,
        gid=1000,
        username="alice",
        primary_group="alice",
        home="/home/alice",
        data_dir="/data/alice",
        managed=True,
        protected=False,
        revision=1,
    )
    meta = dict(
        managed=True,
        revision=1,
        disabled=True,
        deleted_at=None,
        expires_on=None,
        baseline=dict(shell="/bin/bash", password="hash", expire="", restricted=False),
    )
    state = {"accounts": {"1000": meta}}
    accounts.find = lambda state, ident: dict(account, revision=meta["revision"])
    accounts.shadow_baseline = lambda name: dict(
        shell="/usr/sbin/nologin", password="!hash", expire="1", restricted=True
    )
    accounts.execute(state, "delete", "1000", {})
    assert meta["deleted_at"] and meta["disabled"]
    assert all(argv[0] == "usermod" for argv in calls)
    with pytest.raises(DomainError):
        accounts.execute(state, "enable", "1000", {})
    assert meta["disabled"]
    accounts.execute(state, "restore", "1000", {})
    assert meta["deleted_at"] is None and meta["disabled"]
    assert (
        account["uid"] == 1000 and account["home"] == "/home/alice" and account["data_dir"] == "/data/alice"
    )
    assert not any("--unlock" in argv for argv in calls)


def test_policy_restart_requires_new_heartbeat(tmp_path):
    config = {"store_path": str(tmp_path / "agent.sqlite")}

    def collector():
        return [], [process(3, 2, True)], []

    service = AgentService(config, collector=collector)
    service.accounts.is_human = lambda uid: uid == 1000
    task = service.call("snapshot")["tasks"][0]
    task = service.call(
        "apply_task_policy",
        {"task_id": task["id"], "revision": task["revision"], "policy": {"deadline_action": "terminate"}},
    )
    service.call("heartbeat", {"policy_versions": {task["id"]: task["revision"]}})
    restarted = AgentService(config, collector=collector)
    restarted.accounts.is_human = lambda uid: uid == 1000
    assert restarted.call("snapshot")["tasks"][0]["policy_status"] == "awaiting_sync"
    restarted.call("heartbeat", {"policy_versions": {task["id"]: task["revision"] - 1}})
    assert restarted.call("snapshot")["tasks"][0]["policy_status"] == "awaiting_sync"
    restarted.call("heartbeat", {"policy_versions": {task["id"]: task["revision"]}})
    assert restarted.call("snapshot")["tasks"][0]["policy_status"] == "applied"


def test_malformed_ssh_wire_key_is_rejected():
    import base64
    from gpupm.agent.accounts import validate_keys

    blob = (11).to_bytes(4, "big") + b"ssh-ed25519" + (4).to_bytes(4, "big") + b"bad!"
    with pytest.raises(DomainError):
        validate_keys(["ssh-ed25519 " + base64.b64encode(blob).decode()])


def test_quota_native_struct_uses_full_width_and_kib_units(monkeypatch):
    import ctypes
    import gpupm.agent.storage as module

    seen = []

    class Lib:
        def __init__(self):
            def quotactl(command, device, uid, pointer):
                data = ctypes.cast(pointer, ctypes.POINTER(module.Dqblk)).contents
                if command.value & 0xFFFFFFFF == 0x80000800:
                    seen.append((data.bhardlimit, data.ihardlimit, data.valid))
                    return 0
                data.bhardlimit = 2**40
                data.ihardlimit = 2**40
                data.curspace = 1234
                return 0

            self.quotactl = quotactl

    monkeypatch.setattr(module.ctypes, "CDLL", lambda *args, **kwargs: Lib())
    result = module.native_quota(
        "/dev/fake", 1000, {"filesystem_id": "/data", "hard_bytes": 2**50, "hard_inodes": 2**40}
    )
    assert seen == [(2**40, 2**40, 5)]
    assert result["hard_bytes"] == 2**50 and result["hard_inodes"] == 2**40 and result["used_bytes"] == 1234


def test_incomplete_collection_blocks_signal_preview(tmp_path):
    service = AgentService(
        {"store_path": str(tmp_path / "agent.sqlite")},
        collector=lambda: (
            [],
            [process(10, 2, True)],
            [{"code": "nvml_processes_unavailable", "message": "permission"}],
        ),
    )
    snapshot = service.call("snapshot")
    assert snapshot["stale"]
    with pytest.raises(DomainError) as exc:
        service.call("preview_termination", {"task_id": "unconfirmed-task"})
    assert exc.value.code == "stale_collection"


def test_large_audit_entry_does_not_stall_cursor(tmp_path):
    service = AgentService({"store_path": str(tmp_path / "agent.sqlite")}, collector=lambda: ([], [], []))
    with service.database() as db:
        state = service.load(db)
        service.event(state, {}, "large", "host", None, {"notes": "x" * 600000})
        service.save(db, state)
    result = service.call("audit_since")
    assert len(result["items"]) == 1 and not result["has_more"]
    assert result["items"][0]["after"]["truncated"]


def test_reused_parent_pid_cannot_merge_existing_gpu_children():
    items = [process(40, 1), process(2, 40, True), process(3, 40, True)]
    tasks = group_processes(items, [])
    assert sorted(sorted(member["pid"] for member in task["members"]) for task in tasks) == [[2], [3]]


def test_manual_split_membership_survives_descendant_expansion():
    import copy

    root, child, worker = process(20, 1, True), process(21, 20, True), process(22, 21)
    previous = group_processes([root, child], [])
    second = copy.deepcopy(previous[0])
    second.update(id="split", members=[child], historic_identities=[identity_key(child["identity"])])
    previous[0]["members"] = [root]
    previous[0]["historic_identities"] = [identity_key(root["identity"])]
    tasks = group_processes([root, child, worker], previous + [second])
    assert {m["pid"] for m in tasks[0]["members"]} == {20}
    assert {m["pid"] for m in tasks[1]["members"]} == {21, 22}


def test_password_in_preview_is_rejected_before_persistence(tmp_path):
    service = AgentService({"store_path": str(tmp_path / "agent.sqlite")}, collector=lambda: ([], [], []))
    with pytest.raises(DomainError) as exc:
        service.call(
            "preview_account_change",
            {"id": "1000", "revision": 1, "action": "update", "changes": {"password": "secret"}},
        )
    assert exc.value.code == "credentials_in_preview"
    assert b"secret" not in service.path.read_bytes()


def test_configured_device_mismatch_fails_before_provisioning(tmp_path):
    from gpupm.agent.accounts import Accounts

    accounts = Accounts({"data_device": "/dev/null"})
    with pytest.raises(DomainError) as exc:
        accounts.assert_devices(tmp_path, tmp_path)
    assert exc.value.code == "device_mismatch"


def test_storage_acl_capability_does_not_claim_unperformed_check(tmp_path, monkeypatch):
    from gpupm.agent.storage import Storage
    import gpupm.agent.storage as module

    service = AgentService({"store_path": str(tmp_path / "agent.sqlite")}, collector=lambda: ([], [], []))
    service.accounts.list = lambda state: []
    monkeypatch.setattr(module.shutil, "which", lambda tool: "/usr/bin/" + tool)
    with service.database() as db:
        state = service.load(db)
    assert Storage(service).snapshot(state)["capabilities"]["acl"]["status"] == "tools_present_unverified"
    monkeypatch.setattr(module.shutil, "which", lambda tool: None)
    assert Storage(service).snapshot(state)["capabilities"]["acl"]["status"] == "unavailable"


def test_password_reset_keeps_platform_login_lock(monkeypatch):
    import gpupm.agent.accounts as module

    account = dict(id="1000", uid=1000, gid=1000, username="alice", managed=True, protected=False, revision=1)
    meta = dict(
        managed=True,
        revision=1,
        disabled=True,
        deleted_at=None,
        expires_on=None,
        agent_restricted=True,
        baseline=dict(shell="/bin/bash", password="oldhash", expire="", restricted=False),
    )
    native = dict(
        shell="/usr/sbin/nologin", password="!oldhash", expire="1", restricted=True, last_change="100"
    )

    def run(argv, **kwargs):
        if argv[0] == "chpasswd":
            native["password"] = "newhash"
        if "--lock" in argv and not native["password"].startswith("!"):
            native["password"] = "!" + native["password"]
        return ""

    accounts = module.Accounts({}, run)
    accounts.is_human = lambda uid: uid == 1000
    accounts.find = lambda state, ident: dict(account, revision=meta["revision"])
    accounts.shadow_baseline = lambda name: dict(native)
    monkeypatch.setattr(module, "quality_password", lambda password, name: None)
    accounts.execute({"accounts": {"1000": meta}}, "update", "1000", {"password": "valid long password"})
    assert native["password"] == "!newhash" and meta["disabled"]


def test_empty_initial_policy_registration_is_confirmed_only_by_agent(tmp_path):
    service = AgentService(
        {"store_path": str(tmp_path / "agent.sqlite")}, collector=lambda: ([], [process(10, 1, True)], [])
    )
    service.accounts.is_human = lambda uid: uid == 1000
    task = service.call("snapshot")["tasks"][0]
    service.call("heartbeat", {"policy_versions": {task["id"]: task["revision"]}})
    assert service.call("snapshot")["tasks"][0]["policy_status"] == "awaiting_sync"
    applied = service.call(
        "apply_task_policy", {"task_id": task["id"], "revision": task["revision"], "policy": {}}
    )
    service.call("heartbeat", {"policy_versions": {task["id"]: applied["revision"]}})
    assert service.call("snapshot")["tasks"][0]["policy_status"] == "applied"


def test_worker_cleanup_requires_historic_leader_exit():
    leader = process(20, 1, True)
    worker = process(21, 20)
    original = group_processes([leader, worker], [])
    survivors = group_processes([process(21, 1)], original)
    assert survivors[0]["orphan_cleanup_due"]
    assert not group_processes([dict(leader, gpu_memory={}), worker], original)[0]["orphan_cleanup_due"]
    assert not group_processes([process(21, 1, True)], original)[0]["orphan_cleanup_due"]


def test_legacy_cleanup_tick_never_creates_job(tmp_path):
    available = [process(20, 1, True), process(21, 20)]
    service = AgentService(
        {"store_path": str(tmp_path / "agent.sqlite"), "allow_mutations": True, "term_grace_seconds": 0},
        collector=lambda: ([], available, []),
        signaler=lambda identity, sig, uids: "exited",
    )
    service.accounts.is_human = lambda uid: uid == 1000
    service.accounts.list = lambda state: []
    task = service.call("snapshot")["tasks"][0]
    service.call(
        "apply_task_policy",
        {"task_id": task["id"], "revision": task["revision"], "policy": {"cleanup_orphans": True}},
    )
    available[:] = [process(21, 1)]
    task = service.call("snapshot")["tasks"][0]
    service.tick()
    with service.database() as db:
        assert not service.load(db)["jobs"]
    applied = service.call(
        "apply_task_policy",
        {"task_id": task["id"], "revision": task["revision"], "policy": {"cleanup_orphans": True}},
    )
    service.call("heartbeat", {"policy_versions": {task["id"]: applied["revision"]}})
    service.tick()
    for worker in list(service.workers.values()):
        worker.join(timeout=3)
    with service.database() as db:
        assert not service.load(db)["jobs"]


def test_job_records_residual_process_instead_of_signal_success(tmp_path):
    service = AgentService(
        {"store_path": str(tmp_path / "agent.sqlite"), "allow_mutations": True, "term_grace_seconds": 0},
        collector=lambda: ([], [process(20, 2, True)], []),
        signaler=lambda identity, sig, uids: "signaled",
        process_checker=lambda identity: "alive",
    )
    service.accounts.is_human = lambda uid: uid == 1000
    task = service.call("snapshot")["tasks"][0]
    preview = service.call("preview_termination", {"task_id": task["id"]})
    job = service.call(
        "execute_termination", {"token": preview["token"], "reason": "test", "idempotency_key": "residual"}
    )
    for worker in list(service.workers.values()):
        worker.join(timeout=5)
    finished = service.call("job_status", {"id": job["id"]})
    assert finished["status"] == "partial"
    assert finished["results"][0]["final"] == "alive"


def test_restart_rechecks_interrupted_targets_without_replaying_signals(tmp_path):
    config = {"store_path": str(tmp_path / "agent.sqlite")}
    service = AgentService(config, collector=lambda: ([], [], []))
    member = process(20, 2, True)
    with service.database() as db:
        state = service.load(db)
        state["jobs"]["job"] = dict(
            id="job",
            status="running",
            results=[{"identity": member["identity"], "term": "signaled"}],
            targets=[member],
        )
        service.save(db, state)
    restarted = AgentService(
        config,
        collector=lambda: ([], [], []),
        signaler=lambda *args: pytest.fail("must not signal on recovery"),
        process_checker=lambda identity: "alive",
    )
    job = restarted.call("job_status", {"id": "job"})
    assert job["status"] == "interrupted" and job["results"][-1]["status"] == "alive"


def test_storage_alerts_include_capacity_inode_quota_and_share():
    from gpupm.agent.storage import storage_alerts

    fs = [dict(id="/data", path="/data", total=1000, available=50, total_inodes=100, available_inodes=15)]
    users = [
        dict(
            account_id="1000",
            username="alice",
            home_bytes=100,
            data_bytes=850,
            home_files=1,
            data_files=5,
            home_filesystem_id="/data",
            data_filesystem_id="/data",
        )
    ]
    quotas = [
        dict(
            account_id="1000",
            filesystem_id="/data",
            status="applied",
            used_bytes=95,
            hard_bytes=100,
            used_inodes=9,
            hard_inodes=10,
        )
    ]
    shares = [dict(id="shared", name="project", path="/data/shared/project", usage_bytes=950, usage_files=10)]
    alerts = storage_alerts(fs, users, shares, quotas, 80, 90)
    assert {a["scope"] for a in alerts} == {"filesystem", "user_directory", "user_quota", "share"}
    assert any(a["metric"] == "inodes" and a["severity"] == "warning" for a in alerts)
    assert any(a["metric"] == "bytes" and a["severity"] == "critical" for a in alerts)
    assert storage_alerts([dict(id="/data", path="/data", total=0, available=0)], [], [], [], 80, 90) == []


def test_storage_alert_log_records_only_transitions(tmp_path, monkeypatch):
    import gpupm.agent.storage as module

    service = AgentService({"store_path": str(tmp_path / "agent.sqlite")}, collector=lambda: ([], [], []))
    service.accounts.list = lambda state: []
    available = [5]
    monkeypatch.setattr(
        module,
        "filesystems",
        lambda: [
            dict(
                id="/data",
                path="/data",
                total=100,
                available=available[0],
                total_inodes=0,
                available_inodes=0,
            )
        ],
    )
    with service.database() as db:
        state = service.load(db)
        storage = module.Storage(service)
        storage.snapshot(state)
        storage.snapshot(state)
        assert len(state["events"]) == 1
        available[0] = 25
        storage.snapshot(state)
        assert len(state["events"]) == 2 and state["events"][-1]["result"] == "resolved"


def test_generic_global_user_sockets_do_not_block_idle_rename(tmp_path):
    from gpupm.agent.accounts import user_service_configuration

    home = tmp_path / "alice"
    home.mkdir()
    global_units = tmp_path / "global"
    global_units.mkdir()
    (global_units / "sockets.target.wants").mkdir()
    (global_units / "dbus.socket").write_text("[Socket]\nListenStream=%t/bus\n")
    (global_units / "sockets.target.wants/dbus.socket").symlink_to("../dbus.socket")
    account = {"username": "alice", "uid": 1000, "home": str(home), "data_dir": "/data/alice"}
    assert user_service_configuration(account, [global_units]) == []
    (global_units / "training.service").write_text(
        "[Service]\nExecStart=/bin/python " + str(home) + "/train.py\n"
    )
    assert user_service_configuration(account, [global_units])[0]["kind"] == "global_user_service_reference"
    (global_units / "training.service").unlink()
    enabled = home / ".config/systemd/user/default.target.wants"
    enabled.mkdir(parents=True)
    (enabled / "train.service").symlink_to("../train.service")
    assert user_service_configuration(account, [global_units])[0]["kind"] == "user_service_config"


def test_primary_group_change_uses_validated_native_gid_without_directory_migration(monkeypatch):
    import types
    import gpupm.agent.accounts as module

    calls = []
    account = dict(
        id="1000",
        uid=1000,
        gid=1000,
        username="alice",
        primary_group="alice",
        home="/home/alice",
        data_dir="/data/alice",
        managed=True,
        protected=False,
        revision=1,
    )
    meta = dict(
        managed=True,
        revision=1,
        disabled=False,
        deleted_at=None,
        baseline=dict(shell="/bin/bash", password="hash", expire="", restricted=False),
    )
    accounts = module.Accounts({}, lambda argv, **kwargs: calls.append(argv) or "")
    accounts.is_human = lambda uid: uid == 1000
    accounts.find = lambda state, ident: dict(account, revision=meta["revision"])
    accounts.shadow_baseline = lambda name: dict(meta["baseline"])
    accounts.groups = lambda state: [dict(name="research", assignable=True)]
    accounts.assert_human_group = lambda name: None
    monkeypatch.setattr(module.grp, "getgrnam", lambda name: types.SimpleNamespace(gr_gid=2000, gr_name=name))
    accounts.execute({"accounts": {"1000": meta}}, "update", "1000", {"primary_group": "research"})
    assert calls == [
        ["usermod", "--append", "--groups", "human", "alice"],
        ["usermod", "--gid", "research", "alice"],
    ]
    assert account["home"] == "/home/alice" and account["data_dir"] == "/data/alice"
    with pytest.raises(DomainError):
        accounts.execute({"accounts": {"1000": meta}}, "update", "1000", {"primary_group": "sudo"})


def test_shell_and_ssh_ancestors_are_context_only():
    processes = [
        process(1, 0, command="init"),
        process(5, 1, command="sshd"),
        process(10, 5, command="/bin/bash"),
        process(20, 10, True),
        process(21, 20),
    ]
    task = group_processes(processes, [])[0]
    assert {p["pid"] for p in task["members"]} == {20, 21}
    assert {p["pid"] for p in task["context"]} == {1, 5, 10}


def test_sustained_d_state_tracks_same_identity_and_resets_on_recovery(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import gpupm.agent.processes as module

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(module, "utcnow", lambda: now)
    member = dict(process(20, 10, True), status="disk-sleep")
    task = group_processes([member], [])[0]
    assert task["members"][0]["uninterruptible_seconds"] == 0
    now += timedelta(seconds=31)
    task = group_processes([member], [task])[0]
    assert "uninterruptible_sustained" in task["anomalies"]
    assert task["members"][0]["uninterruptible_seconds"] == 31
    task = group_processes([process(20, 10, True)], [task])[0]
    assert "uninterruptible_sustained" not in task["anomalies"] and not task["blocked_since"]


def test_account_preview_reports_current_activity_and_preserves_files(tmp_path):
    service = AgentService({"store_path": str(tmp_path / "agent.sqlite")}, collector=lambda: ([], [], []))
    account = dict(
        id="1000",
        username="alice",
        uid=1000,
        gid=1000,
        home="/home/alice",
        data_dir="/data/alice",
        revision=1,
        protected=False,
        managed=True,
    )
    activity = {
        "processes": [{"pid": 42}],
        "sessions": [],
        "scheduled": [],
        "coverage": {"processes": "available"},
    }
    service.accounts.writable = lambda *args, **kwargs: account
    service.accounts.activity = lambda *args: activity
    preview = service.call(
        "preview_account_change", {"id": "1000", "revision": 1, "action": "delete", "changes": {}}
    )
    assert preview["activity"] == activity and preview["paths"] == {
        "home": "/home/alice",
        "data_dir": "/data/alice",
    }
    assert "Existing processes" in preview["impact"]


def test_unknown_username_login_failure_is_not_associated_with_later_account(monkeypatch):
    import types
    import gpupm.agent.login as module

    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: types.SimpleNamespace(pw_uid=1000))
    event = module.parse_auth_line(
        "Oct 14 12:00:00 server sshd[43]: Failed password for invalid user alice from 192.0.2.1 port 4312 ssh2",
        year=2026,
    )
    assert event["account_id"] is None


def test_account_list_last_success_login_uses_only_known_records(monkeypatch):
    import types
    import gpupm.agent.accounts as module

    entry = types.SimpleNamespace(
        pw_name="alice", pw_uid=1000, pw_gid=1000, pw_shell="/bin/bash", pw_dir="/home/alice"
    )
    accounts = module.Accounts({})
    accounts.local_entries = lambda: [entry]
    accounts.shadow_baseline = lambda name: dict(expire="")
    monkeypatch.setattr(module.grp, "getgrall", lambda: [])
    monkeypatch.setattr(module.grp, "getgrgid", lambda gid: types.SimpleNamespace(gr_name="alice"))
    state = {
        "accounts": {},
        "login_events": [
            dict(
                username="alice",
                result="success",
                time="2026-01-02T00:00:00+00:00",
                ip="192.0.2.1",
                method="publickey",
            ),
            dict(
                username="alice",
                result="failure",
                time="2026-01-03T00:00:00+00:00",
                ip="192.0.2.2",
                method="password",
            ),
        ],
    }
    account = accounts.list(state)[0]
    assert account["last_success_login"]["ip"] == "192.0.2.1"
    assert "ingested OpenSSH" in account["login_coverage"]


def test_external_login_restrictions_before_first_disable_are_retained():
    import gpupm.agent.accounts as module

    account = dict(id="1000", uid=1000, gid=1000, username="alice", managed=True, protected=False, revision=1)
    meta = dict(
        managed=True,
        revision=1,
        disabled=False,
        deleted_at=None,
        baseline=dict(shell="/bin/bash", password="hash", expire="", restricted=False),
    )
    native = dict(
        shell="/usr/sbin/nologin", password="!hash", expire="25000", restricted=True, last_change="100"
    )

    def run(argv, **kwargs):
        if "--lock" in argv and not native["password"].startswith("!"):
            native["password"] = "!" + native["password"]
        if "--unlock" in argv:
            native["password"] = native["password"].removeprefix("!")
        if "--shell" in argv:
            native["shell"] = argv[argv.index("--shell") + 1]
        if "--expiredate" in argv:
            native["expire"] = argv[argv.index("--expiredate") + 1]
        return ""

    accounts = module.Accounts({}, run)
    accounts.is_human = lambda uid: uid == 1000
    accounts.find = lambda state, ident: dict(account, revision=meta["revision"])
    accounts.shadow_baseline = lambda name: dict(native)
    state = {"accounts": {"1000": meta}}
    accounts.execute(state, "disable", "1000", {})
    accounts.execute(state, "enable", "1000", {})
    assert (
        native["password"] == "!hash"
        and native["shell"] == "/usr/sbin/nologin"
        and native["expire"] == "25000"
    )


def test_password_reset_preserves_new_external_lock_after_adoption(monkeypatch):
    import gpupm.agent.accounts as module

    account = dict(id="1000", uid=1000, gid=1000, username="alice", managed=True, protected=False, revision=1)
    meta = dict(
        managed=True,
        revision=1,
        disabled=False,
        deleted_at=None,
        baseline=dict(shell="/bin/bash", password="hash", expire="", restricted=False),
    )
    native = dict(shell="/bin/bash", password="!hash", expire="", restricted=True, last_change="100")

    def run(argv, **kwargs):
        if argv[0] == "chpasswd":
            native["password"] = "newhash"
        if "--lock" in argv and not native["password"].startswith("!"):
            native["password"] = "!" + native["password"]
        return ""

    accounts = module.Accounts({}, run)
    accounts.is_human = lambda uid: uid == 1000
    accounts.find = lambda state, ident: dict(account, revision=meta["revision"])
    accounts.shadow_baseline = lambda name: dict(native)
    monkeypatch.setattr(module, "quality_password", lambda *args: None)
    accounts.execute({"accounts": {"1000": meta}}, "update", "1000", {"password": "strong long password"})
    assert native["password"] == "!newhash"


def test_storage_walk_does_not_hold_authority_lock(tmp_path, monkeypatch):
    import threading
    import gpupm.agent.storage as module

    service = AgentService({"store_path": str(tmp_path / "agent.sqlite")}, collector=lambda: ([], [], []))
    service.accounts.list = lambda state: [
        dict(id="1000", username="alice", uid=1000, managed=True, home=str(tmp_path), data_dir=str(tmp_path))
    ]
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def usage(path):
        entered.set()
        assert release.wait(3)
        return dict(bytes=1, files=1, status="available")

    monkeypatch.setattr(module, "directory_usage", usage)
    monkeypatch.setattr(module, "filesystems", lambda: [])
    scanner = threading.Thread(target=service.collect_storage)
    scanner.start()
    assert entered.wait(1)

    def heartbeat():
        service.call("heartbeat", {"policy_versions": {}})
        service.tick()
        completed.set()

    worker = threading.Thread(target=heartbeat)
    worker.start()
    try:
        assert completed.wait(1), "storage traversal blocked heartbeat/process collection"
    finally:
        release.set()
        scanner.join(timeout=3)
        worker.join(timeout=3)
    assert service.call("storage_snapshot")["users"][0]["home_bytes"] == 1


def test_account_lifecycle_blocks_uid_reuse_and_preserves_original_policy(monkeypatch):
    import types
    import gpupm.agent.accounts as module

    entries = [
        types.SimpleNamespace(
            pw_name="alice", pw_uid=1000, pw_gid=1000, pw_shell="/bin/bash", pw_dir="/home/alice"
        )
    ]
    accounts = module.Accounts({})
    accounts.local_entries = lambda: entries
    accounts.shadow_baseline = lambda name: {"expire": ""}
    monkeypatch.setattr(module.grp, "getgrall", lambda: [])
    monkeypatch.setattr(module.grp, "getgrgid", lambda gid: types.SimpleNamespace(gr_name="ordinary"))
    state = {
        "accounts": {
            "1000": dict(
                managed=True,
                data_dir="/data/alice",
                revision=3,
                disabled=True,
                deleted_at="old",
                baseline={"password": "hash"},
            )
        },
        "events": [],
    }
    original = accounts.list(state)[0]
    assert original["managed"] and original["lifecycle_id"]
    entries.clear()
    assert accounts.list(state) == []
    entries.append(
        types.SimpleNamespace(
            pw_name="bob", pw_uid=1000, pw_gid=1000, pw_shell="/bin/bash", pw_dir="/home/bob"
        )
    )
    reused = accounts.list(state)[0]
    assert reused["lifecycle_id"] != original["lifecycle_id"]
    assert (
        not reused["managed"]
        and not reused["disabled"]
        and reused["deleted_at"] is None
        and reused["data_dir"] is None
    )
    assert reused["login_policy_status"] == "identity_conflict"
    with pytest.raises(DomainError) as exc:
        accounts.writable(state, "1000", adopt=True)
    assert exc.value.code == "identity_conflict"
    assert state["account_history"][0]["metadata"]["data_dir"] == "/data/alice"


def test_native_username_home_drift_invalidates_management(monkeypatch):
    import types
    import gpupm.agent.accounts as module

    entries = [
        types.SimpleNamespace(
            pw_name="alice", pw_uid=1000, pw_gid=1000, pw_shell="/bin/bash", pw_dir="/home/alice"
        )
    ]
    accounts = module.Accounts({})
    accounts.local_entries = lambda: entries
    accounts.shadow_baseline = lambda name: {"expire": ""}
    monkeypatch.setattr(module.grp, "getgrall", lambda: [])
    monkeypatch.setattr(module.grp, "getgrgid", lambda gid: types.SimpleNamespace(gr_name="ordinary"))
    state = {"accounts": {"1000": dict(managed=True, data_dir="/data/alice", revision=1)}, "events": []}
    original = accounts.list(state)[0]
    entries[0].pw_dir = "/home/elsewhere"
    changed = accounts.list(state)[0]
    assert changed["lifecycle_id"] != original["lifecycle_id"] and not changed["managed"]
    assert state["events"][-1]["action"] == "account.identity_conflict"


def test_numeric_expected_mount_ids_reject_fallback_before_creation(tmp_path):
    import os
    from gpupm.agent.accounts import Accounts

    actual = os.stat(tmp_path).st_dev
    Accounts({"home_dev_id": actual, "data_dev_id": actual}).assert_devices(tmp_path, tmp_path)
    with pytest.raises(DomainError) as exc:
        Accounts({"data_dev_id": actual + 1}).assert_devices(tmp_path, tmp_path)
    assert exc.value.code == "device_mismatch"
    with pytest.raises(DomainError):
        Accounts({"data_dev_id": 0}).assert_devices(tmp_path, tmp_path)


def test_authorized_rename_anchor_keeps_lifecycle_id(monkeypatch):
    import types
    import gpupm.agent.accounts as module

    entries = [
        types.SimpleNamespace(
            pw_name="alice", pw_uid=1000, pw_gid=1000, pw_shell="/bin/bash", pw_dir="/home/alice"
        )
    ]
    accounts = module.Accounts({})
    accounts.local_entries = lambda: entries
    accounts.shadow_baseline = lambda name: {"expire": ""}
    monkeypatch.setattr(module.grp, "getgrall", lambda: [])
    monkeypatch.setattr(module.grp, "getgrgid", lambda gid: types.SimpleNamespace(gr_name="ordinary"))
    state = {"accounts": {"1000": dict(managed=True, data_dir="/data/alice", revision=1)}, "events": []}
    original = accounts.list(state)[0]
    entries[0].pw_name = "bob"
    entries[0].pw_dir = "/home/bob"
    state["account_observations"]["1000"].update(username="bob", home="/home/bob")
    state["accounts"]["1000"].update(identity_username="bob", identity_home="/home/bob", data_dir="/data/bob")
    renamed = accounts.list(state)[0]
    assert renamed["lifecycle_id"] == original["lifecycle_id"] and renamed["managed"]


def test_new_policy_requires_its_own_persisted_revision_heartbeat(tmp_path):
    service = AgentService(
        {"store_path": str(tmp_path / "agent.sqlite"), "allow_mutations": True, "term_grace_seconds": 0},
        collector=lambda: ([], [process(20, 2, True)], []),
        signaler=lambda *args: "exited",
        process_checker=lambda identity: "exited",
    )
    service.accounts.is_human = lambda uid: uid == 1000
    service.accounts.list = lambda state: []
    task = service.call("snapshot")["tasks"][0]
    old = service.call(
        "apply_task_policy", {"task_id": task["id"], "revision": task["revision"], "policy": {}}
    )
    service.call("heartbeat", {"policy_versions": {task["id"]: old["revision"]}})
    newer = service.call(
        "apply_task_policy",
        {
            "task_id": task["id"],
            "revision": old["revision"],
            "policy": {"expires_at": "2020-01-01T00:00:00+00:00", "deadline_action": "terminate"},
        },
    )
    assert newer["policy_status"] == "awaiting_sync" and newer["confirmed_revision"] is None
    service.tick()
    with service.database() as db:
        assert not service.load(db)["jobs"]
    service.call("heartbeat", {"policy_versions": {task["id"]: old["revision"]}})
    service.tick()
    with service.database() as db:
        assert not service.load(db)["jobs"]
    service.call("heartbeat", {"policy_versions": {task["id"]: newer["revision"]}})
    service.tick()
    for worker in list(service.workers.values()):
        worker.join(timeout=3)
    with service.database() as db:
        assert len(service.load(db)["jobs"]) == 1


def test_account_effective_expiry_excludes_platform_login_block_marker(monkeypatch):
    import types
    import gpupm.agent.accounts as module
    from datetime import datetime, timezone

    now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(module, "utcnow", lambda: now)
    entry = types.SimpleNamespace(
        pw_name="alice", pw_uid=1000, pw_gid=1000, pw_shell="/usr/sbin/nologin", pw_dir="/home/alice"
    )
    accounts = module.Accounts({})
    accounts.local_entries = lambda: [entry]
    accounts.shadow_baseline = lambda name: {"expire": "1"}
    monkeypatch.setattr(module.grp, "getgrall", lambda: [])
    monkeypatch.setattr(module.grp, "getgrgid", lambda gid: types.SimpleNamespace(gr_name="alice"))
    meta = dict(
        managed=True,
        data_dir="/data/alice",
        agent_restricted=True,
        expires_on="2026-10-14",
        baseline={"expire": ""},
    )
    state = {"accounts": {"1000": meta}}
    listed = accounts.list(state)[0]
    assert listed["expires_effective_at"] == "2026-10-14T00:00:00+00:00" and listed["status"] == "expired"
    meta["expires_on"] = None
    meta["disabled"] = True
    listed = accounts.list(state)[0]
    assert listed["expires_effective_at"] is None and listed["status"] == "disabled"
    meta["disabled"] = False
    meta["baseline"]["expire"] = str(int(datetime(2026, 10, 13, tzinfo=timezone.utc).timestamp()) // 86400)
    listed = accounts.list(state)[0]
    assert listed["expires_effective_at"] == "2026-10-13T00:00:00+00:00" and listed["status"] == "expired"


def test_runtime_settings_and_policy_freshness_follow_persisted_configuration(tmp_path):
    service = AgentService(
        {"store_path": str(tmp_path / "agent.sqlite"), "scan_interval_seconds": 7},
        collector=lambda: ([], [], []),
    )
    assert service.runtime_setting("scan_interval_seconds", 5) == 7
    with service.database() as db:
        assert service.policy_freshness(service.load(db)) == 30
    service.call(
        "configure",
        {
            "settings": {
                "scan_interval_seconds": 60,
                "storage_scan_interval_seconds": 120,
                "term_grace_seconds": 3,
            }
        },
    )
    assert service.runtime_setting("scan_interval_seconds", 5) == 60
    assert service.runtime_setting("storage_scan_interval_seconds", 900) == 120
    assert service.runtime_setting("term_grace_seconds", 10) == 3
    with service.database() as db:
        assert service.policy_freshness(service.load(db)) == 180


def test_termination_grace_is_current_setting_captured_at_job_start(tmp_path):
    service = AgentService(
        {"store_path": str(tmp_path / "agent.sqlite"), "term_grace_seconds": 10},
        collector=lambda: ([], [process(20, 2, True)], []),
        signaler=lambda *args: "exited",
        process_checker=lambda identity: "exited",
    )
    task = service.call("snapshot")["tasks"][0]
    service.call("configure", {"settings": {"term_grace_seconds": 3}})
    calls = []

    class Stop:
        def is_set(self):
            return False

        def wait(self, seconds):
            calls.append(seconds)
            service.call("configure", {"settings": {"term_grace_seconds": 30}})
            return False

    service.stop = Stop()
    with service.database() as db:
        state = service.load(db)
        state["jobs"]["test"] = dict(
            id="test",
            status="queued",
            targets=task["members"],
            task_id=task["id"],
            task_revision=task["revision"],
            results=[],
            actor="admin",
        )
        service.save(db, state)
    service.execute_job("test")
    assert calls == [3]
    assert service.call("job_status", {"id": "test"})["term_grace_seconds"] == 3
    assert service.runtime_setting("term_grace_seconds", 10) == 30


def test_runtime_interval_wait_wakes_for_shorter_configuration(tmp_path):
    import threading
    import time

    service = AgentService({"store_path": str(tmp_path / "agent.sqlite")}, collector=lambda: ([], [], []))
    service.call("configure", {"settings": {"storage_scan_interval_seconds": 900}})
    finished = threading.Event()
    waiter = threading.Thread(
        target=lambda: (service.wait_interval("storage_scan_interval_seconds", 900), finished.set())
    )
    waiter.start()
    time.sleep(0.03)
    service.call("configure", {"settings": {"storage_scan_interval_seconds": 1}})
    try:
        assert finished.wait(1.5)
    finally:
        service.stop.set()
        waiter.join(timeout=2)


def test_unknown_python_supervisor_does_not_merge_or_join_gpu_tasks():
    items = [process(10, 1, command="python supervisor.py"), process(20, 10, True), process(30, 10, True)]
    tasks = group_processes(items, [])
    assert sorted(sorted(p["pid"] for p in task["members"]) for task in tasks) == [[20], [30]]
    assert all(10 in {p["pid"] for p in task["context"]} for task in tasks)


@pytest.mark.parametrize(
    "command",
    [
        "/venv/bin/torchrun --nproc-per-node=2 train.py",
        "python -m torch.distributed.run --nproc_per_node=2 train.py",
        "/venv/bin/python /venv/bin/torchrun --nproc-per-node=2 train.py",
    ],
)
def test_recognized_torch_launcher_groups_confirmed_gpu_workers(command):
    items = [process(10, 1, command=command), process(20, 10, True), process(30, 10, True)]
    tasks = group_processes(items, [])
    assert len(tasks) == 1 and {p["pid"] for p in tasks[0]["members"]} == {10, 20, 30}


def test_failed_rename_retains_recovery_guard_and_tick_cannot_unlock(tmp_path, monkeypatch):
    import os
    import gpupm.agent.accounts as module

    home_base = tmp_path / "home"
    data_base = tmp_path / "data"
    home_base.mkdir()
    data_base.mkdir()
    (home_base / "alice").mkdir()
    (data_base / "alice").mkdir()
    (home_base / "alice/data").symlink_to(data_base / "alice")
    account = dict(
        id=str(os.getuid()),
        uid=os.getuid(),
        gid=os.getgid(),
        username="alice",
        home=str(home_base / "alice"),
        data_dir=str(data_base / "alice"),
        managed=True,
        protected=False,
        revision=1,
    )
    meta = dict(
        managed=True,
        data_dir=account["data_dir"],
        revision=1,
        disabled=False,
        deleted_at=None,
        baseline=dict(shell="/bin/bash", password="hash", expire="", restricted=False),
    )
    calls = []
    accounts = module.Accounts(
        {"home_base": str(home_base), "data_base": str(data_base)},
        lambda argv, **kwargs: calls.append(argv) or "",
    )
    monkeypatch.setattr(module, "secure_directory", lambda path: __import__("pathlib").Path(path))
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    checks = []

    def idle(state, item):
        checks.append(True)
        if len(checks) == 2:
            raise DomainError("account_active", "activity appeared")

    accounts.assert_idle = idle
    state = {"accounts": {account["id"]: meta}}
    with pytest.raises(DomainError):
        accounts.rename(state, account, meta, "bob")
    assert meta["rename_recovery_required"] and meta["agent_restricted"]
    assert (home_base / "alice").is_dir() and (data_base / "alice").is_dir()
    service = AgentService(
        {"store_path": str(tmp_path / "agent.sqlite"), "allow_mutations": True},
        collector=lambda: ([], [], []),
    )
    with service.database() as db:
        saved = service.load(db)
        saved["accounts"][account["id"]] = meta
        service.save(db, saved)
    service.accounts.list = lambda state: [account]
    service.accounts.apply_login = lambda *args: pytest.fail(
        "failed rename must not be automatically unlocked"
    )
    service.tick()
    accounts.find = lambda state, ident: account
    with pytest.raises(DomainError) as exc:
        accounts.writable(state, account["id"])
    assert exc.value.code == "rename_recovery_required"


def test_human_identity_uses_exact_native_group_membership(monkeypatch):
    import types
    from gpupm.agent import accounts as module

    entries = [
        types.SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=gid)
        for name, uid, gid in [("primary", 1001, 2000), ("member", 1002, 1002), ("other", 1003, 1003)]
    ]
    accounts = module.Accounts({})
    accounts.local_entries = lambda: entries
    monkeypatch.setattr(
        module.grp, "getgrnam", lambda name: types.SimpleNamespace(gr_gid=2000, gr_mem=["member"])
    )
    assert accounts.is_human(1001)
    assert accounts.is_human(1002)
    assert not accounts.is_human(1003)
    assert not accounts.is_human(9999)
    monkeypatch.setattr(module.grp, "getgrnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    assert not accounts.is_human(1001)


def test_native_nonhuman_task_policy_and_termination_are_readonly(tmp_path):
    service = AgentService(
        {"store_path": str(tmp_path / "agent.sqlite"), "allow_mutations": True},
        collector=lambda: ([], [process(20, 2, True)], []),
    )
    service.accounts.is_human = lambda uid: False
    task = service.call("snapshot")["tasks"][0]
    assert task["is_human"] is False
    for method, params in [
        ("apply_task_policy", dict(task_id=task["id"], revision=task["revision"], policy={})),
        ("preview_termination", dict(task_id=task["id"])),
        (
            "apply_membership",
            dict(
                task_id=task["id"],
                revision=task["revision"],
                action="exclude",
                excluded_identities=[task["members"][0]["identity"]],
            ),
        ),
    ]:
        with pytest.raises(DomainError) as error:
            service.call(method, params)
        assert error.value.code == "non_human_readonly"


def test_nonhuman_account_cannot_be_adopted(monkeypatch):
    from gpupm.agent.accounts import Accounts

    accounts = Accounts({})
    accounts.find = lambda state, ident: dict(
        id="1001", uid=1001, username="ordinary", protected=False, managed=False, is_human=True
    )
    accounts.is_human = lambda uid: False
    with pytest.raises(DomainError) as error:
        accounts.writable({"accounts": {}}, "1001", adopt=True)
    assert error.value.code == "non_human_readonly"


def test_job_stops_remaining_signals_after_human_membership_removed(tmp_path):
    import signal

    membership = {"active": True}
    signals = []

    def signaler(identity, sig, uids):
        signals.append(sig)
        membership["active"] = False
        return "signaled"

    service = AgentService(
        {
            "store_path": str(tmp_path / "agent.sqlite"),
            "term_grace_seconds": 0,
            "termination_recheck_seconds": 0,
        },
        collector=lambda: ([], [process(20, 2, True), process(21, 20)], []),
        signaler=signaler,
        process_checker=lambda identity: "alive",
    )
    service.accounts.is_human = lambda uid: uid == 1000 and membership["active"]
    task = service.call("snapshot")["tasks"][0]
    with service.database() as db:
        state = service.load(db)
        state["jobs"]["queued"] = dict(
            id="queued",
            task_id=task["id"],
            task_revision=task["revision"],
            targets=task["members"],
            actor="admin",
        )
        service.save(db, state)
    service.execute_job("queued")
    assert signals == [signal.SIGTERM]
    with service.database() as db:
        results = service.load(db)["jobs"]["queued"]["results"]
        assert results[1]["term"] == "scope_changed"
        assert results[0]["kill"] == "scope_changed"


def test_creation_accepts_implicit_missing_human_but_validates_other_groups(monkeypatch):
    from gpupm.agent import accounts as module

    accounts = module.Accounts({})
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    monkeypatch.setattr(module.grp, "getgrnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    monkeypatch.setattr(module, "quality_password", lambda *args: None)

    def provisioning_boundary(path):
        raise DomainError("provisioning_boundary", "reached provisioning")

    monkeypatch.setattr(module, "secure_directory", provisioning_boundary)
    for groups, expected in [
        (["human"], "provisioning_boundary"),
        (["human", "missing"], "group_missing"),
        (["human", "sudo"], "protected_group"),
    ]:
        with pytest.raises(DomainError) as error:
            accounts.execute(
                {"accounts": {}},
                "create",
                None,
                {"username": "newperson", "password": "long test password", "groups": groups},
            )
        assert error.value.code == expected


def test_human_group_creation_checks_native_gid_and_locality(monkeypatch):
    import types
    from gpupm.agent import accounts as module

    native = {}
    commands = []

    def lookup(name):
        if name not in native:
            raise KeyError(name)
        return native[name]

    def run(argv):
        commands.append(argv)
        native["human"] = types.SimpleNamespace(gr_name="human", gr_gid=2000)

    accounts = module.Accounts({}, run)
    monkeypatch.setattr(module.grp, "getgrnam", lookup)
    monkeypatch.setattr(module.Path, "read_text", lambda self: "human:x:2000:\n")
    accounts.ensure_human_group()
    accounts.ensure_human_group()
    assert commands == [["groupadd", "human"]]
    native["human"].gr_gid = 10
    with pytest.raises(DomainError, match="system group"):
        accounts.ensure_human_group()
    native["human"].gr_gid = 2000
    monkeypatch.setattr(module.Path, "read_text", lambda self: "")
    with pytest.raises(DomainError, match="local group"):
        accounts.ensure_human_group()


def test_native_group_scope_includes_primary_nonhuman_members(monkeypatch):
    import types
    from gpupm.agent import accounts as module

    accounts = module.Accounts({})
    accounts.is_human = lambda uid: uid == 1001
    entries = [
        types.SimpleNamespace(pw_name="humanuser", pw_uid=1001, pw_gid=3000),
        types.SimpleNamespace(pw_name="other", pw_uid=1002, pw_gid=2000),
    ]
    monkeypatch.setattr(
        module.grp, "getgrnam", lambda name: types.SimpleNamespace(gr_gid=2000, gr_mem=["humanuser"])
    )
    monkeypatch.setattr(module.pwd, "getpwall", lambda: entries)
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: next(e for e in entries if e.pw_name == name))
    with pytest.raises(DomainError) as error:
        accounts.assert_human_group("research")
    assert error.value.code == "non_human_readonly"


def test_nonhuman_expiry_and_account_tick_are_skipped(tmp_path):
    service = AgentService(
        {"store_path": str(tmp_path / "agent.sqlite"), "allow_mutations": True},
        collector=lambda: ([], [process(20, 2, True)], []),
        signaler=lambda *args: pytest.fail("must not signal nonhuman"),
    )
    service.accounts.is_human = lambda uid: uid == 1000
    task = service.call("snapshot")["tasks"][0]
    task = service.call(
        "apply_task_policy",
        {
            "task_id": task["id"],
            "revision": task["revision"],
            "policy": {
                "expires_at": "2020-01-01T00:00:00+00:00",
                "deadline_action": "terminate",
                "cleanup_orphans": True,
            },
        },
    )
    service.call("heartbeat", {"policy_versions": {task["id"]: task["revision"]}})
    service.accounts.is_human = lambda uid: False
    service.accounts.list = lambda state: [dict(id="1000", uid=1000, managed=True, protected=False)]
    service.accounts.apply_login = lambda *args: pytest.fail("must not apply nonhuman account policy")
    with service.database() as db:
        state = service.load(db)
        state["accounts"]["1000"] = dict(disabled=True, agent_restricted=False)
        service.save(db, state)
    service.tick()
    with service.database() as db:
        assert not service.load(db)["jobs"]


def test_task_original_name_survives_alias_refresh_and_finish():
    tasks = group_processes([process(10, 1, True)], [])
    assert tasks[0]["original_name"] == "python train.py"
    tasks[0]["name"] = "模型A训练"
    refreshed = group_processes([process(10, 1, True)], tasks)
    assert refreshed[0]["name"] == "模型A训练"
    assert refreshed[0]["original_name"] == "python train.py"
    assert group_processes([], refreshed)[0]["original_name"] == "python train.py"
    del tasks[0]["original_name"]
    assert group_processes([], tasks)[0]["original_name"] == "python train.py"
    tasks[0]["members"] = []
    assert group_processes([], tasks)[0]["original_name"] is None
