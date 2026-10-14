import pytest

from gpupm.agent.demo import DemoAgent
from gpupm.errors import DomainError


def test_group_inventory_defaults_to_permission_groups(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    assert agent.call("list_system_groups") == []
    groups = {g["name"]: g for g in agent.call("list_system_groups", {"scope": "all"})}
    assert groups["alice"]["kind"] == "private"
    assert groups["alice"]["primary_users"] == ["alice"]
    assert not groups["alice"]["assignable"]
    assert groups["human"]["kind"] == "platform"


def test_adopt_existing_ordinary_group_and_reject_private(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    state["system_groups"].append(
        dict(id="project", name="project", gid=3000, members=[], managed=False, protected=False, revision=1)
    )
    p = dict(id="project", revision=1, action="update", changes={"managed": True})
    preview = agent.dispatch(state, "preview_group_change", p)
    result = agent.dispatch(state, "execute_group_change", dict(p, token=preview["token"]))
    assert result["managed"] and result["assignable"]
    for ident, changes in [
        ("alice", {"managed": True}),
        ("human", {"managed": True}),
        ("project", {"managed": False}),
        ("project", {"managed": True, "members": []}),
    ]:
        with pytest.raises(DomainError):
            agent.dispatch(state, "preview_group_change", dict(p, id=ident, changes=changes))


def test_group_delete_preview_rejects_share_and_primary_refs(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    state["system_groups"].append(
        dict(id="project", name="project", gid=3000, members=[], managed=True, protected=False, revision=1)
    )
    state["shares"].append(dict(id="share-1", reader_group="project", writer_group="alice"))
    with pytest.raises(DomainError, match="references"):
        agent.dispatch(state, "preview_group_change", dict(id="project", revision=1, action="delete"))


def test_new_account_cannot_grant_private_group(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    with pytest.raises(DomainError):
        agent.call(
            "execute_account_change",
            {
                "action": "create",
                "changes": {"username": "charlie", "password": "valid-password-123", "groups": ["alice"]},
            },
        )


def test_native_adoption_changes_metadata_without_commands(tmp_path):
    from gpupm.agent.host import AgentService
    from gpupm.agent.groups import describe_group

    service = AgentService(dict(store_path=str(tmp_path / "native.db")), collector=lambda: ([], [], []))
    state = {"groups": {}, "accounts": {}, "shares": [], "previews": {}, "events": []}
    calls = []

    def inventory(state):
        meta = state["groups"].get("project", {})
        return [
            describe_group(
                dict(
                    id="project",
                    name="project",
                    gid=3000,
                    members=[],
                    protected=False,
                    managed=bool(meta),
                    revision=meta.get("revision", 1),
                ),
                [],
                state["shares"],
            )
        ]

    service.accounts.groups = inventory
    service.accounts.assert_human_group = lambda name: None
    service.accounts.run = lambda argv: calls.append(argv)
    p = dict(id="project", revision=1, action="update", changes={"managed": True})
    preview = service.group_change(state, "preview_group_change", p)
    result = service.group_change(state, "execute_group_change", dict(p, token=preview["token"]))
    assert result["assignable"]
    assert state["groups"]["project"] == {"gid": 3000, "revision": 2}
    assert calls == []


def test_group_preview_is_bound_to_primary_and_share_refs(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    agent.dispatch(state, "execute_group_change", dict(action="create", changes={"name": "project"}))
    p = dict(id="project", revision=1, action="update", changes={"members": []})
    preview = agent.dispatch(state, "preview_group_change", p)
    state["shares"].append(dict(id="new-share", reader_group="project", writer_group="alice"))
    with pytest.raises(DomainError, match="scope"):
        agent.dispatch(state, "execute_group_change", dict(p, token=preview["token"]))


def test_existing_unmanaged_membership_and_share_notes_are_preserved(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    account = state["accounts"][0]
    account["groups"].append("external")
    state["system_groups"].append(
        dict(
            id="external",
            name="external",
            gid=3000,
            members=["alice"],
            managed=False,
            protected=False,
            revision=1,
        )
    )
    p = dict(id=account["id"], revision=1, action="update", changes={"groups": []})
    preview = agent.dispatch(state, "preview_account_change", p)
    account = agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))
    assert {"external", "human", "alice"} <= set(account["groups"])
    share = dict(
        id="legacy-share", name="legacy", reader_group="alice", writer_group="bob", notes="", revision=1
    )
    state["shares"].append(share)
    p = dict(id=share["id"], revision=1, action="update", changes={"notes": "preserve ACL"})
    preview = agent.dispatch(state, "preview_share_change", p)
    result = agent.dispatch(state, "execute_share_change", dict(p, token=preview["token"]))
    assert result["reader_group"] == "alice" and result["notes"] == "preserve ACL"


def test_native_gid_reuse_and_nonhuman_members_are_not_adoptable(monkeypatch):
    import types
    from gpupm.agent.accounts import Accounts
    from gpupm.agent import accounts as module

    monkeypatch.setattr(
        module.grp,
        "getgrall",
        lambda: [types.SimpleNamespace(gr_name="staff", gr_gid=3000, gr_mem=["daemon"])],
    )
    monkeypatch.setattr(
        module.pwd,
        "getpwall",
        lambda: [types.SimpleNamespace(pw_name="daemon", pw_gid=3000, pw_uid=500, pw_dir="/daemon")],
    )
    accounts = Accounts({})
    accounts.is_human = lambda uid: False
    group = accounts.groups(
        {"groups": {"staff": {"gid": 2000, "revision": 1}}, "accounts": {}, "shares": []}
    )[0]
    assert group["identity_conflict"]
    assert not group["can_adopt"] and not group["assignable"]
    group = accounts.groups({"groups": {}, "accounts": {}, "shares": []})[0]
    assert group["primary_users"] == ["daemon"]
    assert not group["can_adopt"]


def test_group_delete_rejects_ordinary_primary_reference(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    group = agent.dispatch(state, "execute_group_change", dict(action="create", changes={"name": "project"}))
    state["accounts"][0]["gid"] = group["gid"]
    state["accounts"][0]["primary_group"] = "project"
    inventory = {g["name"]: g for g in agent.dispatch(state, "list_system_groups", {"scope": "all"})}
    assert inventory["project"]["kind"] == "permission"
    assert inventory["project"]["primary_users"] == ["alice"]
    with pytest.raises(DomainError, match="references"):
        agent.dispatch(state, "preview_group_change", dict(id="project", revision=1, action="delete"))


def test_current_private_primary_remains_selectable(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    account = agent.call("list_accounts")[0]
    p = dict(
        id=account["id"],
        revision=account["revision"],
        action="update",
        changes={"primary_group": account["primary_group"]},
    )
    preview = agent.call("preview_account_change", p)
    updated = agent.call("execute_account_change", dict(p, token=preview["token"]))
    assert updated["gid"] == account["gid"]


def test_groups_with_protected_human_members_are_readonly(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    state["accounts"][0]["protected"] = True
    state["system_groups"].append(
        dict(
            id="project",
            name="project",
            gid=3000,
            members=["alice"],
            managed=False,
            protected=False,
            revision=1,
        )
    )
    inventory = {g["name"]: g for g in agent.dispatch(state, "list_system_groups", {"scope": "all"})}
    assert not inventory["project"]["can_adopt"]
    with pytest.raises(DomainError):
        agent.dispatch(
            state,
            "preview_group_change",
            dict(id="project", revision=1, action="update", changes={"managed": True}),
        )


def test_group_rename_preserves_native_primary_name_in_demo(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    group = agent.dispatch(state, "execute_group_change", dict(action="create", changes={"name": "project"}))
    state["accounts"][0].update(gid=group["gid"], primary_group="project")
    p = dict(id="project", revision=1, action="update", changes={"name": "research"})
    preview = agent.dispatch(state, "preview_group_change", p)
    group = agent.dispatch(state, "execute_group_change", dict(p, token=preview["token"]))
    assert group["id"] == "research"
    assert state["accounts"][0]["primary_group"] == "research"


def test_adoption_preserves_unmanaged_human_members_and_stays_readonly(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    state["accounts"][0]["managed"] = False
    state["system_groups"].append(
        dict(
            id="project",
            name="project",
            gid=3000,
            members=["alice"],
            managed=False,
            protected=False,
            revision=1,
        )
    )
    p = dict(id="project", revision=1, action="update", changes={"managed": True})
    preview = agent.dispatch(state, "preview_group_change", p)
    group = agent.dispatch(state, "execute_group_change", dict(p, token=preview["token"]))
    assert group["managed"] and group["members"] == ["alice"]
    assert not group["assignable"]
    with pytest.raises(DomainError):
        agent.dispatch(
            state,
            "preview_group_change",
            dict(id="project", revision=2, action="update", changes={"members": []}),
        )


def test_account_grant_updates_group_members_and_blocks_deletion(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    agent.dispatch(state, "execute_group_change", dict(action="create", changes={"name": "project"}))
    account = state["accounts"][0]
    p = dict(id=account["id"], revision=1, action="update", changes={"groups": ["project"]})
    preview = agent.dispatch(state, "preview_account_change", p)
    agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))
    group = next(g for g in state["system_groups"] if g["name"] == "project")
    assert group["members"] == ["alice"]
    with pytest.raises(DomainError):
        agent.dispatch(state, "preview_group_change", dict(id="project", revision=1, action="delete"))


@pytest.mark.parametrize("changes", [{"name": "external"}, {"members": ["alice"]}])
def test_delete_group_refuses_embedded_changes(tmp_path, changes):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    agent.dispatch(state, "execute_group_change", dict(action="create", changes={"name": "project"}))
    with pytest.raises(DomainError, match="delete"):
        agent.dispatch(
            state, "preview_group_change", dict(id="project", revision=1, action="delete", changes=changes)
        )


def test_demo_creation_and_group_updates_sync_memberships(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    agent.dispatch(
        state,
        "execute_group_change",
        dict(action="create", changes={"name": "project", "members": ["alice"]}),
    )
    assert "project" in state["accounts"][0]["groups"]
    created = agent.dispatch(
        state,
        "execute_account_change",
        dict(
            action="create",
            changes={"username": "carol", "password": "valid-password-123", "groups": ["project"]},
        ),
    )
    assert next(g for g in state["system_groups"] if g["name"] == "carol")["members"] == []
    assert next(g for g in state["system_groups"] if g["name"] == "project")["members"] == ["alice", "carol"]
    p = dict(id="project", revision=1, action="update", changes={"members": [created["username"]]})
    preview = agent.dispatch(state, "preview_group_change", p)
    agent.dispatch(state, "execute_group_change", dict(p, token=preview["token"]))
    assert "project" not in state["accounts"][0]["groups"]


@pytest.mark.parametrize("method", ["preview_group_change", "execute_group_change"])
@pytest.mark.parametrize("changes", [{"name": "external"}, {"members": ["alice"]}])
def test_native_delete_rpc_rejects_changes_before_commands(tmp_path, method, changes):
    from gpupm.agent.host import AgentService
    from gpupm.agent.groups import describe_group

    service = AgentService(dict(store_path=str(tmp_path / "native.db")), collector=lambda: ([], [], []))
    state = {
        "groups": {"project": {"gid": 3000, "revision": 1}},
        "accounts": {},
        "shares": [],
        "previews": {},
        "events": [],
    }
    group = describe_group(
        dict(id="project", name="project", gid=3000, members=[], protected=False, managed=True, revision=1),
        [],
        [],
    )
    service.accounts.groups = lambda state: [group]
    calls = []
    service.accounts.run = lambda argv: calls.append(argv)
    with pytest.raises(DomainError, match="delete"):
        service.group_change(state, method, dict(id="project", revision=1, action="delete", changes=changes))
    assert calls == []


def test_native_legacy_private_marker_is_saved_before_primary_change(monkeypatch):
    from gpupm.agent.accounts import Accounts

    account = dict(
        id="1001",
        uid=1001,
        gid=1001,
        username="alice",
        primary_group="alice",
        groups=["alice", "human"],
        home="/home/alice",
        data_dir="/data/alice",
        managed=True,
        protected=False,
        revision=1,
    )
    meta = dict(managed=True, revision=1, baseline={}, disabled=False, deleted_at=None)
    accounts = Accounts({}, lambda argv, **kw: "")
    accounts.writable = lambda *args, **kw: account
    accounts.find = lambda *args: account
    accounts.validate_permission_groups = lambda *args: None
    accounts.capture_external_policy = lambda *args: None
    accounts.apply_login = lambda *args: None
    accounts.execute({"accounts": {"1001": meta}}, "update", "1001", {"primary_group": "project"})
    assert meta["private_group"] == "alice"


def test_demo_primary_switch_preserves_private_classification_and_memberships(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    agent.dispatch(state, "execute_group_change", dict(action="create", changes={"name": "project"}))
    account = state["accounts"][0]
    p = dict(id=account["id"], revision=1, action="update", changes={"primary_group": "project"})
    preview = agent.dispatch(state, "preview_account_change", p)
    updated = agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))
    assert "project" in updated["groups"]
    assert "alice" not in updated["groups"]
    groups = {g["name"]: g for g in agent.dispatch(state, "list_system_groups", {"scope": "all"})}
    assert groups["alice"]["kind"] == "private" and not groups["alice"]["assignable"]
    assert groups["project"]["primary_users"] == ["alice"]
    assert groups["project"]["members"] == []


@pytest.mark.parametrize("reader", ["alice", "external"])
def test_share_binding_change_rejects_unchanged_legacy_reader(tmp_path, reader):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    agent.dispatch(state, "execute_group_change", dict(action="create", changes={"name": "newwriter"}))
    state["system_groups"].append(
        dict(id="external", name="external", gid=3000, members=[], managed=False, protected=False, revision=1)
    )
    state["shares"].append(
        dict(id="legacy", name="legacy", reader_group=reader, writer_group="bob", notes="", revision=1)
    )
    p = dict(id="legacy", revision=1, action="update", changes={"writer_group": "newwriter"})
    with pytest.raises(DomainError):
        agent.dispatch(state, "preview_share_change", p)
    p["changes"] = {"notes": "preserve"}
    preview = agent.dispatch(state, "preview_share_change", p)
    assert (
        agent.dispatch(state, "execute_share_change", dict(p, token=preview["token"]))["notes"] == "preserve"
    )


def test_own_private_primary_can_be_restored_but_not_after_gid_drift(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    agent.dispatch(state, "execute_group_change", dict(action="create", changes={"name": "project"}))
    account = state["accounts"][0]
    for primary in ["project", "alice"]:
        p = dict(
            id=account["id"],
            revision=account["revision"],
            action="update",
            changes={"primary_group": primary},
        )
        preview = agent.dispatch(state, "preview_account_change", p)
        account = agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))
    assert account["primary_group"] == "alice" and account["private_gid"] == 1001
    p = dict(
        id=account["id"], revision=account["revision"], action="update", changes={"primary_group": "project"}
    )
    preview = agent.dispatch(state, "preview_account_change", p)
    account = agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))
    next(g for g in state["system_groups"] if g["name"] == "alice")["gid"] = 3999
    for primary in ["alice", "bob"]:
        p = dict(
            id=account["id"],
            revision=account["revision"],
            action="update",
            changes={"primary_group": primary},
        )
        preview = agent.dispatch(state, "preview_account_change", p)
        with pytest.raises(DomainError):
            agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))


def test_native_account_adoption_records_actual_private_identity(tmp_path, monkeypatch):
    import os
    from gpupm.agent import accounts as module

    private_dir = tmp_path / "private"
    private_dir.mkdir(mode=0o700)
    account = dict(
        id="1001",
        uid=os.getuid(),
        gid=1001,
        username="alice",
        primary_group="alice",
        groups=["alice", "human"],
        home="/home/alice",
        data_dir="/data/alice",
        managed=False,
        protected=False,
        revision=1,
    )
    accounts = module.Accounts({})
    accounts.writable = lambda *args, **kw: account
    accounts.find = lambda *args: account
    accounts.shadow_baseline = lambda *args: {}
    accounts.capture_external_policy = lambda *args: None
    accounts.apply_login = lambda *args: None
    monkeypatch.setattr(module, "open_directory", lambda *args: os.open(private_dir, os.O_RDONLY))
    state = {"accounts": {}}
    accounts.execute(state, "update", "1001", {"managed": True})
    assert state["accounts"]["1001"]["managed"]
    assert state["accounts"]["1001"]["private_group"] == "alice"
    assert state["accounts"]["1001"]["private_gid"] == 1001


def test_native_share_binding_change_validates_both_groups(tmp_path):
    from gpupm.agent.host import AgentService
    from gpupm.agent.storage import Storage

    service = AgentService(dict(store_path=str(tmp_path / "native.db")), collector=lambda: ([], [], []))
    share = dict(id="legacy", name="legacy", reader_group="alice", writer_group="bob", revision=1)
    state = {"shares": [share]}
    calls = []

    def validate(state, names):
        calls.append(names)
        raise DomainError("protected_group", "legacy reader is readonly", 403)

    service.accounts.validate_permission_groups = validate
    with pytest.raises(DomainError):
        Storage(service).dispatch(
            state,
            "preview_share_change",
            dict(id="legacy", revision=1, changes={"writer_group": "newwriter"}),
        )
    assert calls == [["alice", "newwriter"]]


def test_demo_account_adoption_makes_existing_permission_membership_assignable(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    account = state["accounts"][0]
    account["managed"] = False
    state["system_groups"].append(
        dict(
            id="project",
            name="project",
            gid=3000,
            members=["alice"],
            managed=True,
            protected=False,
            revision=1,
        )
    )
    p = dict(id=account["id"], revision=1, action="update", changes={"managed": True})
    preview = agent.dispatch(state, "preview_account_change", p)
    adopted = agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))
    assert adopted["managed"] and adopted["private_group"] == "alice" and adopted["private_gid"] == 1001
    assert next(g for g in agent.dispatch(state, "list_system_groups", {}) if g["name"] == "project")[
        "assignable"
    ]


def test_native_own_private_restore_requires_bound_gid(monkeypatch):
    import types
    from gpupm.agent import accounts as module

    account = dict(
        id="1001",
        uid=1001,
        gid=3000,
        username="alice",
        primary_group="project",
        groups=["project", "human"],
        home="/home/alice",
        data_dir="/data/alice",
        managed=True,
        protected=False,
        revision=1,
    )
    meta = dict(
        managed=True,
        revision=1,
        baseline={},
        disabled=False,
        deleted_at=None,
        private_group="alice",
        private_gid=1001,
    )
    accounts = module.Accounts({}, lambda argv, **kw: "")
    accounts.writable = lambda *args, **kw: account
    accounts.find = lambda *args: account
    accounts.capture_external_policy = lambda *args: None
    accounts.apply_login = lambda *args: None

    def forbid(*args):
        raise DomainError("protected_group", "not assignable", 403)

    accounts.validate_permission_groups = forbid
    monkeypatch.setattr(
        module.grp, "getgrnam", lambda name: types.SimpleNamespace(gr_gid=1001, gr_name=name, gr_mem=[])
    )
    state = {"accounts": {"1001": meta}}
    accounts.execute(state, "update", "1001", {"primary_group": "alice"})
    monkeypatch.setattr(
        module.grp, "getgrnam", lambda name: types.SimpleNamespace(gr_gid=3999, gr_name=name, gr_mem=[])
    )
    with pytest.raises(DomainError, match="GID"):
        accounts.execute(state, "update", "1001", {"primary_group": "alice"})
    with pytest.raises(DomainError):
        accounts.execute(state, "update", "1001", {"primary_group": "bob"})


def test_demo_explicit_old_primary_membership_is_retained_during_switch(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    agent.dispatch(state, "execute_group_change", dict(action="create", changes={"name": "project"}))
    account = state["accounts"][0]
    p = dict(
        id=account["id"],
        revision=1,
        action="update",
        changes={"primary_group": "project", "groups": ["alice"]},
    )
    preview = agent.dispatch(state, "preview_account_change", p)
    updated = agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))
    assert {"alice", "project", "human"} <= set(updated["groups"])
    assert next(g for g in state["system_groups"] if g["name"] == "alice")["members"] == ["alice"]


@pytest.mark.parametrize("restriction", ["protected", "unmanaged", "nonhuman"])
def test_demo_own_private_restore_rejects_outside_scope_members(tmp_path, restriction):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    agent.dispatch(state, "execute_group_change", dict(action="create", changes={"name": "project"}))
    account = state["accounts"][0]
    p = dict(id=account["id"], revision=1, action="update", changes={"primary_group": "project"})
    preview = agent.dispatch(state, "preview_account_change", p)
    account = agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))
    next(g for g in state["system_groups"] if g["name"] == "alice")["members"] = ["bob"]
    if restriction == "nonhuman":
        next(g for g in state["system_groups"] if g["name"] == "human")["members"].remove("bob")
    else:
        state["accounts"][1]["protected" if restriction == "protected" else "managed"] = (
            restriction == "protected"
        )
    p = dict(
        id=account["id"], revision=account["revision"], action="update", changes={"primary_group": "alice"}
    )
    preview = agent.dispatch(state, "preview_account_change", p)
    with pytest.raises(DomainError):
        agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))


