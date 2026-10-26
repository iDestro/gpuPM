import copy
import os
from types import SimpleNamespace

import pytest

from gpupm.agent.accounts import Accounts, restriction_active
from gpupm.errors import DomainError


def test_incomplete_creation_is_always_restricted():
    assert restriction_active({"creation": {"status": "incomplete"}})


def test_lifecycle_reports_independent_restrictions_and_unknown_legacy():
    from gpupm.agent.accounts import lifecycle_details

    result = lifecycle_details(
        {
            "disabled": True,
            "deleted_at": "2026-01-01T00:00:00+00:00",
            "expires_on": "2020-01-01",
            "disabled_reason": "investigation",
        }
    )
    assert result["disabled"] == {"active": True, "at": None, "reason": "investigation", "source": "platform"}
    assert result["deleted"]["active"] and result["deleted"]["reason"] is None
    assert result["expiry"]["active"] and result["expiry"]["at"] == "2020-01-01T00:00:00+00:00"


@pytest.fixture
def provisioning(tmp_path, monkeypatch):
    import gpupm.agent.accounts as module

    home, data = tmp_path / "home", tmp_path / "data"
    home.mkdir()
    data.mkdir()
    entries = {}
    native = dict(password="!", shell="/usr/sbin/nologin", expire="1", last_change="100", restricted=True)
    calls, saved = [], []
    fail = {"command": None}

    def lookup(name):
        if name not in entries:
            raise KeyError(name)
        return entries[name]

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "useradd":
            entries[argv[-1]] = SimpleNamespace(
                pw_uid=os.getuid(),
                pw_gid=os.getgid(),
                pw_name=argv[-1],
                pw_dir=str(home / argv[-1]),
                pw_shell="/usr/sbin/nologin",
                pw_gecos=argv[argv.index("--comment") + 1] if "--comment" in argv else "",
            )
        if argv[0] == fail["command"]:
            raise DomainError("injected_failure", "interrupted native operation", 503)
        if argv[0] == "chpasswd":
            native["password"] = "hash"
        if "--password" in argv:
            native["password"] = argv[argv.index("--password") + 1]
        if "--lock" in argv:
            native["password"] = "!" + native["password"].lstrip("!")
        if "--unlock" in argv:
            native["password"] = native["password"].removeprefix("!")
        if "--shell" in argv:
            native["shell"] = argv[argv.index("--shell") + 1]
        if "--expiredate" in argv:
            value = argv[argv.index("--expiredate") + 1]
            native["expire"] = "" if value == "-1" else value
        return ""

    monkeypatch.setattr(module.pwd, "getpwnam", lookup)
    monkeypatch.setattr(
        module,
        "rename_noreplace",
        lambda srcfd, src, dstfd, dst: os.rename(src, dst, src_dir_fd=srcfd, dst_dir_fd=dstfd),
    )
    monkeypatch.setattr(module, "quality_password", lambda *args: None)
    monkeypatch.setattr(module, "secure_directory", lambda path: module.Path(path))
    account = Accounts({"home_base": str(home), "data_base": str(data), "allow_mutations": True}, run)
    account.local_entries = lambda: list(entries.values())
    account.observe_identities = lambda *args: None
    account.ensure_human_group = lambda: None
    account.groups = lambda state: []
    account.shadow_baseline = lambda name: dict(native)
    account.find = lambda state, ident: dict(
        state["accounts"][ident],
        id=ident,
        uid=int(ident),
        gid=os.getgid(),
        username="newuser",
        home=str(home / "newuser"),
        data_dir=str(data / "newuser"),
    )
    account.checkpoint = lambda state: saved.append(copy.deepcopy(state))
    return account, {"accounts": {}, "groups": {}}, fail, saved, entries, native, calls


def test_partial_creation_survives_restart_and_requires_fresh_credentials(provisioning):
    accounts, state, fail, saved, entries, native, calls = provisioning
    fail["command"] = "chpasswd"
    with pytest.raises(DomainError, match="interrupted"):
        accounts.execute(state, "create", None, {"username": "newuser", "password": "Strong-password-123"})
    durable = saved[-1]
    ident = str(os.getuid())
    assert durable["accounts"][ident]["creation"]["status"] == "incomplete"
    assert "Strong-password-123" not in repr(durable)
    assert ":" not in durable["accounts"][ident]["creation"]["marker"]
    assert restriction_active(durable["accounts"][ident])
    with pytest.raises(DomainError) as error:
        accounts.execute(durable, "resume", ident, {})
    assert error.value.code == "credentials_required"
    fail["command"] = None
    result = accounts.execute(durable, "resume", ident, {"password": "Different-password-123"})
    assert result["creation"]["status"] == "complete"
    assert len([c for c in calls if c[0] == "useradd"]) == 1
    assert native["shell"] == "/bin/bash" and native["expire"] == ""


