import pytest
from fastapi.testclient import TestClient

from gpupm.api.main import create_app
from gpupm.config import Config


@pytest.fixture
def app(tmp_path):
    instance = create_app(
        Config(mode="demo", database=tmp_path / "app.db", agent_database=tmp_path / "agent.db")
    )
    instance.state.auth.create_admin("admin", "Strong-admin-pass-42")
    return instance


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def login(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "Strong-admin-pass-42"})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_requires_auth_and_csrf(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/tasks").status_code == 401
    headers = login(client)
    assert client.patch("/api/settings", json={"term_grace_seconds": 8}).status_code == 403
    assert client.patch("/api/settings", json={"term_grace_seconds": 8}, headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/tasks").status_code == 401


def test_groups_and_audit_are_persisted(client, app):
    headers = login(client)
    new = client.post(
        "/api/groups", json={"name": "research", "priority": 80, "notes": "团队"}, headers=headers
    )
    assert new.status_code == 200, new.text
    assert client.get("/api/groups").json()[-1]["priority"] == 80
    logs = client.get("/api/audit-logs").json()["items"]
    assert any(log["action"] == "group.create" and log["actor"] == "admin" for log in logs)
    second = create_app(app.state.config)
    with TestClient(second) as other:
        login(other)
        assert any(group["name"] == "research" for group in other.get("/api/groups").json())


def test_demo_task_policy_versions_protection_and_preview(client):
    headers = login(client)
    tasks = client.get("/api/tasks").json()
    assert tasks["source"] == "demo"
    task = tasks["items"][0]
    changed = client.patch(
        f"/api/tasks/{task['id']}", json={"revision": task["revision"], "protected": True}, headers=headers
    )
    assert changed.status_code == 200, changed.text
    stale = client.patch(
        f"/api/tasks/{task['id']}", json={"revision": task["revision"], "notes": "旧数据"}, headers=headers
    )
    assert stale.status_code == 409
    assert (
        client.post(f"/api/tasks/{task['id']}/termination-preview", json={}, headers=headers).status_code
        == 409
    )


def test_login_rate_limit(client):
    for _ in range(5):
        assert (
            client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
        )
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 429


def test_invalid_settings_and_untrusted_origin(client):
    headers = login(client)
    assert (
        client.patch("/api/settings", json={"scan_interval_seconds": 0}, headers=headers).status_code == 422
    )
    headers["Origin"] = "https://evil.example"
    assert client.patch("/api/settings", json={"term_grace_seconds": 8}, headers=headers).status_code == 403


def test_account_rows_include_existing_business_policy(client):
    headers = login(client)
    new_group = client.post("/api/groups", json={"name": "special", "priority": 88}, headers=headers).json()
    account = client.get("/api/system-users?state=all").json()[0]
    response = client.patch(
        f"/api/users/{account['uid']}", json={"group_id": new_group["id"], "priority": 73}, headers=headers
    )
    assert response.status_code == 200
    account = client.get(f"/api/system-users/{account['id']}").json()
    assert account["group_id"] == new_group["id"]
    assert account["priority"] == 73


def test_preview_edit_accepts_reason_and_leaves_business_fields(client):
    headers = login(client)
    account = client.get("/api/system-users?state=all").json()[0]
    preview = client.post(
        f"/api/system-users/{account['id']}/change-preview",
        json={"action": "update", "revision": account["revision"], "changes": {"notes": "reviewed"}},
        headers=headers,
    ).json()
    edited = client.patch(
        f"/api/system-users/{account['id']}",
        json={
            "notes": "reviewed",
            "revision": account["revision"],
            "token": preview["token"],
            "reason": "管理员修改备注",
        },
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["notes"] == "reviewed"


def test_share_create_requires_server_preview(client):
    headers = login(client)
    for name in ["readers", "writers"]:
        assert client.post("/api/system-groups", json={"name": name}, headers=headers).status_code == 200
    fields = {"name": "dataset", "reader_group": "readers", "writer_group": "writers", "notes": ""}
    assert client.post("/api/shares", json=fields, headers=headers).status_code == 409
    preview = client.post(
        "/api/shares/change-preview", json={"action": "create", "changes": fields}, headers=headers
    )
    assert preview.status_code == 200, preview.text
    created = client.post(
        "/api/shares",
        json={**fields, "token": preview.json()["token"], "reason": "共享数据集"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    assert created.json()["path"] == "/data/shared/dataset"


def test_quota_changes_require_specific_usage_preview(client):
    headers = login(client)
    account = client.get("/api/system-users?state=all").json()[0]
    fields = {
        "filesystem_id": "demo-fs",
        "soft_bytes": 1024,
        "hard_bytes": 2048,
        "soft_inodes": 0,
        "hard_inodes": 0,
        "grace_seconds": 60,
    }
    path = f"/api/system-users/{account['id']}/quotas"
    assert client.patch(path, json=fields, headers=headers).status_code == 409
    preview = client.post(path + "/preview", json=fields, headers=headers)
    assert preview.status_code == 200, preview.text
    assert "impact" in preview.json()
    changed = client.patch(
        path, json={**fields, "token": preview.json()["token"], "reason": "限制测试"}, headers=headers
    )
    assert changed.status_code == 200, changed.text
    assert client.get(path).json()[0]["hard_bytes"] == 2048


def test_password_never_echoed_or_stored_in_preview(client, app):
    import sqlite3

    headers = login(client)
    weak = "secret123"
    response = client.post(
        "/api/system-users", json={"username": "newuser", "password": weak}, headers=headers
    )
    assert response.status_code == 422
    assert weak not in response.text
    account = client.get("/api/system-users?state=all").json()[0]
    secret = "Only-in-memory-password-928"
    preview = client.post(
        f"/api/system-users/{account['id']}/change-preview",
        json={"action": "update", "revision": account["revision"], "changes": {"password": secret}},
        headers=headers,
    )
    assert preview.status_code == 422
    with sqlite3.connect(app.state.config.agent_database) as db:
        assert secret not in db.execute("SELECT data FROM state WHERE id=1").fetchone()[0]


def test_sensitive_account_edits_require_preview_and_validate_business_first(client):
    headers = login(client)
    account = client.get("/api/system-users?state=all").json()[0]
    path = f"/api/system-users/{account['id']}"
    assert (
        client.patch(
            path, json={"revision": account["revision"], "public_keys": []}, headers=headers
        ).status_code
        == 409
    )
    preview = client.post(
        path + "/change-preview",
        json={"action": "update", "revision": account["revision"], "changes": {"notes": "must not save"}},
        headers=headers,
    ).json()
    result = client.patch(
        path,
        json={
            "revision": account["revision"],
            "token": preview["token"],
            "notes": "must not save",
            "group_id": 99999,
        },
        headers=headers,
    )
    assert result.status_code == 404
    assert client.get(path).json()["notes"] != "must not save"


def test_online_rename_and_group_preview_scope_are_rejected(client):
    headers = login(client)
    account = client.get("/api/system-users?state=all").json()[0]
    path = f"/api/system-users/{account['id']}"
    preview = client.post(
        path + "/change-preview",
        json={"action": "update", "revision": account["revision"], "changes": {"username": "renamed"}},
        headers=headers,
    ).json()
    result = client.patch(
        path,
        json={"revision": account["revision"], "token": preview["token"], "username": "renamed"},
        headers=headers,
    )
    assert result.status_code == 409
    for name in ["preview_group", "alternate_group"]:
        assert client.post("/api/system-groups", json={"name": name}, headers=headers).status_code == 200
    path = "/api/system-groups/preview_group"
    preview = client.post(
        path + "/change-preview", json={"revision": 1, "changes": {"members": ["alice"]}}, headers=headers
    ).json()
    result = client.patch(
        path, json={"revision": 1, "token": preview["token"], "members": ["bob"]}, headers=headers
    )
    assert result.status_code == 409


def test_missing_memory_is_not_zero(client, app, monkeypatch):
    login(client)
    original = app.state.ctx.agent.call

    def agent_call(method, params=None):
        result = original(method, params)
        if method == "snapshot":
            result["tasks"][0]["members"][0]["gpu_memory"] = {"demo-gpu-0": None}
        return result

    monkeypatch.setattr(app.state.ctx.agent, "call", agent_call)
    app.state.ctx.invalidate()
    result = client.get("/api/tasks").json()
    task = next(t for t in result["items"] if t["id"] == "demo-task-1")
    assert task["memory_used"] is None


def test_imported_host_audit_keeps_execution_time(client, app, monkeypatch):
    login(client)
    original = app.state.ctx.agent.call

    def agent_call(method, params=None):
        if method == "audit_since":
            return {
                "items": [
                    {
                        "id": "historical-event",
                        "time": "2026-10-01T01:02:03+00:00",
                        "actor": "system",
                        "action": "historical.test",
                        "target": "sample",
                        "before": None,
                        "after": None,
                        "result": "succeeded",
                        "reason": "",
                    }
                ],
                "cursor": "historical-event",
                "has_more": False,
            }
        return original(method, params)

    monkeypatch.setattr(app.state.ctx.agent, "call", agent_call)
    app.state.ctx.synchronize_events()
    logs = client.get("/api/audit-logs?action=historical.test").json()["items"]
    assert logs[0]["time"] == "2026-10-01T01:02:03+00:00"


def test_key_only_account_creation_and_primary_group(client):
    headers = login(client)
    created = client.post(
        "/api/system-users",
        json={
            "username": "carol",
            "public_keys": ["ssh-ed25519 AAAAfixture"],
            "require_password_change": False,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    account = created.json()
    changes = {"primary_group": "bob"}
    preview = client.post(
        f"/api/system-users/{account['id']}/change-preview",
        json={"action": "update", "revision": account["revision"], "changes": changes},
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    changed = client.patch(
        f"/api/system-users/{account['id']}",
        json={"revision": account["revision"], "token": preview.json()["token"], **changes},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["primary_group"] == "bob"
    empty = client.post("/api/system-users", json={"username": "dave"}, headers=headers)
    assert empty.status_code == 422


def test_quota_edit_does_not_reset_grace_when_omitted(client, app):
    headers = login(client)
    account = client.get("/api/system-users?state=all").json()[0]
    policy = {"filesystem_id": "demo-fs", "soft_bytes": 1024, "hard_bytes": 4096}
    preview = client.post(f"/api/system-users/{account['id']}/quotas/preview", json=policy, headers=headers)
    assert preview.status_code == 200
    assert "grace_seconds" not in preview.json()["proposed"]
    applied = client.patch(
        f"/api/system-users/{account['id']}/quotas",
        json=dict(policy, token=preview.json()["token"]),
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    assert "grace_seconds" not in applied.json()