def test_native_own_private_restore_checks_existing_member_scope(monkeypatch):
    import types
    from gpupm.agent import accounts as module

    account = dict(id="1001", uid=1001, gid=3000, username="alice", primary_group="project", revision=1)
    meta = dict(managed=True, revision=1, private_group="alice", private_gid=1001)
    commands = []
    accounts = module.Accounts({}, lambda argv, **kw: commands.append(argv))
    accounts.find = lambda *args: account

    def writable(state, ident, adopt=False):
        if ident == "1002":
            raise DomainError("account_unmanaged", "existing member requires adoption", 403)
        return account

    accounts.writable = writable
    monkeypatch.setattr(
        module.grp, "getgrnam", lambda name: types.SimpleNamespace(gr_gid=1001, gr_name=name, gr_mem=["bob"])
    )
    monkeypatch.setattr(module.pwd, "getpwall", lambda: [])
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: types.SimpleNamespace(pw_uid=1002))
    with pytest.raises(DomainError, match="adoption"):
        accounts.execute({"accounts": {"1001": meta}}, "update", "1001", {"primary_group": "alice"})
    assert commands == []


@pytest.mark.parametrize(
    "changes", [{"notes": "readonly"}, {"groups": ["project"]}, {"primary_group": "project"}]
)
def test_demo_unmanaged_accounts_require_explicit_adoption(tmp_path, changes):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    agent.dispatch(state, "execute_group_change", dict(action="create", changes={"name": "project"}))
    account = state["accounts"][0]
    p = dict(id=account["id"], revision=1, action="update", changes=changes)
    preview = agent.dispatch(state, "preview_account_change", p)
    account["managed"] = False
    with pytest.raises(DomainError) as error:
        agent.dispatch(state, "preview_account_change", p)
    assert error.value.code == "account_unmanaged"
    with pytest.raises(DomainError) as error:
        agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))
    assert error.value.code == "account_unmanaged"
    p["changes"] = dict(changes, managed=True)
    preview = agent.dispatch(state, "preview_account_change", p)
    assert agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))["managed"]


