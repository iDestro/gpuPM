"""Explicit root QA run; uses only gpupmqa_* accounts and /var/lib/gpupm-qa."""

import json
import os
import pwd
import secrets
import subprocess
from pathlib import Path

from gpupm.agent.host import AgentService
from gpupm.agent.processes import collect

assert os.geteuid() == 0
base = Path("/var/lib/gpupm-qa")
assert base.is_dir() and base.stat().st_uid == 0
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
for old in service.call("list_accounts"):
    if old["username"].startswith("gpupmqa_") and old["managed"] and not old["deleted_at"]:
        params = {"id":old["id"],"revision":old["revision"],"action":"delete","changes":{}}
        preview = service.call("preview_account_change",params)
        service.call("execute_account_change",dict(params,token=preview["token"]))
name = "gpupmqa_" + secrets.token_hex(3)
password = secrets.token_urlsafe(24) + "9!aA"
account = service.call(
    "execute_account_change",
    {
        "action": "create",
        "changes": {
            "username": name,
            "password": password,
            "require_password_change": False,
        },
    },
)
uid, gid = account["uid"], account["gid"]
home, data = Path(account["home"]), Path(account["data_dir"])
assert pwd.getpwnam(name).pw_shell == "/bin/bash"
for path in (home, data):
    assert path.stat().st_uid == uid and path.stat().st_mode & 0o777 == 0o700
payload = data / "retained.txt"
payload.write_text("retain after soft delete")
os.chown(payload, uid, gid)
before = payload.stat()


def change(action, changes=None):
    global account
    account = next(a for a in service.call("list_accounts") if a["id"] == str(uid))
    params = {
        "id": str(uid),
        "revision": account["revision"],
        "action": action,
        "changes": changes or {},
    }
    preview = service.call("preview_account_change", dict(params, changes={k:v for k,v in params["changes"].items() if k != "password"}))
    account = service.call(
        "execute_account_change", dict(params, token=preview["token"])
    )
    return account


child = subprocess.Popen(["runuser", "-u", name, "--", "sleep", "60"])
try:
    change("disable")
    assert pwd.getpwnam(name).pw_shell == "/usr/sbin/nologin"
    change("delete")
    assert child.poll() is None
    assert payload.read_text() == "retain after soft delete"
    assert (payload.stat().st_uid, payload.stat().st_mode) == (
        before.st_uid,
        before.st_mode,
    )
    change("restore")
    assert account["disabled"] and pwd.getpwnam(name).pw_shell == "/usr/sbin/nologin"
    change("enable")
    assert pwd.getpwnam(name).pw_shell == "/bin/bash"
finally:
    child.terminate()
    child.wait(timeout=5)
change(
    "update",
    {"password": secrets.token_urlsafe(24) + "4!Bb", "require_password_change": True},
)
shadow = (
    subprocess.check_output(["getent", "shadow", name], text=True).strip().split(":")
)
assert shadow[2] == "0"
change("delete")
gpus, processes, errors = collect()
assert gpus and any(g["uuid"] for g in gpus)
print(
    json.dumps(
        {
            "account": name,
            "uid": uid,
            "soft_deleted": True,
            "retained_file": str(payload),
            "checks": [
                "bash",
                "private_directories",
                "password_quality",
                "disable",
                "soft_delete",
                "restore_independent_restrictions",
                "live_process_retained",
                "password_change",
                "NVML",
            ],
            "gpu_count": len(gpus),
            "gpu_task_processes": sum(bool(p["gpu_memory"]) for p in processes),
            "errors": errors,
        }
    )
)
