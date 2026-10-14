"""Unprivileged real HTTP smoke for the temporary QA systemd services."""

import json
import os
from pathlib import Path
import secrets
import time
import httpx
from gpupm.api.auth import Auth
from gpupm.db.session import database

assert os.geteuid() == 1000
_, sessions = database(Path("/var/lib/gpupm-qa/api/app.sqlite"))
username = "qa-" + secrets.token_hex(3)
password = secrets.token_urlsafe(24)
Auth(sessions).create_admin(username, password)
with httpx.Client(base_url="http://127.0.0.1:18000", timeout=20) as client:
    for _ in range(20):
        try:
            if client.get("/api/health").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    assert client.get("/api/tasks").status_code == 401
    login = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert login.status_code == 200, login.text
    tasks = client.get("/api/tasks")
    assert (
        tasks.status_code == 200
        and tasks.json()["source"] == "host"
        and not tasks.json()["stale"]
    ), tasks.text
    assert client.get("/").status_code == 200
    assert client.get("/accounts").status_code == 200
    assert client.get("/api/storage").status_code == 200
    assert (
        client.post(
            "/api/auth/logout", headers={"X-CSRF-Token": login.json()["csrf_token"]}
        ).status_code
        == 200
    )
    assert client.get("/api/tasks").status_code == 401
    print(
        json.dumps(
            {
                "checks": [
                    "ordinary_user_systemd_API",
                    "root_systemd_agent",
                    "real_HTTP_auth_CSRF",
                    "host_snapshot",
                    "SPA_routes",
                    "logout_invalidated",
                ],
                "tasks": tasks.json()["total"],
            }
        )
    )