@pytest.mark.parametrize("name,gid", [("sudo", 3000), ("alice", 500)])
def test_demo_own_private_restore_rejects_sensitive_or_system_group(tmp_path, name, gid):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    project = agent.dispatch(
        state, "execute_group_change", dict(action="create", changes={"name": "project"})
    )
    account = state["accounts"][0]
    account.update(
        gid=project["gid"],
        primary_group="project",
        groups=["human", "project"],
        private_group=name,
        private_gid=gid,
    )
    state["system_groups"].append(
        dict(id=name + "-legacy", name=name, gid=gid, members=[], managed=False, protected=False, revision=1)
    )
    if name == "alice":
        state["system_groups"] = [g for g in state["system_groups"] if g["id"] != "alice"]
    p = dict(id=account["id"], revision=1, action="update", changes={"primary_group": name})
    preview = agent.dispatch(state, "preview_account_change", p)
    with pytest.raises(DomainError):
        agent.dispatch(state, "execute_account_change", dict(p, token=preview["token"]))
    assert account["primary_group"] == "project" and account["gid"] == project["gid"]


def test_legacy_demo_private_identity_is_backfilled_without_rebinding(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    account = state["accounts"][0]
    account.pop("private_group")
    account.pop("private_gid")
    original = {key: account[key] for key in ("groups", "revision", "notes", "managed")}
    listed = agent.dispatch(state, "list_accounts", {})[0]
    assert listed["private_group"] == "alice" and listed["private_gid"] == 1001
    assert {key: listed[key] for key in original} == original
    next(g for g in state["system_groups"] if g["name"] == "alice")["gid"] = 3999
    listed = agent.dispatch(state, "list_accounts", {})[0]
    assert listed["private_group"] == "alice" and listed["private_gid"] == 1001
