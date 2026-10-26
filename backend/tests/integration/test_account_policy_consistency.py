import json
import sqlite3

import pytest
from test_api import login

pytest_plugins = ["test_api"]


@pytest.mark.parametrize(
    "state_change",
    [
        {"disabled": True},
        {"expires_on": "2000-01-01"},
        {"creation": {"status": "incomplete"}},
    ],
)
def test_legacy_account_policy_checks_preview_and_execution(client, app, state_change):
    headers = login(client)
    account = next(a for a in client.get("/api/system-users").json() if a["uid"] == 1001)
    path = f"/api/system-users/{account['id']}"
    changes = {"priority": 81}
    preview = client.post(
        path + "/change-preview",
        headers=headers,
        json={
            "action": "update",
            "revision": account["revision"],
            "changes": changes,
        },
    )
    assert preview.status_code == 200, preview.text
    with sqlite3.connect(app.state.config.agent_database) as db:
        state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        next(a for a in state["accounts"] if a["uid"] == 1001).update(state_change)
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    app.state.ctx.invalidate()
    modern = client.patch("/api/users/1001", headers=headers, json=changes)
    assert modern.status_code == 403, modern.text
    old_preview = client.post(
        path + "/change-preview",
        headers=headers,
        json={
            "action": "update",
            "revision": account["revision"],
            "changes": changes,
        },
    )
    assert old_preview.status_code == 403, old_preview.text
    old_update = client.patch(
        path,
        headers=headers,
        json={
            **changes,
            "revision": account["revision"],
            "token": preview.json()["token"],
        },
    )
    assert old_update.status_code == 403, old_update.text
    assert client.get(path).json()["priority"] == account["priority"]


def test_legacy_account_policy_freezes_existing_tasks_before_update(client, app):
    import copy
    from gpupm.db.models import TaskConfig
    from gpupm.domain.rules import utcnow

    headers = login(client)
    account = next(a for a in client.get("/api/system-users").json() if a["uid"] == 1001)
    path = f"/api/system-users/{account['id']}"
    changes = {"priority": 81}
    preview = client.post(
        path + "/change-preview",
        headers=headers,
        json={
            "action": "update",
            "revision": account["revision"],
            "changes": changes,
        },
    ).json()
    with sqlite3.connect(app.state.config.agent_database) as db:
        state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        task = copy.deepcopy(next(t for t in state["tasks"] if t["uid"] == 1001))
        task.update(id="before-legacy-policy-edit", revision=1, started_at=utcnow().isoformat())
        state["tasks"].append(task)
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
    app.state.ctx.invalidate()
    result = client.patch(
        path,
        headers=headers,
        json={
            **changes,
            "revision": account["revision"],
            "token": preview["token"],
        },
    )
    assert result.status_code == 200, result.text
    with app.state.ctx.sessions() as db:
        config = db.get(TaskConfig, task["id"])
        assert config is not None
        assert config.policy["priority"] == 50
        assert config.assignment_snapshot["group_id"] == 1
    app.state.ctx.heartbeat()
    assert client.get(f"/api/tasks/{task['id']}").json()["priority"] == 50
    user = next(u for u in client.get("/api/users").json() if u["uid"] == 1001)
    assert user["effective_policy"]["priority"] == 81
