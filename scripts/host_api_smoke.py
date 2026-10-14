"""Run unprivileged against the explicitly configured root QA socket."""

import json
import os
from pathlib import Path
import secrets
from fastapi.testclient import TestClient
from gpupm.api.main import create_app
from gpupm.config import Config

assert os.geteuid() != 0
root = Path.home() / "gpupm-qa"
app = create_app(
    Config(
        mode="host",
        database=root / ("api-" + secrets.token_hex(3) + ".sqlite"),
        agent_socket="/var/lib/gpupm-qa/readonly.sock",
        home_base="/var/lib/gpupm-qa/home",
        data_base="/var/lib/gpupm-qa/data",
    )
)
password = secrets.token_urlsafe(24)
app.state.auth.create_admin("qa-admin", password)
with TestClient(app) as client:
    assert client.get("/api/tasks").status_code == 401
    login = client.post(
        "/api/auth/login", json={"username": "qa-admin", "password": password}
    )
    assert login.status_code == 200, login.text
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    tasks = client.get("/api/tasks").json()
    assert tasks["source"] == "host" and not tasks["stale"], tasks
    assert client.get("/api/gpus").json()["items"]
    accounts = client.get("/api/system-users?state=all")
    assert accounts.status_code == 200 and accounts.json()
    for path in (
        "/api/storage",
        "/api/login-events",
        "/api/system-groups",
        "/api/audit-logs",
    ):
        result = client.get(path)
        assert result.status_code == 200, (path, result.text)
    created = client.post(
        "/api/system-users",
        headers=headers,
        json={"username": "gpupmqa_forbidden", "password": "Random-long-QA-pass!123"},
    )
    assert (
        created.status_code == 403
        and created.json()["detail"]["code"] == "mutations_disabled"
    ), created.text
    print(
        json.dumps(
            {
                "checks": [
                    "nonroot_API_root_socket",
                    "host_GPU_tasks_accounts",
                    "storage_login_audit_routes",
                    "readonly_native_write_rejected",
                    "authentication_CSRF",
                ],
                "task_count": tasks["total"],
                "source": tasks["source"],
            }
        )
    )