def test_recovery_refuses_replaced_native_identity(provisioning):
    accounts, state, fail, saved, entries, native, calls = provisioning
    fail["command"] = "chpasswd"
    with pytest.raises(DomainError):
        accounts.execute(state, "create", None, {"username": "newuser", "password": "Strong-password-123"})
    entries["newuser"].pw_gecos = "unrelated account"
    with pytest.raises(DomainError) as error:
        accounts.execute(saved[-1], "resume", str(os.getuid()), {"password": "Different-password-123"})
    assert error.value.code == "creation_identity_conflict"


def test_host_checkpoints_survive_process_abort(provisioning, tmp_path):
    from gpupm.agent.host import AgentService

    accounts, state, fail, saved, entries, native, calls = provisioning
    service = AgentService(
        dict(store_path=str(tmp_path / "state.sqlite"), allow_mutations=True), collector=lambda: ([], [], [])
    )
    service.accounts = accounts
    original = accounts.run

    def crash(argv, **kwargs):
        if argv[0] == "chpasswd":
            raise SystemExit("simulated process death")
        return original(argv, **kwargs)

    accounts.run = crash
    with pytest.raises(SystemExit):
        service.call(
            "execute_account_change",
            dict(action="create", changes={"username": "newuser", "password": "Strong-password-123"}),
        )
    restarted = AgentService(
        dict(store_path=str(tmp_path / "state.sqlite"), allow_mutations=True), collector=lambda: ([], [], [])
    )
    with restarted.database() as db:
        durable = restarted.load(db)
    assert durable["accounts"][str(os.getuid())]["creation"]["stage"] == "credentials"
    assert "Strong-password-123" not in repr(durable)


def test_adoption_preflight_reports_missing_data_without_creating_it(tmp_path):
    home, data = tmp_path / "home", tmp_path / "data"
    home.mkdir(mode=0o700)
    accounts = Accounts({"home_base": str(tmp_path), "data_base": str(data)})
    account = dict(username="alice", uid=os.getuid(), home=str(home))
    result = accounts.adoption_preflight(account)
    assert not result["ready"]
    assert any(c["code"] == "home_path" and not c["ok"] for c in result["checks"])
    assert any(c["code"] == "data_directory" and not c["ok"] for c in result["checks"])
    assert result["manual_steps"] and not data.exists()


def test_readonly_reasons_identify_actual_protection(monkeypatch):
    accounts = Accounts({"api_uid": 1200, "allow_mutations": False})
    accounts.is_human = lambda uid: True
    reasons = accounts.readonly_reasons(SimpleNamespace(pw_uid=1200, pw_name="apiuser"), {"managed": True})
    assert reasons == ["api_account", "mutations_disabled"]


def test_resume_refuses_changed_directory_inode(provisioning):
    from pathlib import Path

    accounts, state, fail, saved, entries, native, calls = provisioning
    fail["command"] = "chpasswd"
    with pytest.raises(DomainError):
        accounts.execute(state, "create", None, {"username": "newuser", "password": "Strong-password-123"})
    home = Path(entries["newuser"].pw_dir)
    home.rename(home.with_name("retained"))
    home.mkdir(mode=0o700)
    with pytest.raises(DomainError) as error:
        accounts.execute(saved[-1], "resume", str(os.getuid()), {"password": "Different-password-123"})
    assert error.value.code == "creation_path_conflict"


def test_demo_health_lifecycle_and_resume_contract(tmp_path):
    from gpupm.agent.demo import DemoAgent

    demo = DemoAgent(tmp_path / "demo.sqlite")
    assert demo.call("health")["mutations"] is True
    account = next(a for a in demo.call("list_accounts") if a["managed"] and not a["protected"])
    preview = demo.call(
        "preview_account_change", dict(id=account["id"], revision=account["revision"], action="disable")
    )
    disabled = demo.call(
        "execute_account_change",
        dict(
            id=account["id"],
            revision=account["revision"],
            action="disable",
            token=preview["token"],
            reason="investigation",
        ),
    )
    assert disabled["lifecycle"]["disabled"]["reason"] == "investigation"
    assert disabled["lifecycle"]["disabled"]["at"]
    with pytest.raises(DomainError) as error:
        demo.call(
            "preview_account_change", dict(id=disabled["id"], revision=disabled["revision"], action="resume")
        )
    assert error.value.code == "creation_not_pending"


