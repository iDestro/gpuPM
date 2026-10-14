"""Disposable real SSH/ACL fixtures confined to gpupm QA paths."""

import json
import os
from pathlib import Path
import secrets
import subprocess
from gpupm.agent.host import AgentService

assert os.geteuid() == 0
base = Path("/var/lib/gpupm-qa")
assert base.stat().st_uid == 0
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
suffix = secrets.token_hex(3)
key = base / f"key-{suffix}"
subprocess.run(
    ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True
)
password = secrets.token_urlsafe(24) + "9!Ab"
accounts = []
for role in ("rw", "ro", "other"):
    name = f"gpupmqa_{role}{suffix}"
    accounts.append(
        service.call(
            "execute_account_change",
            {
                "action": "create",
                "changes": {
                    "username": name,
                    "password": password,
                    "public_keys": [key.with_suffix(".pub").read_text().strip()],
                    "require_password_change": False,
                },
            },
        )
    )


def change(account, action, changes=None):
    current = next(a for a in service.call("list_accounts") if a["id"] == account["id"])
    changes = changes or {}
    params = {
        "id": current["id"],
        "revision": current["revision"],
        "action": action,
        "changes": {k: v for k, v in changes.items() if k != "password"},
    }
    token = service.call("preview_account_change", params)["token"]
    return service.call(
        "execute_account_change", dict(params, changes=changes, token=token)
    )


common = [
    "ssh",
    "-o",
    "ConnectTimeout=5",
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    f"UserKnownHostsFile={base / 'known_hosts'}",
    "-o",
    "LogLevel=ERROR",
]
askpass = base / "askpass.py"
askpass.write_text(
    '#!/usr/bin/python3\nimport os\nprint(os.environ["GPUPM_QA_PASSWORD"])\n'
)
askpass.chmod(0o700)
try:
    name = accounts[0]["username"]
    public = subprocess.run(
        common + ["-i", str(key), "-o", "BatchMode=yes", name + "@127.0.0.1", "id -un"],
        capture_output=True,
        text=True,
    )
    assert public.returncode == 0 and public.stdout.strip() == name, public.stderr
    mask = subprocess.run(
        common + ["-i", str(key), "-o", "BatchMode=yes", name + "@127.0.0.1", "umask"],
        capture_output=True,
        text=True,
    )
    assert mask.returncode == 0 and mask.stdout.strip() in ("0077", "077"), mask.stdout
    private_file = Path(accounts[0]["data_dir"]) / "isolation.txt"
    private_file.write_text("private")
    os.chown(private_file, accounts[0]["uid"], accounts[0]["gid"])
    change(accounts[1], "update", {"groups": [name]})
    isolation = subprocess.run(
        ["runuser", "-u", accounts[1]["username"], "--", "cat", str(private_file)],
        capture_output=True,
        text=True,
    )
    assert isolation.returncode != 0
    env = dict(
        os.environ,
        GPUPM_QA_PASSWORD=password,
        SSH_ASKPASS=str(askpass),
        SSH_ASKPASS_REQUIRE="force",
        DISPLAY=":999",
    )
    pwdlogin = subprocess.run(
        common
        + [
            "-o",
            "PreferredAuthentications=password",
            "-o",
            "PubkeyAuthentication=no",
            name + "@127.0.0.1",
            "id -un",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        start_new_session=True,
    )
    assert pwdlogin.returncode == 0 and pwdlogin.stdout.strip() == name, pwdlogin.stderr
    change(accounts[0], "disable")
    blocked = subprocess.run(
        common + ["-i", str(key), "-o", "BatchMode=yes", name + "@127.0.0.1", "true"],
        capture_output=True,
        text=True,
    )
    assert blocked.returncode != 0
    disabled_password = subprocess.run(
        common
        + [
            "-o",
            "PreferredAuthentications=password",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=1",
            name + "@127.0.0.1",
            "true",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        start_new_session=True,
    )
    assert disabled_password.returncode != 0
    change(accounts[0], "enable")
    replacement = secrets.token_urlsafe(24) + "3!Xx"
    change(
        accounts[0],
        "update",
        {"password": replacement, "require_password_change": False},
    )
    old_password = subprocess.run(
        common
        + [
            "-o",
            "PreferredAuthentications=password",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=1",
            name + "@127.0.0.1",
            "true",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        start_new_session=True,
    )
    assert old_password.returncode != 0
    change(accounts[0], "update", {"public_keys": []})
    old_key = subprocess.run(
        common + ["-i", str(key), "-o", "BatchMode=yes", name + "@127.0.0.1", "true"],
        capture_output=True,
        text=True,
    )
    assert old_key.returncode != 0
    groups = []
    for role, index in [("rw", 0), ("ro", 1)]:
        groupname = f"gpupmqa_{role}_{suffix}"
        groups.append(
            service.call(
                "execute_group_change",
                {
                    "action": "create",
                    "changes": {
                        "name": groupname,
                        "members": [accounts[index]["username"]],
                    },
                },
            )
        )
    changes = {
        "name": "project_" + suffix,
        "reader_group": groups[1]["name"],
        "writer_group": groups[0]["name"],
    }
    preview = service.call("preview_share_change", {"changes": changes})
    share = service.call(
        "execute_share_change", {"changes": changes, "token": preview["token"]}
    )
    target = Path(share["path"]) / "test.txt"
    writer = subprocess.run(
        [
            "runuser",
            "-u",
            accounts[0]["username"],
            "--",
            "python3",
            "-c",
            f'from pathlib import Path; Path({str(target)!r}).write_text("shared")',
        ],
        capture_output=True,
        text=True,
    )
    assert writer.returncode == 0, writer.stderr
    reader = subprocess.run(
        ["runuser", "-u", accounts[1]["username"], "--", "cat", str(target)],
        capture_output=True,
        text=True,
    )
    assert reader.returncode == 0 and reader.stdout == "shared", reader.stderr
    denied = subprocess.run(
        ["runuser", "-u", accounts[1]["username"], "--", "touch", str(target)],
        capture_output=True,
        text=True,
    )
    assert denied.returncode != 0
    private = subprocess.run(
        ["runuser", "-u", accounts[2]["username"], "--", "cat", str(target)],
        capture_output=True,
        text=True,
    )
    assert private.returncode != 0
    print(
        json.dumps(
            {
                "checks": [
                    "SSH_publickey",
                    "SSH_password",
                    "SSH_umask_077",
                    "same_group_private_data_denied",
                    "disable_blocks_SSH",
                    "disable_blocks_password",
                    "password_reset_old_password_denied",
                    "removed_key_denied",
                    "shared_writer",
                    "shared_reader",
                    "reader_write_denied",
                    "outsider_denied",
                ],
                "accounts": [a["username"] for a in accounts],
                "share": share["path"],
            }
        )
    )
finally:
    for account in accounts:
        change(account, "delete")
