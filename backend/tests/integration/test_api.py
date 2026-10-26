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
            "public_keys": [
                "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            ],
            "require_password_change": False,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    account = created.json()
    assert client.post("/api/system-groups", json={"name": "research"}, headers=headers).status_code == 200
    changes = {"primary_group": "research"}
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
    assert changed.json()["primary_group"] == "research"
    empty = client.post("/api/system-users", json={"username": "dave"}, headers=headers)
    assert empty.status_code == 422




def mark_bob_other(app):
    original = app.state.ctx.agent.call

    def call(method, params=None):
        result = original(method, params)
        if method == "snapshot":
            for row in result["accounts"] + result["tasks"]:
                row["is_human"] = row["uid"] != 1002
        elif method == "list_accounts":
            for row in result:
                row["is_human"] = row["uid"] != 1002
        return result

    app.state.ctx.agent.call = call
    app.state.ctx.invalidate()


def test_human_lists_default_and_other_remains_visible(client, app):
    login(client)
    mark_bob_other(app)
    tasks = client.get("/api/tasks").json()["items"]
    assert tasks and all(t["uid"] != 1002 for t in tasks)
    other = client.get("/api/tasks?scope=other").json()["items"]
    assert other and all(t["uid"] == 1002 for t in other)
    assert len(client.get("/api/tasks?scope=all").json()["items"]) == len(tasks) + len(other)
    assert all(a["uid"] != 1002 for a in client.get("/api/system-users").json())
    assert client.get("/api/system-users?scope=other").json()[0]["uid"] == 1002
    assert client.get("/api/system-users/demo-bob").status_code == 200
    assert all(u["is_human"] for u in client.get("/api/users").json())
    assert client.get("/api/tasks?scope=invalid").status_code == 422


def test_other_business_and_task_policy_rejected_before_persistence(client, app):
    headers = login(client)
    mark_bob_other(app)
    task = next(t for t in client.get("/api/tasks?scope=all").json()["items"] if t["uid"] == 1002)
    response = client.patch("/api/users/1002", json={"priority": 99}, headers=headers)
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "non_human_readonly"
    response = client.patch(
        f"/api/tasks/{task['id']}", json={"revision": task["revision"], "priority": 99}, headers=headers
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "non_human_readonly"
    assert client.get(f"/api/tasks/{task['id']}").json()["priority"] != 99
    assert (
        client.post(f"/api/tasks/{task['id']}/termination-preview", json={}, headers=headers).status_code
        == 403
    )


def test_web_created_account_is_automatically_managed_human(client):
    headers = login(client)
    response = client.post(
        "/api/system-users",
        json={
            "username": "managedcheck",
            "password": "Strong-user-pass-42",
            "require_password_change": False,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    account = response.json()
    assert account["managed"] is True and account["is_human"] is True
    assert "human" in account["groups"]
    assert account["primary_group"] == "managedcheck"
    assert account["shell"] == "/bin/bash"
    assert account["home"] == "/home/managedcheck"
    assert account["data_dir"] == "/data/managedcheck"
    assert any(a["id"] == account["id"] for a in client.get("/api/system-users").json())
    params = {"action": "update", "revision": account["revision"], "changes": {"notes": "already managed"}}
    preview = client.post(f"/api/system-users/{account['id']}/change-preview", json=params, headers=headers)
    assert preview.status_code == 200, preview.text
    updated = client.patch(
        f"/api/system-users/{account['id']}",
        json={"revision": account["revision"], "token": preview.json()["token"], "notes": "already managed"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["managed"] is True


def test_task_alias_keeps_original_name_across_edits_and_restart(client, app):
    headers = login(client)
    task = client.get("/api/tasks/demo-task-1").json()
    assert task["original_name"] == "alice / training"
    members = task["members"]
    for name in ("模型A训练", "模型A第二阶段"):
        response = client.patch(
            "/api/tasks/demo-task-1", json={"revision": task["revision"], "name": name}, headers=headers
        )
        assert response.status_code == 200, response.text
        task = response.json()
        assert task["name"] == name
        assert task["original_name"] == "alice / training"
        assert task["members"] == members
    with TestClient(create_app(app.state.config)) as restarted:
        login(restarted)
        task = restarted.get("/api/tasks/demo-task-1").json()
        assert task["name"] == "模型A第二阶段"
        assert task["original_name"] == "alice / training"


def test_task_template_settings_read_patch_and_preserve_existing_tasks(client):
    headers = login(client)
    initial = client.get("/api/settings").json()
    template = {
        "default_max_runtime_seconds": 1800,
        "default_task_protected": False,
        "default_task_priority": 50,
        "default_deadline_action": "notify",
        "default_cleanup_orphans": False,
    }
    assert template.items() <= initial.items()
    before = client.get("/api/tasks").json()["items"]
    changed = dict(
        template,
        default_max_runtime_seconds=None,
        default_task_protected=True,
        default_task_priority=100,
        default_deadline_action="terminate",
        default_cleanup_orphans=True,
    )
    response = client.patch("/api/settings", json=changed, headers=headers)
    assert response.status_code == 200, response.text
    assert changed.items() <= response.json().items()
    assert changed.items() <= client.get("/api/settings").json().items()
    after = client.get("/api/tasks").json()["items"]
    fields = (
        "id",
        "name",
        "original_name",
        "protected",
        "priority",
        "max_runtime_seconds",
        "deadline_action",
        "cleanup_orphans",
        "revision",
    )
    assert [{key: task[key] for key in fields} for task in before] == [
        {key: task[key] for key in fields} for task in after
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("default_task_protected", "false"),
        ("default_task_protected", 0),
        ("default_task_protected", None),
        ("default_cleanup_orphans", "true"),
        ("default_cleanup_orphans", 1),
        ("default_cleanup_orphans", None),
        ("default_task_priority", -1),
        ("default_task_priority", 101),
        ("default_task_priority", True),
        ("default_task_priority", "50"),
        ("default_task_priority", None),
        ("default_max_runtime_seconds", True),
        ("default_max_runtime_seconds", "1800"),
        ("default_max_runtime_seconds", 315360001),
        ("default_deadline_action", "kill"),
        ("default_deadline_action", None),
    ],
)
def test_task_template_api_rejects_invalid_parameters(client, field, value):
    headers = login(client)
    before = client.get("/api/settings").json()
    response = client.patch("/api/settings", json={field: value}, headers=headers)
    assert response.status_code == 422, response.text
    assert client.get("/api/settings").json() == before


def test_residual_api_defaults_active_filter_and_strict_fields(client):
    headers = login(client)
    settings = client.get("/api/settings").json()
    assert settings["default_orphan_reminder"] is True
    assert settings["default_orphan_wait_seconds"] == 300
    tasks = client.get("/api/tasks?status=active").json()["items"]
    assert tasks
    task = tasks[0]
    assert task["orphan_reminder"] is True
    assert task["orphan_wait_seconds"] == 300
    assert client.get("/api/overview").json()["awaiting_cleanup_count"] == 0
    for field, value in [
        ("orphan_reminder", "true"),
        ("orphan_wait_seconds", True),
        ("orphan_wait_seconds", 0),
        ("orphan_wait_seconds", 86401),
        ("orphan_wait_seconds", None),
    ]:
        response = client.patch(
            f"/api/tasks/{task['id']}", json={"revision": task["revision"], field: value}, headers=headers
        )
        assert response.status_code == 422
        response = client.patch("/api/settings", json={f"default_{field}": value}, headers=headers)
        assert response.status_code == 422
    response = client.post(
        f"/api/tasks/{task['id']}/termination-preview", json={"residual_only": True}, headers=headers
    )
    assert response.status_code == 409


def test_stale_awaiting_cleanup_task_detail_and_list_block_preview(client, app, monkeypatch):
    headers = login(client)
    original = app.state.ctx.agent.call

    def call(method, params=None):
        result = original(method, params)
        if method == "snapshot":
            result["stale"] = True
            task = result["tasks"][0]
            task["status"] = "awaiting_cleanup"
            task["finalizing_since"] = "2026-01-01T00:00:00+00:00"
        return result

    monkeypatch.setattr(app.state.ctx.agent, "call", call)
    app.state.ctx.invalidate()
    payload = client.get("/api/tasks?status=awaiting_cleanup").json()
    assert payload["stale"] is True
    task = payload["items"][0]
    assert task["stale"] is True
    detail = client.get(f"/api/tasks/{task['id']}").json()
    assert detail["stale"] is True
    assert detail["status"] == "awaiting_cleanup"
    response = client.post(
        f"/api/tasks/{task['id']}/termination-preview", json={"residual_only": True}, headers=headers
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_snapshot"


def test_executable_allowlist_hides_old_tasks_and_reverses(client, app):
    import json
    import sqlite3

    headers = login(client)
    assert client.get("/api/settings").json()["ignored_task_executables"] == [
        "/usr/lib/xorg/Xorg",
        "/usr/bin/Xorg",
    ]
    original = client.get("/api/tasks?scope=all").json()["items"]
    hidden_id = original[0]["id"]
    other_id = original[1]["id"]
    with sqlite3.connect(app.state.config.agent_database) as db:
        state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        task = next(t for t in state["tasks"] if t["id"] == hidden_id)
        for member in task["members"]:
            member["exe"] = "/usr/lib/xorg/Xorg"
        other = next(t for t in state["tasks"] if t["id"] == other_id)
        other["members"][0]["exe"] = "/usr/bin/python"
        other["members"][0]["command"] += " /usr/lib/xorg/Xorg"
        expected_gpus = state["gpus"]
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    app.state.ctx.invalidate()
    listed = client.get("/api/tasks?scope=all").json()["items"]
    assert [t["id"] for t in listed] == [other_id]
    assert client.get(f"/api/tasks/{hidden_id}").status_code == 404
    assert client.get("/api/overview").json()["task_count"] == 1
    assert client.get("/api/gpus").json()["items"] == expected_gpus
    assert (
        client.patch("/api/settings", json={"ignored_task_executables": []}, headers=headers).status_code
        == 200
    )
    assert {t["id"] for t in client.get("/api/tasks?scope=all").json()["items"]} == {hidden_id, other_id}
    assert client.get(f"/api/tasks/{hidden_id}").status_code == 200
    for invalid in [None, "/x", ["/x/*"], ["/x/../y"], [1]]:
        assert (
            client.patch(
                "/api/settings", json={"ignored_task_executables": invalid}, headers=headers
            ).status_code
            == 422
        )
    assert client.get("/api/settings").json()["ignored_task_executables"] == []


@pytest.mark.parametrize("missing_group", [False, True])
def test_authoritative_mutation_health_and_fresh_credential_recovery(client, app, missing_group):
    import json
    import sqlite3

    assert client.get("/api/health").json()["mutations"] is True
    headers = login(client)
    group = client.post(
        "/api/groups", json={"name": "recovered-profile", "priority": 70}, headers=headers
    ).json()
    account = next(a for a in client.get("/api/system-users").json() if not a["protected"])
    with sqlite3.connect(app.state.config.agent_database) as db:
        state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        pending = next(a for a in state["accounts"] if a["id"] == account["id"])
        pending["creation"] = dict(
            status="incomplete",
            stage="credentials",
            started_at="2026-01-01T00:00:00+00:00",
            profile={"group_id": 9999 if missing_group else group["id"], "priority": 17},
        )
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    account = client.get(f"/api/system-users/{account['id']}").json()
    assert "creation_incomplete" in account["readonly_reasons"]
    preview = client.post(
        f"/api/system-users/{account['id']}/change-preview",
        headers=headers,
        json=dict(action="resume", revision=account["revision"], changes={}),
    )
    assert preview.status_code == 200, preview.text
    payload = dict(
        token=preview.json()["token"], revision=account["revision"], reason="Resume failed initialization"
    )
    assert (
        client.post(f"/api/system-users/{account['id']}/resume", headers=headers, json=payload).status_code
        == 422
    )
    payload["password"] = "Fresh-recovery-password-123"
    result = client.post(f"/api/system-users/{account['id']}/resume", headers=headers, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["creation"]["status"] == "complete"
    recovered = client.get(f"/api/system-users/{account['id']}").json()
    assert recovered["group_id"] == (1 if missing_group else group["id"]) and recovered["priority"] == 17
    if missing_group:
        audit = client.get("/api/audit-logs", params={"action": "account.recovery_profile_default"}).json()[
            "items"
        ]
        assert len(audit) == 1 and "9999" in audit[0]["reason"]
    with sqlite3.connect(app.state.config.agent_database) as db:
        assert payload["password"] not in db.execute("SELECT data FROM state WHERE id=1").fetchone()[0]


def test_health_forwards_safe_storage_readiness_and_fails_closed(client, app, monkeypatch):
    assert client.get("/api/health").json()["root_readiness"] == {"ready": True, "error_code": None}

    def health_unavailable(method, params=None):
        from gpupm.errors import DomainError

        raise DomainError("agent_unavailable", "unavailable", 503)

    monkeypatch.setattr(app.state.ctx.agent, "call", health_unavailable)
    health = client.get("/api/health").json()
    assert not health["mutations"] and not health["root_readiness"]["ready"]
    assert health["root_readiness"]["error_code"] == "agent_unavailable"


def test_account_preview_binds_business_changes_before_native_mutation(client):
    headers = login(client)
    account = next(a for a in client.get("/api/system-users").json() if a["managed"] and not a["protected"])
    group = client.post(
        "/api/groups", json={"name": "preview-profile", "priority": 50}, headers=headers
    ).json()
    path = f"/api/system-users/{account['id']}"
    changes = {"group_id": group["id"], "priority": 17, "notes": "native reviewed note"}
    preview = client.post(
        path + "/change-preview",
        headers=headers,
        json={"action": "update", "revision": account["revision"], "changes": changes},
    ).json()
    assert preview["business_changes"] == {"group_id": group["id"], "priority": 17}
    assert preview["current"]["priority"] == account["priority"]
    assert preview["proposed"]["group_id"] == group["id"] and preview["proposed"]["priority"] == 17
    rejected = client.patch(
        path,
        headers=headers,
        json=dict(changes, priority=18, revision=account["revision"], token=preview["token"]),
    )
    assert rejected.status_code == 409
    unchanged = client.get(path).json()
    assert unchanged["notes"] == account["notes"] and unchanged["priority"] == account["priority"]
    preview = client.post(
        path + "/change-preview",
        headers=headers,
        json={"action": "update", "revision": unchanged["revision"], "changes": changes},
    ).json()
    accepted = client.patch(
        path, headers=headers, json=dict(changes, revision=unchanged["revision"], token=preview["token"])
    )
    assert accepted.status_code == 200, accepted.text
    updated = client.get(path).json()
    assert updated["priority"] == 17 and updated["group_id"] == group["id"]
    preview = client.post(
        path + "/change-preview",
        headers=headers,
        json={"action": "update", "revision": updated["revision"], "changes": {"group_id": 1}},
    ).json()
    accepted = client.patch(
        path,
        headers=headers,
        json={"group_id": 1, "revision": updated["revision"], "token": preview["token"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert client.get(path).json()["priority"] == 17


@pytest.mark.parametrize("changes", [{"priority": True}, {"group_id": -1}, {"priority": None}])
def test_account_preview_rejects_invalid_business_fields(client, changes):
    headers = login(client)
    account = next(a for a in client.get("/api/system-users").json() if a["managed"] and not a["protected"])
    result = client.post(
        f"/api/system-users/{account['id']}/change-preview",
        headers=headers,
        json={"action": "update", "revision": account["revision"], "changes": changes},
    )
    assert result.status_code == 422


def test_quota_feature_removed_but_storage_and_shares_remain(client, app):
    headers = login(client)
    for method, path in [('GET', '/api/system-users/1001/quotas'),
                         ('POST', '/api/system-users/1001/quotas/preview'),
                         ('PATCH', '/api/system-users/1001/quotas')]:
        assert client.request(method, path, headers=headers, json={}).status_code in {404, 405}
    storage = client.get('/api/storage').json()
    assert 'quotas' not in storage
    assert all('quota_enabled' not in fs and 'quota_supported' not in fs for fs in storage['filesystems'])
    assert client.get('/api/shares').status_code == 200
    assert not any('/quotas' in path for path in app.openapi()['paths'])


def test_directory_refresh_requires_auth_and_csrf_and_updates_timestamp(client):
    assert client.post('/api/storage/refresh').status_code == 401
    headers = login(client)
    assert client.post('/api/storage/refresh').status_code == 403
    result = client.post('/api/storage/refresh', headers=headers)
    assert result.status_code == 200
    assert client.get('/api/storage').json()['directory_collected_at']


def test_share_member_permissions_create_change_and_revoke(client):
    headers = login(client)
    users = client.get('/api/system-users').json()
    user = next(a for a in users if a['managed'] and not a['protected'] and a['status']=='active')
    changes = dict(name='member-project', members=[dict(username=user['username'],permission='read')])
    preview=client.post('/api/shares/change-preview',headers=headers,json=dict(action='create',changes=changes))
    assert preview.status_code == 200, preview.text
    created=client.post('/api/shares',headers=headers,json=dict(changes,token=preview.json()['token']))
    assert created.status_code == 200, created.text
    share=created.json()
    assert share['access_mode']=='members'
    for permission in ('write',None):
        members=[dict(username=user['username'],permission=permission)] if permission else []
        preview=client.post(f"/api/shares/{share['id']}/change-preview",headers=headers,json=dict(revision=share['revision'],changes=dict(members=members)))
        assert preview.status_code==200,preview.text
        changed=client.patch(f"/api/shares/{share['id']}",headers=headers,json=dict(revision=share['revision'],token=preview.json()['token'],members=members))
        assert changed.status_code==200,changed.text
        share=changed.json()
        listed=next(s for s in client.get('/api/shares').json() if s['id']==share['id'])
        assert listed['members']==members
    groups=client.get('/api/system-groups?scope=all').json()
    owned=[g for g in groups if g.get('share_owner')=='member-project']
    assert len(owned)==2
    assert all(not g['assignable'] for g in owned)


def test_shared_preview_rejects_stale_revision_like_native_agent(client):
    headers = login(client)
    changes = dict(name='revision-preview',members=[])
    preview = client.post('/api/shares/change-preview',headers=headers,json=dict(action='create',changes=changes)).json()
    share = client.post('/api/shares',headers=headers,json=dict(changes,token=preview['token'])).json()
    params = dict(revision=share['revision'],changes=dict(notes='updated'))
    preview = client.post(f"/api/shares/{share['id']}/change-preview",headers=headers,json=params).json()
    result = client.patch(f"/api/shares/{share['id']}",headers=headers,json=dict(revision=share['revision'],notes='updated',token=preview['token']))
    assert result.status_code == 200
    stale = client.post(f"/api/shares/{share['id']}/change-preview",headers=headers,json=params)
    assert stale.status_code == 409
    assert stale.json()['detail']['code'] == 'revision_conflict'


def test_gpu_filter_keeps_finished_tasks_without_live_members(client, app):
    login(client)
    original = app.state.ctx.agent.call

    def call(method, *args, **kwargs):
        value = original(method, *args, **kwargs)
        if method == 'snapshot':
            task = value['tasks'][0]
            task.update(status='finished', members=[], gpu_uuids=['historic-gpu'])
        return value

    app.state.ctx.agent.call = call
    app.state.ctx.invalidate()
    rows = client.get('/api/tasks?gpu=historic-gpu&status=finished').json()['items']
    assert len(rows) == 1
    assert rows[0]['members'] == []
    assert client.get('/api/tasks?gpu=historic-gpu&status=active').json()['total'] == 0
    assert client.get('/api/tasks?gpu=other-gpu&status=finished').json()['total'] == 0


@pytest.mark.parametrize('known_end', [True, False])
def test_finished_task_api_does_not_keep_counting(client, app, monkeypatch, known_end):
    from datetime import datetime, timedelta, timezone

    login(client)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = start + timedelta(hours=1)
    monkeypatch.setattr('gpupm.api.context.utcnow', lambda: now)
    original = app.state.ctx.agent.call

    def call(method, *args, **kwargs):
        value = original(method, *args, **kwargs)
        if method == 'snapshot':
            task = value['tasks'][0]
            task.update(status='finished', members=[], started_at=start.isoformat(),
                        max_runtime_seconds=300,
                        finished_at=(start + timedelta(seconds=300)).isoformat() if known_end else None)
        return value

    app.state.ctx.agent.call = call
    app.state.ctx.invalidate()
    task = client.get('/api/tasks?status=finished').json()['items'][0]
    assert task['runtime_seconds'] == (300 if known_end else None)
    assert task['remaining_seconds'] is None
    assert task['overdue'] is False
