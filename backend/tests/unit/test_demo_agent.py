import pytest

from gpupm.agent.demo import DemoAgent
from gpupm.errors import DomainError


def test_soft_delete_preserves_identity_and_independent_disable(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    account = agent.call("list_accounts")[0]
    original = {key: account[key] for key in ("id", "uid", "home", "data_dir")}
    for action in ["disable", "delete", "restore"]:
        token = agent.call(
            "preview_account_change", {"action": action, "id": account["id"], "revision": account["revision"]}
        )
        account = agent.call(
            "execute_account_change",
            {"action": action, "id": account["id"], "revision": account["revision"], "token": token["token"]},
        )
    assert account["status"] == "disabled"
    assert {key: account[key] for key in original} == original
    reopened = DemoAgent(tmp_path / "agent.db")
    assert reopened.call("list_accounts")[0]["disabled"] is True


def test_task_preview_rejects_changes_and_idempotent_execution(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    task = agent.call("snapshot")["tasks"][0]
    preview = agent.call("preview_termination", {"task_id": task["id"]})
    agent.call(
        "apply_task_policy",
        {"task_id": task["id"], "revision": task["revision"], "policy": {"notes": "edited"}},
    )
    with pytest.raises(DomainError, match="范围"):
        agent.call(
            "execute_termination",
            {"token": preview["token"], "reason": "test", "idempotency_key": "test-idempotent"},
        )
    preview = agent.call("preview_termination", {"task_id": task["id"]})
    params = {"token": preview["token"], "reason": "test", "idempotency_key": "test-idempotent"}
    first = agent.call("execute_termination", params)
    assert first == agent.call("execute_termination", params)
    assert first["source"] == "demo"


def test_sensitive_groups_and_unregistered_pid_rejected(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    with pytest.raises(DomainError):
        agent.call(
            "execute_account_change",
            {"action": "create", "changes": {"username": "evil", "groups": ["docker"]}},
        )
    task = agent.call("snapshot")["tasks"][0]
    with pytest.raises(DomainError):
        agent.call(
            "preview_termination",
            {"task_id": task["id"], "identity": {"boot_id": "demo", "pid": 1, "start_ticks": 0}},
        )


def test_demo_human_membership_is_computed_and_other_is_readonly(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    assert all(account["is_human"] for account in agent.dispatch(state, "list_accounts", {}))
    account = state["accounts"][0]
    account["groups"] = ["alice"]
    account["is_human"] = True
    human = next(g for g in state["system_groups"] if g["name"] == "human")
    human["members"].remove("alice")
    snapshot = agent.dispatch(state, "snapshot", {})
    task = snapshot["tasks"][0]
    assert not account["is_human"] and not task["is_human"]
    for method, params in [
        ("apply_task_policy", dict(task_id=task["id"], revision=1, policy={})),
        ("preview_termination", dict(task_id=task["id"])),
        ("preview_account_change", dict(id=account["id"], revision=1, action="disable")),
        ("preview_quota", dict(id=account["id"], policy={"filesystem_id": "demo-fs"})),
        ("preview_group_change", dict(id="human", action="delete")),
    ]:
        with pytest.raises(DomainError):
            agent.dispatch(state, method, params)


def test_existing_demo_migrates_human_membership_without_reset(tmp_path):
    import json
    import sqlite3

    path = tmp_path / "agent.db"
    agent = DemoAgent(path)
    state = agent.seed()
    state["system_groups"] = [g for g in state["system_groups"] if g["name"] != "human"]
    for account in state["accounts"]:
        account["groups"].remove("human")
    state["accounts"][0]["notes"] = "keep my edits"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    reopened = DemoAgent(path)
    accounts = reopened.call("list_accounts")
    assert all(a["is_human"] for a in accounts)
    assert accounts[0]["notes"] == "keep my edits"


def test_human_group_cannot_authorize_a_share(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    with pytest.raises(DomainError) as error:
        agent.call(
            "preview_share_change",
            {
                "action": "create",
                "changes": {"name": "unsafe", "reader_group": "human", "writer_group": "alice"},
            },
        )
    assert error.value.code == "protected_group"


def test_primary_human_membership_survives_primary_group_change(tmp_path):
    agent = DemoAgent(tmp_path / "agent.db")
    state = agent.seed()
    account = state["accounts"][0]
    human = next(g for g in state["system_groups"] if g["name"] == "human")
    account["gid"] = human["gid"]
    account["primary_group"] = "human"
    human["members"].remove(account["username"])
    changes = {"primary_group": "alice"}
    params = {"id": account["id"], "revision": account["revision"], "action": "update", "changes": changes}
    preview = agent.dispatch(state, "preview_account_change", params)
    agent.dispatch(state, "execute_account_change", dict(params, token=preview["token"]))
    assert agent.dispatch(state, "list_accounts", {})[0]["is_human"]
    assert account["gid"] != human["gid"]
    assert account["username"] in human["members"]
