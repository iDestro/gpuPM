"""Real key-only SSH and managed expiry/cancellation on a disposable account."""

import json
import os
from pathlib import Path
import secrets
import subprocess
from gpupm.agent.host import AgentService
from gpupm.domain.rules import utcnow

assert os.geteuid() == 0
base = Path("/var/lib/gpupm-qa")
key = base / ("expiry-key-" + secrets.token_hex(3))
subprocess.run(
    ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True
)
service = AgentService(
    dict(
        store_path=str(base / "state.sqlite"),
        allow_mutations=True,
        home_base=str(base / "home"),
        data_base=str(base / "data"),
        share_base=str(base / "data/shared"),
        maintenance_users=["wuzhaoxiang"],
    )
)
name = "gpupmqa_key_" + secrets.token_hex(3)
account = service.call(
    "execute_account_change",
    {
        "action": "create",
        "changes": {
            "username": name,
            "public_keys": [key.with_suffix(".pub").read_text().strip()],
            "require_password_change": False,
        },
    },
)


def change(action, changes=None):
    global account
    account = next(a for a in service.call("list_accounts") if a["username"] == name)
    params = {
        "id": account["id"],
        "revision": account["revision"],
        "action": action,
        "changes": changes or {},
    }
    preview = service.call("preview_account_change", params)
    account = service.call(
        "execute_account_change", dict(params, token=preview["token"])
    )
    return account


def login():
    return subprocess.run(
        [
            "ssh",
            "-i",
            str(key),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={base / 'known_hosts'}",
            name + "@127.0.0.1",
            "true",
        ],
        capture_output=True,
        text=True,
    ).returncode


try:
    assert login() == 0
    today = utcnow().date().isoformat()
    change("update", {"expires_on": today})
    assert (
        account["status"] == "expired"
        and account["expires_effective_at"] == today + "T00:00:00+00:00"
    ), account
    assert login() != 0
    change("update", {"expires_on": None})
    assert account["status"] == "active" and account["expires_effective_at"] is None
    assert login() == 0
    change("disable")
    assert account["expires_effective_at"] is None
    print(
        json.dumps(
            {
                "account": name,
                "checks": [
                    "key_only_creation_SSH",
                    "today_expiry_blocks_SSH",
                    "effective_expiry_UTC",
                    "cancel_expiry_restores_SSH",
                    "disable_does_not_invent_1970_expiry",
                ],
            }
        )
    )
finally:
    change("delete")
