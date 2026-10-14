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
