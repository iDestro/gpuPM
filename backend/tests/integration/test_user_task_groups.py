import pytest
from test_api import login

pytest_plugins = ["test_api"]


def test_policy_groups_inherit_and_override(client):
    headers = login(client)
    groups = client.get("/api/groups").json()
    assert any(g.get("is_custom") for g in groups)
    group = client.post(
        "/api/groups",
        headers=headers,
        json={"name": "inherited", "policy_overrides": {"max_runtime_seconds": None}},
    )
    assert group.status_code == 200, group.text
    group = group.json()
    assert group["effective_policy"]["max_runtime_seconds"] is None
    assert group["policy_sources"]["priority"] == "global"
    assert (
        client.patch(
            "/api/groups/1", headers=headers, json={"policy_overrides": {"priority": 90}}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/groups", headers=headers, json={"name": "bad", "policy_overrides": {"priority": True}}
        ).status_code
        == 422
    )


def test_personal_policy_retained_only_active_in_custom_group(client):
    headers = login(client)
    user = next(u for u in client.get("/api/users").json() if u.get("policy_editable"))
    custom = next(g for g in client.get("/api/groups").json() if g["is_custom"])
    url = f"/api/users/{user['uid']}"
    saved = client.patch(
        url, headers=headers, json={"group_id": custom["id"], "personal_policy": {"priority": 88}}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["effective_policy"]["priority"] == 88
    default = client.patch(url, headers=headers, json={"group_id": 1}).json()
    assert default["personal_policy"] == {"priority": 88}
    assert default["effective_policy"]["priority"] == 50
    restored = client.patch(url, headers=headers, json={"group_id": custom["id"]}).json()
    assert restored["effective_policy"]["priority"] == 88


def test_new_task_snapshot_and_explicit_edit(client, app):
    import copy
    import json
    import sqlite3
    from gpupm.domain.rules import utcnow

    headers = login(client)
    group = client.post(
        "/api/groups",
        headers=headers,
        json={
            "name": "training",
            "policy_overrides": {"priority": 87, "max_runtime_seconds": 600, "protected": True},
        },
    ).json()
    assert client.patch("/api/users/1001", headers=headers, json={"group_id": group["id"]}).status_code == 200
    with sqlite3.connect(app.state.config.agent_database) as db:
        state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        task = copy.deepcopy(state["tasks"][0])
        task.update(id="new-policy-task", revision=1, started_at=utcnow().isoformat())
        state["tasks"].append(task)
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    app.state.ctx.heartbeat()
    task = client.get("/api/tasks/new-policy-task").json()
    assert task["max_runtime_seconds"] == 600
    assert task["priority"] == 87
    assert task["policy_sources"]["priority"] == "group"
    assert task["priority_tuple"] == [87, 87, 87]
    client.patch(
        f"/api/groups/{group['id']}",
        headers=headers,
        json={"policy_overrides": {"max_runtime_seconds": 1, "priority": 2}},
    )
    client.patch("/api/users/1001", headers=headers, json={"group_id": 1})
    client.patch("/api/settings", headers=headers, json={"default_max_runtime_seconds": 2})
    app.state.ctx.heartbeat()
    frozen = client.get("/api/tasks/new-policy-task").json()
    assert frozen["max_runtime_seconds"] == 600
    assert frozen["priority"] == 87
    changed = client.patch(
        "/api/tasks/new-policy-task",
        headers=headers,
        json={"revision": frozen["revision"], "protected": False, "max_runtime_seconds": None},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["protected"] is False
    assert changed.json()["max_runtime_seconds"] is None
    assert changed.json()["policy_sources"]["protected"] == "task"


def test_policy_changes_reject_ineligible_accounts(client, app):
    import json
    import sqlite3

    headers = login(client)
    for field, value in [("managed", False), ("protected", True), ("disabled", True)]:
        with sqlite3.connect(app.state.config.agent_database) as db:
            state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
            account = next(a for a in state["accounts"] if a["uid"] == 1001)
            account.update(managed=True, protected=False, disabled=False)
            account[field] = value
            db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
        app.state.ctx.invalidate()
        result = client.patch("/api/users/1001", headers=headers, json={"personal_policy": {"priority": 80}})
        assert result.status_code == 403, result.text


def test_group_delete_and_validation_boundaries(client):
    headers = login(client)
    for overrides in [
        {"priority": None},
        {"priority": 101},
        {"protected": 1},
        {"max_runtime_seconds": 0},
        {"max_runtime_seconds": "60"},
        {"orphan_wait_seconds": 86401},
        {"deadline_action": "kill"},
        {"cleanup_orphans": True},
    ]:
        assert (
            client.post(
                "/api/groups", headers=headers, json={"name": "invalid", "policy_overrides": overrides}
            ).status_code
            == 422
        )
    groups = client.get("/api/groups").json()
    for builtin in groups:
        if builtin["is_default"] or builtin["is_custom"]:
            assert client.delete(f"/api/groups/{builtin['id']}", headers=headers).status_code == 409
    group = client.post(
        "/api/groups", headers=headers, json={"name": "temporary", "policy_overrides": {"priority": 70}}
    ).json()
    client.patch(
        "/api/users/1001",
        headers=headers,
        json={"group_id": group["id"], "personal_policy": {"priority": 90}},
    )
    client.patch("/api/settings", headers=headers, json={"default_max_runtime_seconds": 123})
    user = next(u for u in client.get("/api/users").json() if u["uid"] == 1001)
    assert user["effective_policy"]["priority"] == 70
    assert user["effective_policy"]["max_runtime_seconds"] == 123
    assert client.delete(f"/api/groups/{group['id']}", headers=headers).status_code == 200
    user = next(u for u in client.get("/api/users").json() if u["uid"] == 1001)
    assert user["group_id"] == 1 and user["personal_policy"] == {"priority": 90}


def test_task_policy_guard_does_not_persist_rejected_overlay(client, app):
    import json
    import sqlite3
    import pytest
    from gpupm.errors import DomainError
    from gpupm.db.models import TaskConfig

    headers = login(client)
    app.state.ctx.heartbeat()
    before = client.get("/api/tasks/demo-task-1").json()
    with app.state.sessions() as db:
        old_policy = db.get(TaskConfig, before["id"]).policy.copy()
    with sqlite3.connect(app.state.config.agent_database) as db:
        state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        state["accounts"][0].update(disabled=True, protected=True)
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    app.state.ctx.invalidate()
    changes = {"protected": False, "deadline_action": "terminate", "max_runtime_seconds": 1}
    response = client.patch(
        "/api/tasks/demo-task-1", headers=headers, json=dict(revision=before["revision"], **changes)
    )
    assert response.status_code == 403
    assert client.get("/api/tasks/demo-task-1").json()["policy_editable"] is False
    with app.state.sessions() as db:
        assert db.get(TaskConfig, before["id"]).policy == old_policy
    with pytest.raises(DomainError, match="read-only"):
        app.state.ctx.agent.call(
            "apply_task_policy", {"task_id": before["id"], "revision": before["revision"], "policy": changes}
        )


@pytest.mark.parametrize("edit", [False, True])
def test_first_edit_before_heartbeat_keeps_entire_group_policy(app, edit):
    import copy
    import json
    import sqlite3
    from fastapi.testclient import TestClient
    from gpupm.domain.rules import utcnow
    from gpupm.db.models import ManagementGroup, ManagedUser

    # No lifespan means no background sync: exercise the discovery/edit race.
    client = TestClient(app)
    headers = login(client)
    app.state.ctx.users()
    with app.state.sessions.begin() as db:
        group = ManagementGroup(
            name="early-edit", policy_overrides={"priority": 87, "max_runtime_seconds": 600}
        )
        db.add(group)
        db.flush()
        db.get(ManagedUser, 1001).group_id = group.id
    with sqlite3.connect(app.state.config.agent_database) as db:
        state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        new = copy.deepcopy(state["tasks"][0])
        new.update(id="first-edit", started_at=utcnow().isoformat(), revision=2)
        state["tasks"].append(new)
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    app.state.ctx.invalidate()
    if edit:
        response = client.patch(
            "/api/tasks/first-edit", headers=headers, json={"revision": 2, "notes": "first edit"}
        )
    else:
        app.state.ctx.heartbeat()
        response = client.get("/api/tasks/first-edit")
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["priority"] == 87 and saved["max_runtime_seconds"] == 600
    assert saved["policy_sources"]["priority"] == "group"
    if edit:
        assert saved["policy_sources"]["notes"] == "task"
    assert saved["priority_tuple"] == [87, 87, 87]
    app.state.ctx.heartbeat()
    assert client.get("/api/tasks/first-edit").json()["max_runtime_seconds"] == 600


def test_group_member_counts_match_human_member_list(client, app):
    from gpupm.db.models import ManagedUser

    headers = login(client)
    people = client.get("/api/users").json()
    group = client.post("/api/groups", headers=headers, json={"name": "count-test"}).json()
    with app.state.sessions.begin() as db:
        db.add(ManagedUser(uid=99, username="service-account", group_id=1))
        db.add(ManagedUser(uid=98, username="other-service", group_id=group["id"]))
        db.get(ManagedUser, people[0]["uid"]).group_id = group["id"]
    visible = client.get("/api/users").json()
    groups = client.get("/api/groups").json()
    for row in groups:
        assert row["member_count"] == sum(u["group_id"] == row["id"] for u in visible)
    changed = client.patch(f"/api/groups/{group['id']}", headers=headers, json={"notes": "count checked"})
    assert changed.status_code == 200
    assert changed.json()["member_count"] == 1


def test_bulk_membership_atomic_conflict_and_personal_retention(client):
    headers = login(client)
    members = [u for u in client.get("/api/users").json() if u["policy_editable"]][:2]
    assert len(members) == 2
    target = client.post("/api/groups", headers=headers, json={"name": "batch"}).json()["id"]
    first = members[0]
    client.patch(f"/api/users/{first['uid']}", headers=headers, json={"personal_policy": {"priority": 93}})
    before_tasks = client.get("/api/tasks").json()["items"]
    payload = {"members": [{"uid": u["uid"], "group_id": u["group_id"]} for u in members]}
    response = client.post(f"/api/groups/{target}/members", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    after = {u["uid"]: u for u in client.get("/api/users").json()}
    assert all(after[u["uid"]]["group_id"] == target for u in members)
    assert after[first["uid"]]["personal_policy"] == {"priority": 93}
    assert client.post("/api/groups/1/members", headers=headers, json=payload).status_code == 409
    assert all(
        u["group_id"] == target
        for u in client.get("/api/users").json()
        if u["uid"] in after and u["uid"] in {m["uid"] for m in members}
    )
    after_tasks = client.get("/api/tasks").json()["items"]
    assert [(t["id"], t["priority"], t.get("assignment_snapshot")) for t in before_tasks] == [
        (t["id"], t["priority"], t.get("assignment_snapshot")) for t in after_tasks
    ]


def test_bulk_membership_rejects_invalid_account_without_partial_write(client):
    headers = login(client)
    user = next(u for u in client.get("/api/users").json() if u["policy_editable"])
    target = client.post("/api/groups", headers=headers, json={"name": "atomic"}).json()["id"]
    response = client.post(
        f"/api/groups/{target}/members",
        headers=headers,
        json={"members": [{"uid": user["uid"], "group_id": user["group_id"]}, {"uid": 0, "group_id": 1}]},
    )
    assert response.status_code in (403, 404), response.text
    assert (
        next(u for u in client.get("/api/users").json() if u["uid"] == user["uid"])["group_id"]
        == user["group_id"]
    )
    for members in ([], [{"uid": True, "group_id": 1}], [{"uid": user["uid"], "group_id": 1}] * 2):
        assert (
            client.post(
                f"/api/groups/{target}/members", headers=headers, json={"members": members}
            ).status_code
            == 422
        )


def test_bulk_membership_checks_live_account_protection(client, app):
    import json
    import sqlite3

    headers = login(client)
    users = [u for u in client.get("/api/users").json() if u["policy_editable"]][:2]
    target = client.post("/api/groups", headers=headers, json={"name": "protected-batch"}).json()["id"]
    with sqlite3.connect(app.state.config.agent_database) as db:
        state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        next(a for a in state["accounts"] if a["uid"] == users[1]["uid"])["protected"] = True
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    response = client.post(
        f"/api/groups/{target}/members",
        headers=headers,
        json={"members": [{"uid": u["uid"], "group_id": u["group_id"]} for u in users]},
    )
    assert response.status_code == 403, response.text
    actual = {u["uid"]: u["group_id"] for u in client.get("/api/users").json()}
    assert all(actual[u["uid"]] == u["group_id"] for u in users)
