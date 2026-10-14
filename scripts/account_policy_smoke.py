"""Native primary-group, idle rename and external-restriction QA."""

import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
from gpupm.agent.host import AgentService

assert os.geteuid() == 0
base = Path("/var/lib/gpupm-qa")
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
name = "gpupmqa_" + secrets.token_hex(3)
account = service.call(
    "execute_account_change",
    {
        "action": "create",
        "changes": {
            "username": name,
            "password": secrets.token_urlsafe(24) + "8!Ab",
            "require_password_change": False,
        },
    },
)
uid, gid = account["uid"], account["gid"]


def change(action, changes=None):
    global account
    current = next(a for a in service.call("list_accounts") if a["id"] == str(uid))
    changes = changes or {}
    params = {
        "id": str(uid),
        "revision": current["revision"],
        "action": action,
        "changes": {k: v for k, v in changes.items() if k != "password"},
    }
    preview = service.call("preview_account_change", params)
    assert "activity" in preview and "paths" in preview
    account = service.call(
        "execute_account_change", dict(params, changes=changes, token=preview["token"])
    )
    return account


try:
    homefile = Path(account["home"]) / "keep.txt"
    datafile = Path(account["data_dir"]) / "keep.txt"
    for path in (homefile, datafile):
        path.write_text("preserve")
        os.chown(path, uid, gid)
    groupname = "gpupmqa_grp_" + secrets.token_hex(3)
    group = service.call(
        "execute_group_change", {"action": "create", "changes": {"name": groupname}}
    )
    change("update", {"primary_group": groupname})
    assert pwd.getpwuid(uid).pw_gid == group["gid"]
    assert homefile.stat().st_gid == group["gid"] and datafile.stat().st_gid == gid
    lifecycle = account.get("lifecycle_id")
    newname = name + "_new"
    change("update", {"username": newname})
    assert pwd.getpwuid(uid).pw_name == newname
    assert account.get("lifecycle_id") == lifecycle
    assert Path(account["home"], "keep.txt").read_text() == "preserve"
    assert Path(account["data_dir"], "keep.txt").read_text() == "preserve"
    assert not homefile.exists() and not datafile.exists()
    subprocess.run(["passwd", "--lock", newname], check=True, capture_output=True)
    subprocess.run(
        [
            "usermod",
            "--shell",
            "/usr/sbin/nologin",
            "--expiredate",
            "2030-01-01",
            newname,
        ],
        check=True,
    )
    change("disable")
    change("enable")
    assert pwd.getpwuid(uid).pw_shell == "/usr/sbin/nologin"
    shadow = (
        subprocess.check_output(["getent", "shadow", newname], text=True)
        .strip()
        .split(":")
    )
    assert shadow[1].startswith("!") and shadow[7] != "1"
    change(
        "update",
        {
            "password": secrets.token_urlsafe(24) + "4!Xx",
            "require_password_change": False,
        },
    )
    shadow = (
        subprocess.check_output(["getent", "shadow", newname], text=True)
        .strip()
        .split(":")
    )
    assert (
        shadow[1].startswith("!") and pwd.getpwuid(uid).pw_shell == "/usr/sbin/nologin"
    )
    print(
        json.dumps(
            {
                "account": newname,
                "checks": [
                    "primary_group_native_home_GID",
                    "data_GID_retained",
                    "idle_rename_files",
                    "rename_lifecycle_preserved",
                    "external_lock_shell_expiry_preserved",
                    "password_reset_preserves_external_lock",
                ],
            }
        )
    )
finally:
    change("delete")
