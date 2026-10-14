"""Quota checks on disposable loop images only; never formats host disks."""

import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess

from gpupm.agent.storage import native_quota

assert os.geteuid() == 0
base = Path("/var/lib/gpupm-qa")
assert base.is_dir() and base.stat().st_uid == 0
account = next(a for a in pwd.getpwall() if a.pw_name.startswith("gpupmqa_"))
results = []
for kind in ("ext4", "xfs"):
    suffix = secrets.token_hex(3)
    image = base / f"{kind}-{suffix}.img"
    mount = base / f"{kind}-{suffix}"
    with image.open("xb") as file:
        file.truncate(512 * 1024 * 1024)
    mount.mkdir(mode=0o755)
    if kind == "ext4":
        subprocess.run(
            ["mkfs.ext4", "-q", "-O", "quota", "-E", "quotatype=usrquota", str(image)],
            check=True,
        )
        options = "loop,usrquota"
    else:
        subprocess.run(["mkfs.xfs", "-q", str(image)], check=True)
        options = "loop,uquota"
    subprocess.run(["mount", "-o", options, str(image), str(mount)], check=True)
    try:
        device = json.loads(
            subprocess.check_output(
                ["findmnt", "-J", "-o", "SOURCE", "--target", str(mount)], text=True
            )
        )["filesystems"][0]["source"]
        assert device.startswith("/dev/loop")
        work = mount / "personal"
        work.mkdir()
        os.chown(work, account.pw_uid, account.pw_gid)
        limits = {
            "soft_bytes": 512 * 1024,
            "hard_bytes": 1024 * 1024,
            "soft_inodes": 10,
            "hard_inodes": 20,
            "grace_seconds": 120,
        }
        actual = native_quota(device, account.pw_uid, limits)
        assert (
            actual["hard_bytes"] == limits["hard_bytes"] and actual["hard_inodes"] == 20
        )
        command = [
            "runuser",
            "-u",
            account.pw_name,
            "--",
            "python3",
            "-c",
            f"from pathlib import Path; Path({str(work / 'large')!r}).write_bytes(b'x'*(2*1024*1024))",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode != 0 and "Disk quota exceeded" in result.stderr, (
            result.stderr
        )
        subprocess.run(
            [
                "runuser",
                "-u",
                account.pw_name,
                "--",
                "python3",
                "-c",
                f"from pathlib import Path; Path({str(work / 'large')!r}).write_bytes(b'x'*(768*1024))",
            ],
            check=True,
        )
        os.sync()
        actual = native_quota(device, account.pw_uid, limits)
        print(json.dumps({"filesystem":kind,"current_quota":actual}))
        import time

        assert (
            actual["byte_grace_expires_at"]
            and 100 <= actual["byte_grace_expires_at"] - time.time() <= 120
        )
        inode_limits = dict(limits, hard_inodes=3, soft_inodes=2)
        native_quota(device, account.pw_uid, inode_limits)
        inode_result = subprocess.run(
            [
                "runuser",
                "-u",
                account.pw_name,
                "--",
                "python3",
                "-c",
                f"from pathlib import Path; [Path({str(work)!r},str(i)).touch() for i in range(10)]",
            ],
            capture_output=True,
            text=True,
        )
        assert (
            inode_result.returncode != 0
            and "Disk quota exceeded" in inode_result.stderr
        ), inode_result.stderr
        results.append(
            {
                "filesystem": kind,
                "device": device,
                "readback": True,
                "hard_limit_enforced": True,
                "inode_limit_enforced": True,
                "current_overage_grace_verified": True,
            }
        )
    finally:
        subprocess.run(["umount", str(mount)], check=True)
print(json.dumps(results))