def test_health_exposes_authoritative_roots_and_fail_closed_readiness(tmp_path):
    from gpupm.agent.host import AgentService

    service = AgentService(
        dict(
            store_path=str(tmp_path / "state.sqlite"),
            home_base=str(tmp_path / "missing-home"),
            data_base=str(tmp_path / "missing-data"),
            share_base=str(tmp_path / "missing-shares"),
        ),
        collector=lambda: ([], [], []),
    )
    health = service.call("health")
    assert health["roots"]["home_base"] == str(tmp_path / "missing-home")
    assert health["root_readiness"]["ready"] is False
    assert health["root_readiness"]["error_code"] == "unsafe_path"


def test_restart_recovers_native_creation_before_uid_checkpoint(provisioning):
    accounts, state, fail, saved, entries, native, calls = provisioning
    original = accounts.run

    def crash_after_useradd(argv, **kwargs):
        result = original(argv, **kwargs)
        if argv[0] == "useradd":
            raise SystemExit("process died after useradd")
        return result

    accounts.run = crash_after_useradd
    with pytest.raises(SystemExit):
        accounts.execute(state, "create", None, {"username": "newuser", "password": "Strong-password-123"})
    durable = saved[-1]
    assert not durable["accounts"]
    accounts.recover_creation_records(durable, list(entries.values()))
    ident = str(os.getuid())
    assert durable["accounts"][ident]["creation"]["status"] == "incomplete"
    accounts.run = original
    assert (
        accounts.execute(durable, "resume", ident, {"password": "Fresh-password-123"})["creation"]["status"]
        == "complete"
    )


def test_tick_never_releases_incomplete_creation(tmp_path):
    from gpupm.agent.host import AgentService

    service = AgentService(
        dict(store_path=str(tmp_path / "state.sqlite"), allow_mutations=True), collector=lambda: ([], [], [])
    )
    with service.database() as db:
        state = service.load(db)
        state["accounts"]["1001"] = dict(creation={"status": "incomplete"}, revision=1, agent_restricted=True)
        service.save(db, state)
    service.accounts.list = lambda state: [dict(id="1001", uid=1001, managed=True, protected=False)]
    service.accounts.is_human = lambda uid: True
    service.accounts.apply_login = lambda *args: pytest.fail(
        "incomplete creation must never be released by tick"
    )
    service.tick()


def test_resume_refuses_external_login_policy_drift(provisioning):
    accounts, state, fail, saved, entries, native, calls = provisioning
    fail["command"] = "chpasswd"
    with pytest.raises(DomainError):
        accounts.execute(state, "create", None, {"username": "newuser", "password": "Strong-password-123"})
    native["expire"] = "42"
    with pytest.raises(DomainError) as error:
        accounts.execute(saved[-1], "resume", str(os.getuid()), {"password": "Fresh-password-123"})
    assert error.value.code == "external_policy_changed"


def test_lifecycle_restore_preserves_independent_disable_and_expiry_reason(tmp_path):
    from gpupm.agent.demo import DemoAgent

    demo = DemoAgent(tmp_path / "demo.sqlite")
    account = next(a for a in demo.call("list_accounts") if a["managed"] and not a["protected"])
    for action, changes, reason in [
        ("disable", {}, "investigation"),
        ("update", {"expires_on": "2030-01-01"}, "lease ends"),
        ("delete", {}, "archival"),
        ("restore", {}, "restore access record"),
    ]:
        params = dict(id=account["id"], revision=account["revision"], action=action, changes=changes)
        preview = demo.call("preview_account_change", params)
        if action == "restore":
            assert preview["current"]["deleted_at"] and preview["proposed"]["deleted_at"] is None
            assert preview["proposed"]["disabled"] is True
        account = demo.call("execute_account_change", dict(params, token=preview["token"], reason=reason))
    assert account["lifecycle"]["disabled"]["reason"] == "investigation"
    assert account["lifecycle"]["disabled"]["active"]
    assert account["lifecycle"]["expiry"]["reason"] == "lease ends"
    assert not account["lifecycle"]["deleted"]["active"] and account["lifecycle"]["deleted"]["reason"] is None


