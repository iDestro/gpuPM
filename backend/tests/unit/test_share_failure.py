import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gpupm.agent.host import AgentService
from gpupm.agent.storage import Storage
from gpupm.errors import DomainError


@pytest.fixture
def share_env(tmp_path, monkeypatch):
    import gpupm.agent.storage as module

    root = tmp_path / "shared"
    root.mkdir()
    service = AgentService(
        dict(store_path=str(tmp_path / "agent.db"), share_base=str(root)), collector=lambda: ([], [], [])
    )
    service.accounts.validate_permission_groups = Mock()
    service.accounts.assert_devices = Mock()
    monkeypatch.setattr(module, "secure_directory", Path)
    monkeypatch.setattr(
        module.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=111 if name == "readers" else 222)
    )
    monkeypatch.setattr(module.os, "fchown", lambda *args: None)
    original = os.fstat

    def root_stat(fd):
        values = list(original(fd))
        values[4] = 0
        return os.stat_result(values)

    monkeypatch.setattr(module.os, "fstat", root_stat)
    service.accounts.run = Mock(
        return_value="user::rwx\ngroup::rwx\ngroup:111:r-x\ngroup:222:rwx\nmask::rwx\nother::---\ndefault:user::rwx\ndefault:group::rwx\ndefault:group:111:r-x\ndefault:group:222:rwx\ndefault:mask::rwx\ndefault:other::---\n"
    )
    state = dict(shares=[], previews={}, events=[])
    changes = dict(name="research", reader_group="readers", writer_group="writers")
    storage = Storage(service)

    def execute():
        preview = storage.dispatch(state, "preview_share_change", dict(changes=changes))
        return storage.dispatch(state, "execute_share_change", dict(changes=changes, token=preview["token"]))

    return root, service, state, execute


def test_failed_acl_create_can_retry_without_path_conflict(share_env):
    root, service, state, execute = share_env
    good = service.accounts.run.return_value
    service.accounts.run.side_effect = DomainError("command_failed", "injected ACL failure")
    with pytest.raises(DomainError):
        execute()
    assert not (root / "research").exists()
    assert state["shares"] == []
    service.accounts.run.side_effect = None
    service.accounts.run.return_value = good
    assert execute()["name"] == "research"


def test_failed_create_preserves_files_and_locks_partial_directory(share_env):
    root, service, state, execute = share_env

    def fail(*args):
        (root / "research" / "keep.txt").write_text("retain me")
        raise DomainError("command_failed", "injected failure")

    service.accounts.run.side_effect = fail
    with pytest.raises(DomainError):
        execute()
    assert (root / "research" / "keep.txt").read_text() == "retain me"
    assert (root / "research").stat().st_mode & 0o777 == 0o700
    assert state["shares"] == []


def test_acl_readback_must_verify_permissions_not_just_group_presence(share_env):
    root, service, state, execute = share_env
    service.accounts.run.return_value = "group:111:rwx\ngroup:222:rwx\nother::rwx\n"
    with pytest.raises(DomainError) as error:
        execute()
    assert error.value.code == "acl_readback_mismatch"
    assert not (root / "research").exists()


def test_existing_directory_is_never_removed_or_adopted(share_env):
    root, service, state, execute = share_env
    path = root / "research"
    path.mkdir()
    (path / "keep.txt").write_text("existing")
    with pytest.raises(DomainError) as error:
        execute()
    assert error.value.code == "path_conflict"
    assert (path / "keep.txt").read_text() == "existing"
    service.accounts.run.assert_not_called()


def test_failure_does_not_delete_replacement_directory(share_env):
    root, service, state, execute = share_env

    def swap(*args):
        (root / "research").rename(root / "original")
        (root / "research").mkdir()
        (root / "research" / "keep.txt").write_text("replacement")
        raise DomainError("command_failed", "injected replacement")

    service.accounts.run.side_effect = swap
    with pytest.raises(DomainError) as error:
        execute()
    assert error.value.code == "share_creation_incomplete"
    assert (root / "research" / "keep.txt").read_text() == "replacement"
    assert (root / "original").stat().st_mode & 0o777 == 0o700


