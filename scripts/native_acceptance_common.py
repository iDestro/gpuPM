"""Shared live-agent fixtures. Never creates an agent or deletes account files."""

import grp
import json
import os
import pwd
import secrets
import stat
import subprocess
from pathlib import Path

from gpupm.api.agent_client import AgentClient


class CheckFailed(RuntimeError):
    pass


def require(condition, label):
    if not condition:
        raise CheckFailed(label)


def run(command, **kwargs):
    return subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=30, **kwargs
    )


def as_user(account, code, *args):
    return run(
        [
            "runuser",
            "-u",
            account["username"],
            "--",
            "python3",
            "-c",
            code,
            *map(str, args),
        ]
    )


class Fixtures:
    def __init__(self, socket):
        require(os.geteuid() == 0, "root execution required")
        info = Path(socket).stat()
        require(
            stat.S_ISSOCK(info.st_mode) and info.st_uid == 0,
            "root-owned agent socket required",
        )
        self.agent = AgentClient(socket, timeout=60)
        self.suffix = secrets.token_hex(5)
        self.names = []
        self.accounts = []
        self.checks = []
        self.artifacts = []

    def create(self, role, **credentials):
        name = f"gpupmqa_{role}_{self.suffix}"
        for lookup in (pwd.getpwnam, grp.getgrnam):
            try:
                lookup(name)
            except KeyError:
                continue
            raise CheckFailed("fixture identity already exists")
        self.names.append(
            name
        )  # Track partial provisioning as well as successful calls.
        account = self.agent.call(
            "execute_account_change",
            {
                "action": "create",
                "reason": "Disposable native acceptance fixture",
                "changes": {"username": name, **credentials},
            },
        )
        require(account["username"] == name, "created identity mismatch")
        self.accounts.append(account)
        self.artifacts.append(
            {k: account.get(k) for k in ("id", "username", "uid", "home", "data_dir")}
        )
        return account

    def current(self, account):
        return next(
            a for a in self.agent.call("list_accounts") if a["id"] == account["id"]
        )

    def change(self, account, action, changes=None):
        current = self.current(account)
        require(
            current["username"] in self.names and current["uid"] == account["uid"],
            "fixture identity changed",
        )
        changes = changes or {}
        params = {
            "id": current["id"],
            "revision": current["revision"],
            "action": action,
            "reason": "Disposable native acceptance fixture",
            "changes": {k: v for k, v in changes.items() if k != "password"},
        }
        token = self.agent.call("preview_account_change", params)["token"]
        return self.agent.call(
            "execute_account_change", dict(params, token=token, changes=changes)
        )

    def cleanup(self):
        errors = []
        try:
            accounts = self.agent.call("list_accounts")
        except Exception:  # noqa: BLE001 - Cleanup must continue without exposing diagnostics.
            return ["unable to list fixtures for soft-delete"]
        for account in accounts:
            if account["username"] in self.names:
                try:
                    original = next(
                        (
                            a
                            for a in self.accounts
                            if a["username"] == account["username"]
                        ),
                        None,
                    )
                    require(
                        original is not None,
                        "partial creation requires identity review before cleanup",
                    )
                    require(
                        account["uid"] == original["uid"],
                        "fixture UID changed before cleanup",
                    )
                    self.change(original, "delete")
                except Exception as exc:  # noqa: BLE001 - Only sanitized error codes leave the runner.
                    errors.append(
                        {
                            "username": account["username"],
                            "error": getattr(exc, "code", type(exc).__name__),
                        }
                    )
        return errors

    def check(self, condition, label):
        require(condition, label)
        self.checks.append(label)


def execute(args, operation):
    """Emit only an allowlisted summary; native stderr and exceptions may contain secrets."""
    fixtures = None
    report = {"status": "failed", "checks": [], "retained_fixtures": []}
    try:
        fixtures = Fixtures(args.socket)
        operation(fixtures, args)
        report["status"] = "passed"
    except Exception as exc:  # noqa: BLE001 - Only sanitized error codes leave the runner.
        report["error"] = (
            str(exc)
            if isinstance(exc, CheckFailed)
            else getattr(exc, "code", type(exc).__name__)
        )
    finally:
        if fixtures:
            report.update(checks=fixtures.checks, retained_fixtures=fixtures.artifacts)
            report["cleanup_errors"] = fixtures.cleanup()
            report["requested_fixture_names"] = fixtures.names
            if report["cleanup_errors"]:
                report["status"] = "failed"
    rendered = json.dumps(report, indent=2)
    if args.output:
        # Refuse overwrites/symlinks, including another run's evidence.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(rendered + "\n")
    print(rendered)
    return 0 if report["status"] == "passed" else 1