def test_key_only_resume_never_forces_password_change(provisioning):
    accounts, state, fail, saved, entries, native, calls = provisioning
    fail["command"] = "chpasswd"
    with pytest.raises(DomainError):
        accounts.execute(state, "create", None, {"username": "newuser", "password": "Strong-password-123"})
    keys = ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"]
    result = accounts.execute(
        saved[-1], "resume", str(os.getuid()), {"public_keys": keys, "require_password_change": True}
    )
    assert not result["require_password_change"]
    assert not any(call[:3] == ["chage", "--lastday", "0"] for call in calls)


def test_adoption_requires_usable_exact_private_permissions(tmp_path):
    home, data = tmp_path / "home", tmp_path / "data"
    (home / "alice").mkdir(parents=True, mode=0o700)
    (data / "alice").mkdir(parents=True, mode=0o700)
    accounts = Accounts({"home_base": str(home), "data_base": str(data)})
    account = dict(username="alice", uid=os.getuid(), home=str(home / "alice"))
    assert accounts.adoption_preflight(account)["ready"]
    (data / "alice").chmod(0o600)
    try:
        assert not accounts.adoption_preflight(account)["ready"]
    finally:
        (data / "alice").chmod(0o700)


@pytest.mark.parametrize("boundary", ["directory", "files"])
def test_resume_after_directory_or_files_process_abort(provisioning, boundary):
    accounts, state, fail, saved, entries, native, calls = provisioning
    method = "provision_directory" if boundary == "directory" else "write_files"
    original = getattr(accounts, method)

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise SystemExit("simulated process death")

    setattr(accounts, method, crash)
    with pytest.raises(SystemExit):
        accounts.execute(state, "create", None, {"username": "newuser", "password": "Strong-password-123"})
    setattr(accounts, method, original)
    result = accounts.execute(saved[-1], "resume", str(os.getuid()), {"password": "Fresh-password-123"})
    assert result["creation"]["status"] == "complete"


@pytest.mark.parametrize(
    "failure", [DomainError("injected_login_failure", "login apply failed", 503), SystemExit("crash")]
)
def test_final_login_failure_only_follows_durable_complete_initialization(provisioning, failure):
    accounts, state, fail, saved, entries, native, calls = provisioning

    def crash(*args):
        raise failure

    accounts.apply_login = crash
    with pytest.raises(type(failure)):
        accounts.execute(state, "create", None, {"username": "newuser", "password": "Strong-password-123"})
    durable = saved[-1]["accounts"][str(os.getuid())]
    assert durable["creation"]["status"] == "complete"
    assert durable["creation"]["stage"] == "login_pending"
    assert durable["baseline"]["password"] == "hash"
    assert durable["agent_restricted"]
    assert not restriction_active(durable)
    assert "Strong-password-123" not in repr(saved)


def test_demo_preview_rejects_credentials_without_persisting_them(tmp_path):
    from gpupm.agent.demo import DemoAgent

    demo = DemoAgent(tmp_path / "demo.sqlite")
    account = next(a for a in demo.call("list_accounts") if not a["protected"] and a["managed"])
    with pytest.raises(DomainError):
        demo.call(
            "preview_account_change",
            dict(
                id=account["id"],
                revision=account["revision"],
                action="update",
                changes={"password": "Never-store-this-password"},
            ),
        )
    assert b"Never-store-this-password" not in (tmp_path / "demo.sqlite").read_bytes()


@pytest.mark.parametrize("when", ["before", "after"])
def test_final_creation_policy_reconciles_process_crash(provisioning, when):
    accounts, state, fail, saved, entries, native, calls = provisioning
    original = accounts.run

    def crash(argv, **kwargs):
        final = argv[0] == "usermod" and "--unlock" in argv and "--shell" in argv
        if final and when == "before":
            raise SystemExit("before final policy")
        value = original(argv, **kwargs)
        if final and when == "after":
            raise SystemExit("after final policy")
        return value

    accounts.run = crash
    with pytest.raises(SystemExit):
        accounts.execute(state, "create", None, {"username": "newuser", "password": "Strong-password-123"})
    durable = saved[-1]
    meta = durable["accounts"][str(os.getuid())]
    assert meta["creation"]["status"] == "complete" and meta["creation"]["stage"] == "login_pending"
    accounts.run = original
    accounts.apply_login(accounts.find(durable, str(os.getuid())), meta)
    assert meta["login_policy_status"] == "applied"
    assert not any("hash" in argument for argv in calls for argument in argv)
    assert meta["creation"]["stage"] == "initialized"
    assert native["password"] == "hash" and native["shell"] == "/bin/bash" and native["expire"] == ""