def test_failed_edit_marks_permissions_unverified_without_claiming_success(share_env):
    root, service, state, execute = share_env
    created = execute()
    before = created["revision"]
    service.accounts.run.side_effect = DomainError("command_failed", "injected update failure")
    changes = dict(reader_group="newreaders")
    storage = Storage(service)
    preview = storage.dispatch(
        state, "preview_share_change", dict(id=created["id"], revision=before, changes=changes)
    )
    with pytest.raises(DomainError):
        storage.dispatch(
            state,
            "execute_share_change",
            dict(id=created["id"], revision=before, changes=changes, token=preview["token"]),
        )
    assert created["status"] == "access_recheck_required"
    assert created["revision"] == before + 1
    assert (root / "research").is_dir()


def test_native_os_error_is_reported_as_auditable_domain_failure(share_env):
    root, service, state, execute = share_env
    service.accounts.run.side_effect = OSError("injected filesystem error")
    with pytest.raises(DomainError) as error:
        execute()
    assert error.value.code == "host_command_failed"
    assert not (root / "research").exists()


@pytest.fixture
def member_env(share_env, monkeypatch):
    root, service, state, _ = share_env
    state["groups"] = {}
    native = {}
    accounts = [
        dict(
            id=str(uid),
            uid=uid,
            gid=uid,
            username=name,
            managed=True,
            is_human=True,
            protected=False,
            status="active",
            revision=1,
        )
        for uid, name in [(1001, "alice"), (1002, "bob")]
    ]
    service.accounts.list = lambda state: accounts
    service.accounts.groups = lambda state: [
        dict(name=name, gid=g.gr_gid, members=list(g.gr_mem), primary_users=[]) for name, g in native.items()
    ]

    def lookup(name):
        if name not in native:
            raise KeyError(name)
        return native[name]

    monkeypatch.setattr("gpupm.agent.share_members.grp.getgrnam", lookup)
    monkeypatch.setattr("gpupm.agent.share_members.pwd.getpwall", lambda: [])

    def run(argv):
        if argv[0] == "groupadd":
            native[argv[1]] = SimpleNamespace(gr_gid=2000 + len(native), gr_mem=[])
        elif argv[0] == "gpasswd":
            native[argv[-1]].gr_mem = argv[2].split(",") if argv[2] else []
        elif argv[0] == "getfacl":
            from gpupm.agent.share_members import MemberGroups

            names = MemberGroups(service, state, "research").names
            r, w = (native[names[f]].gr_gid for f in ("reader_group", "writer_group"))
            entries = [
                "user::rwx",
                "group::rwx",
                f"group:{r}:r-x",
                f"group:{w}:rwx",
                "mask::rwx",
                "other::---",
            ]
            return "\n".join(entries + ["default:" + e for e in entries])
        return ""

    service.accounts.run = Mock(side_effect=run)

    def change(changes, existing=None):
        p = dict(changes=changes)
        if existing:
            p.update(id=existing["id"], revision=existing["revision"])
        storage = Storage(service)
        preview = storage.dispatch(state, "preview_share_change", p)
        return storage.dispatch(state, "execute_share_change", dict(p, token=preview["token"]))

    return root, service, state, native, accounts, change


def test_native_members_create_downgrade_and_revoke_without_touching_other_groups(member_env):
    root, service, state, native, accounts, change = member_env
    share = change(dict(name="research", members=[dict(username="alice", permission="write")]))
    assert share["access_mode"] == "members"
    assert native[share["writer_group"]].gr_mem == ["alice"]
    change(
        dict(members=[dict(username="alice", permission="read"), dict(username="bob", permission="write")]),
        share,
    )
    assert native[share["writer_group"]].gr_mem == ["bob"]
    assert native[share["reader_group"]].gr_mem == ["alice"]
    change(dict(members=[]), share)
    assert all(not g.gr_mem for g in native.values())
    assert (root / "research").is_dir()


def test_native_member_preview_rejects_account_identity_drift(member_env):
    _, service, state, _, accounts, _ = member_env
    changes = dict(name="research", members=[dict(username="alice", permission="read")])
    storage = Storage(service)
    preview = storage.dispatch(state, "preview_share_change", dict(changes=changes))
    accounts[0]["uid"] = 9999
    with pytest.raises(DomainError) as error:
        storage.dispatch(state, "execute_share_change", dict(changes=changes, token=preview["token"]))
    assert error.value.code == "scope_changed"
    service.accounts.run.assert_not_called()


def test_native_member_failure_clears_grants_and_marks_recheck(member_env):
    _, service, state, native, _, change = member_env
    share = change(dict(name="research", members=[dict(username="alice", permission="write")]))
    original = service.accounts.run.side_effect

    def fail(argv):
        if argv[0] == "setfacl":
            raise DomainError("host_command_failed", "injected")
        return original(argv)

    service.accounts.run.side_effect = fail
    with pytest.raises(DomainError):
        change(dict(members=[dict(username="bob", permission="write")]), share)
    assert share["status"] == "access_recheck_required"
    assert all(not g.gr_mem for g in native.values())


def test_legacy_migration_keeps_old_groups_and_existing_files(member_env):
    root, service, state, native, _, change = member_env
    native["oldreaders"] = SimpleNamespace(gr_gid=3001, gr_mem=["bob"])
    native["oldwriters"] = SimpleNamespace(gr_gid=3002, gr_mem=["alice"])
    folder = root / "research"
    folder.mkdir()
    (folder / "keep").write_text("unchanged")
    share = dict(
        id="legacy",
        name="research",
        path=str(folder),
        revision=1,
        reader_group="oldreaders",
        writer_group="oldwriters",
        status="active",
    )
    state["shares"].append(share)
    change(dict(members=[dict(username="bob", permission="read")]), share)
    assert share["access_mode"] == "members"
    assert native["oldreaders"].gr_mem == ["bob"]
    assert native["oldwriters"].gr_mem == ["alice"]
    assert (folder / "keep").read_text() == "unchanged"


def test_legacy_path_grants_registered_directory_not_new_root_namesake(member_env):
    root, service, state, native, _, change = member_env
    native["oldreaders"] = SimpleNamespace(gr_gid=3001, gr_mem=[])
    native["oldwriters"] = SimpleNamespace(gr_gid=3002, gr_mem=[])
    legacy_parent = root.parent / "old_shared"
    legacy_parent.mkdir()
    legacy = legacy_parent / "research"
    legacy.mkdir()
    (legacy / "keep").write_text("original")
    namesake = root / "research"
    namesake.mkdir(mode=0o700)
    share = dict(
        id="legacy",
        name="research",
        path=str(legacy),
        revision=1,
        reader_group="oldreaders",
        writer_group="oldwriters",
        status="active",
    )
    state["shares"].append(share)
    storage = Storage(service)
    params = dict(id="legacy", revision=1, changes=dict(members=[dict(username="alice", permission="read")]))
    preview = storage.dispatch(state, "preview_share_change", params)
    assert preview["path"] == str(legacy)
    assert preview["proposed"]["path"] == str(legacy)
    storage.dispatch(state, "execute_share_change", dict(params, token=preview["token"]))
    assert legacy.stat().st_mode & 0o777 == 0o770
    assert namesake.stat().st_mode & 0o777 == 0o700
    assert (legacy / "keep").read_text() == "original"
    assert share["path"] == str(legacy)


def test_legacy_share_symlink_is_rejected_before_grants(member_env):
    root, service, state, _, _, _ = member_env
    actual = root.parent / "actual"
    actual.mkdir()
    (root / "research").symlink_to(actual, target_is_directory=True)
    share = dict(
        id="s",
        name="research",
        path=str(root / "research"),
        revision=1,
        reader_group="oldr",
        writer_group="oldw",
    )
    state["shares"].append(share)
    with pytest.raises(DomainError):
        Storage(service).dispatch(
            state, "preview_share_change", dict(id="s", revision=1, changes=dict(reader_group="newr"))
        )
    service.accounts.run.assert_not_called()


def test_registered_directory_replacement_after_preview_stops_before_grants(member_env):
    root, service, state, native, _, _ = member_env
    native["oldreaders"] = SimpleNamespace(gr_gid=3001, gr_mem=[])
    native["oldwriters"] = SimpleNamespace(gr_gid=3002, gr_mem=[])
    path = root / "research"
    path.mkdir()
    share = dict(
        id="s",
        name="research",
        path=str(path),
        revision=1,
        reader_group="oldreaders",
        writer_group="oldwriters",
    )
    state["shares"].append(share)
    storage = Storage(service)
    params = dict(id="s", revision=1, changes=dict(members=[]))
    preview = storage.dispatch(state, "preview_share_change", params)
    path.rename(root / "retained")
    path.mkdir()
    with pytest.raises(DomainError) as error:
        storage.dispatch(state, "execute_share_change", dict(params, token=preview["token"]))
    assert error.value.code == "scope_changed"
    service.accounts.run.assert_not_called()