def test_creation_profile_survives_failure_without_joining_native_changes(provisioning):
    accounts, state, fail, saved, entries, native, calls = provisioning
    fail["command"] = "chpasswd"
    with pytest.raises(DomainError):
        accounts.execute(
            state,
            "create",
            None,
            {"username": "newuser", "password": "Strong-password-123"},
            profile={"group_id": 2, "priority": 17},
        )
    creation = saved[-1]["accounts"][str(os.getuid())]["creation"]
    assert creation["profile"] == {"group_id": 2, "priority": 17}
    assert "profile" not in creation["settings"]


def test_creation_rejects_invalid_business_profile_before_native_commands(provisioning):
    accounts, state, fail, saved, entries, native, calls = provisioning
    with pytest.raises(DomainError) as error:
        accounts.execute(
            state,
            "create",
            None,
            {"username": "newuser", "password": "Strong-password-123"},
            profile={"group_id": -1, "priority": True},
        )
    assert error.value.code == "invalid_profile" and not calls


def test_final_creation_policy_refuses_replaced_home(provisioning):
    from pathlib import Path

    accounts, state, fail, saved, entries, native, calls = provisioning
    original = accounts.apply_login
    accounts.apply_login = lambda *args: (_ for _ in ()).throw(SystemExit("before final policy"))
    with pytest.raises(SystemExit):
        accounts.execute(state, "create", None, {"username": "newuser", "password": "Strong-password-123"})
    durable = saved[-1]
    home = Path(entries["newuser"].pw_dir)
    home.rename(home.with_name("old-home"))
    home.mkdir(mode=0o700)
    accounts.apply_login = original
    with pytest.raises(DomainError) as error:
        accounts.apply_login(accounts.find(durable, str(os.getuid())), durable["accounts"][str(os.getuid())])
    assert error.value.code == "creation_path_conflict"
    assert native["shell"] == "/usr/sbin/nologin" and native["expire"] == "1"


@pytest.mark.parametrize(
    "profile,expected",
    [
        ({"group_id": 3, "priority": 17}, (3, 17)),
        ({"group_id": 999, "priority": 17}, (1, 17)),
        ({"group_id": 3, "priority": True}, (1, 50)),
    ],
)
def test_first_discovery_and_identity_reset_restore_only_valid_creation_profile(tmp_path, profile, expected):
    from gpupm.api.context import Context
    from gpupm.db.models import ManagementGroup, ManagedUser
    from gpupm.db.session import database

    _, sessions = database(tmp_path / "api.sqlite")
    with sessions.begin() as db:
        db.add(ManagementGroup(id=3, name="research", priority=70, notes=""))
    context = Context(sessions, None, None)
    account = dict(
        id="1001",
        uid=1001,
        username="newuser",
        lifecycle_id="new",
        is_human=True,
        creation={"profile": profile},
    )
    context.snapshot = lambda: {"accounts": [account], "tasks": []}
    user = context.users()[0]
    assert (user["group_id"], user["priority"]) == expected
    with sessions.begin() as db:
        row = db.get(ManagedUser, 1001)
        row.priority = 80
    assert context.users()[0]["priority"] == 80
    account["lifecycle_id"] = "replacement"
    user = context.users()[0]
    assert (user["group_id"], user["priority"]) == expected


def test_native_account_preview_binds_business_changes_before_execution(tmp_path):
    from gpupm.agent.host import AgentService

    service = AgentService(
        {"store_path": str(tmp_path / "agent.sqlite"), "allow_mutations": True},
        collector=lambda: ([], [], []),
    )
    account = dict(id="1001", uid=1001, username="alice", revision=1, managed=True, protected=False)
    service.accounts.writable = lambda *args, **kwargs: account
    service.accounts.find = lambda *args, **kwargs: account
    service.accounts.activity = lambda *args: {"processes": [], "sessions": [], "scheduled": []}
    called = []
    service.accounts.execute = lambda *args, **kwargs: called.append(args) or account
    params = dict(id="1001", revision=1, action="update", changes={}, business_changes={"priority": 17})
    preview = service.call("preview_account_change", params)
    with pytest.raises(DomainError) as error:
        service.call(
            "execute_account_change", dict(params, token=preview["token"], business_changes={"priority": 18})
        )
    assert error.value.code == "scope_changed" and not called
    result = service.call("execute_account_change", dict(params, token=preview["token"]))
    assert result["id"] == "1001" and len(called) == 1
