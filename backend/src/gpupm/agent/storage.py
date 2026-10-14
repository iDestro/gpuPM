import ctypes
import errno
import grp
import os
import re
import stat
import shutil
from pathlib import Path

from gpupm.agent.accounts import open_directory, secure_directory
from gpupm.domain.rules import utcnow, validate_name
from gpupm.errors import DomainError


class Dqblk(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "bhardlimit",
            "bsoftlimit",
            "curspace",
            "ihardlimit",
            "isoftlimit",
            "curinodes",
            "btime",
            "itime",
        )
    ] + [("valid", ctypes.c_uint32)]


def quota_blocks(value):
    return (value + 1023) // 1024


def validate_quota(policy):
    allowed = {"filesystem_id", "soft_bytes", "hard_bytes", "soft_inodes", "hard_inodes", "grace_seconds"}
    if set(policy) - allowed:
        raise DomainError("invalid_quota", "unknown quota fields", 422)
    for field in allowed - {"filesystem_id"}:
        value = policy.get(field, 0)
        if type(value) is not int or value < 0 or value > 2**63 - 1:
            raise DomainError("invalid_quota", "quota values must be nonnegative native-width integers", 422)
    for soft, hard in [("soft_bytes", "hard_bytes"), ("soft_inodes", "hard_inodes")]:
        if policy.get(hard, 0) and policy.get(soft, 0) > policy[hard]:
            raise DomainError("invalid_quota", "soft limit exceeds hard limit", 422)


def native_quota(device, uid, policy=None):
    lib = ctypes.CDLL(None, use_errno=True)
    if not hasattr(lib, "quotactl"):
        raise DomainError("quota_unavailable", "Linux quotactl required", 503)
    lib.quotactl.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
    values = Dqblk()
    command = 0x800007
    if policy is not None:
        validate_quota(policy)
        command = 0x800008
        values.bsoftlimit = quota_blocks(policy.get("soft_bytes", 0))
        values.bhardlimit = quota_blocks(policy.get("hard_bytes", 0))
        values.isoftlimit = policy.get("soft_inodes", 0)
        values.ihardlimit = policy.get("hard_inodes", 0)
        values.valid = 1 | 4
        if "grace_seconds" in policy:
            # Per-user grace timestamps use native epoch seconds, only if current usage exceeds soft limits.
            current = native_quota(device, uid)
            seconds = int(utcnow().timestamp()) + policy["grace_seconds"]
            values.btime = (
                seconds if values.bsoftlimit and current["used_bytes"] > values.bsoftlimit * 1024 else 0
            )
            values.itime = seconds if values.isoftlimit and current["used_inodes"] > values.isoftlimit else 0
            values.valid |= 16 | 32
    result = lib.quotactl(
        ctypes.c_int((command << 8) & 0xFFFFFFFF), device.encode(), uid, ctypes.byref(values)
    )
    if result:
        code = ctypes.get_errno()
        if code in {errno.ESRCH, errno.ENOENT}:
            name = "quota_disabled"
            message = "user quotas are disabled; administrator must enable usrquota/uquota using the host filesystem procedure"
        elif code in {errno.ENOSYS, errno.EOPNOTSUPP, errno.EINVAL}:
            name = "quota_unsupported"
            message = (
                "filesystem or kernel does not support native user quotas; ext4/XFS user quotas required"
            )
        else:
            name = "quota_unavailable"
            message = f"quotactl failed errno {code}; root access and enabled filesystem user quotas required"
        raise DomainError(name, message, 422)
    if policy is not None:
        return native_quota(device, uid)
    return dict(
        soft_bytes=values.bsoftlimit * 1024,
        hard_bytes=values.bhardlimit * 1024,
        soft_inodes=values.isoftlimit,
        hard_inodes=values.ihardlimit,
        used_bytes=values.curspace,
        used_inodes=values.curinodes,
        byte_grace_expires_at=values.btime or None,
        inode_grace_expires_at=values.itime or None,
        status="applied",
        error=None,
        grace_seconds=None,
        grace_scope="current overage timestamps; future overages use filesystem-wide native defaults",
    )


def mount_unescape(value):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), value)


def filesystems():
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return []
    result = []
    for line in lines:
        parts = line.split()
        separator = parts.index("-")
        path = mount_unescape(parts[4])
        fstype = parts[separator + 1]
        device = mount_unescape(parts[separator + 2])
        if fstype not in {"ext4", "xfs"}:
            continue
        try:
            usage = os.statvfs(path)
        except OSError:
            continue
        options = ",".join([parts[5], parts[separator + 3]])
        enabled = bool(set(options.split(",")) & {"usrquota", "uquota", "quota"})
        result.append(
            dict(
                id=path,
                path=path,
                device=device,
                fstype=fstype,
                total=usage.f_blocks * usage.f_frsize,
                available=usage.f_bavail * usage.f_frsize,
                total_inodes=usage.f_files,
                available_inodes=usage.f_favail,
                quota_supported=True,
                quota_enabled=enabled,
                error=None
                if enabled
                else "Enable native user quotas with the filesystem administrator; no automatic remount/format is performed",
            )
        )
    return result


def directory_usage(path):
    total = 0
    count = 0
    errors = 0
    try:
        root = open_directory(path)
    except DomainError as exc:
        return dict(bytes=None, files=None, status=exc.code)

    def walk(fd):
        nonlocal total, count, errors
        for name in os.listdir(fd):
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                count += 1
                if stat.S_ISREG(info.st_mode):
                    total += info.st_size
                elif stat.S_ISDIR(info.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        if os.fstat(child).st_dev == os.fstat(root).st_dev:
                            walk(child)
                    finally:
                        os.close(child)
            except OSError:
                errors += 1

    try:
        walk(root)
    finally:
        os.close(root)
    return dict(bytes=total, files=count, status="partial" if errors else "available")


def filesystem_for(path, mounts):
    candidates = [
        fs for fs in mounts if Path(path) == Path(fs["path"]) or Path(fs["path"]) in Path(path).parents
    ]
    return max(candidates, key=lambda fs: len(fs["path"])) if candidates else None


def storage_alerts(mounts, users, shares, quotas, warning, critical, observations=None):
    alerts = []
    by_id = {fs["id"]: fs for fs in mounts}

    def add(scope, target, metric, used, limit, label, basis):
        if used is None or not limit or limit < 0:
            return
        percentage = used / limit * 100
        if observations is not None:
            observations.add(f"{scope}:{target}:{metric}")
        severity = "critical" if percentage >= critical else "warning" if percentage >= warning else None
        if severity:
            alerts.append(
                dict(
                    id=f"{scope}:{target}:{metric}",
                    scope=scope,
                    target=str(target),
                    metric=metric,
                    severity=severity,
                    percent=round(percentage, 2),
                    used=used,
                    limit=limit,
                    basis=basis,
                    message=f"{label}: {metric} {percentage:.1f}% ({severity})",
                )
            )

    for fs in mounts:
        if fs.get("available") is not None:
            add(
                "filesystem",
                fs["id"],
                "bytes",
                fs["total"] - fs["available"],
                fs["total"],
                fs["path"],
                "filesystem capacity",
            )
        if fs.get("available_inodes") is not None:
            add(
                "filesystem",
                fs["id"],
                "inodes",
                fs.get("total_inodes", 0) - fs["available_inodes"],
                fs.get("total_inodes"),
                fs["path"],
                "filesystem inode capacity",
            )
    for user in users:
        for field in ("home", "data"):
            fs = by_id.get(user.get(field + "_filesystem_id"))
            if fs:
                add(
                    "user_directory",
                    user["account_id"] + ":" + field,
                    "bytes",
                    user.get(field + "_bytes"),
                    fs["total"],
                    user["username"] + " " + field,
                    "share of filesystem capacity; no per-directory hard limit",
                )
                add(
                    "user_directory",
                    user["account_id"] + ":" + field,
                    "inodes",
                    user.get(field + "_files"),
                    fs.get("total_inodes"),
                    user["username"] + " " + field,
                    "directory entry count / filesystem inode capacity; hard links may duplicate counts",
                )
    for quota in quotas:
        if quota.get("status") != "applied":
            continue
        for metric in ("bytes", "inodes"):
            limit = quota.get("hard_" + metric) or quota.get("soft_" + metric)
            if not limit and quota.get("used_" + metric) is not None and observations is not None:
                observations.add(f"user_quota:{quota['account_id']}:{quota['filesystem_id']}:{metric}")
            add(
                "user_quota",
                quota["account_id"] + ":" + quota["filesystem_id"],
                metric,
                quota.get("used_" + metric),
                limit,
                quota["account_id"] + " " + quota["filesystem_id"],
                "native user quota hard limit or soft limit when unlimited hard",
            )
    for share in shares:
        fs = filesystem_for(share["path"], mounts)
        if fs:
            add(
                "share",
                share["id"],
                "bytes",
                share.get("usage_bytes"),
                fs["total"],
                share["name"],
                "share of filesystem capacity; no per-share hard limit",
            )
            add(
                "share",
                share["id"],
                "inodes",
                share.get("usage_files"),
                fs.get("total_inodes"),
                share["name"],
                "directory entry count / filesystem inode capacity; hard links may duplicate counts",
            )
    return alerts


class Storage:
    def __init__(self, service):
        self.service = service

    def filesystem(self, ident):
        fs = next((f for f in filesystems() if f["id"] == ident), None)
        if not fs:
            raise DomainError("quota_unsupported", "quota target must be a discovered ext4/XFS mount", 422)
        return fs

    def quotas(self, state, account):
        result = []
        for fs in filesystems():
            try:
                quota = native_quota(fs["device"], account["uid"])
            except DomainError as exc:
                quota = dict(status=exc.code, error=exc.message, used_bytes=None, used_inodes=None)
            result.append(dict(filesystem_id=fs["id"], **quota))
        return result

    def snapshot(self, state):
        users = []
        mounts = filesystems()
        quotas = []
        for account in self.service.accounts.list(state):
            if not account["managed"]:
                continue
            home = directory_usage(account["home"])
            data = directory_usage(account["data_dir"])
            users.append(
                dict(
                    account_id=account["id"],
                    username=account["username"],
                    home_bytes=home["bytes"],
                    data_bytes=data["bytes"],
                    home_files=home["files"],
                    data_files=data["files"],
                    home_filesystem_id=(filesystem_for(account["home"], mounts) or {}).get("id"),
                    data_filesystem_id=(filesystem_for(account["data_dir"], mounts) or {}).get("id"),
                    files=(home["files"] + data["files"])
                    if home["files"] is not None and data["files"] is not None
                    else None,
                    status="available" if home["status"] == data["status"] == "available" else "partial",
                    collected_at=utcnow().isoformat(),
                )
            )
            for fs in mounts:
                try:
                    quota = native_quota(fs["device"], account["uid"])
                except DomainError as exc:
                    quota = dict(status=exc.code, error=exc.message)
                quotas.append(dict(account_id=account["id"], filesystem_id=fs["id"], **quota))
        for share in state["shares"]:
            usage = directory_usage(share["path"])
            share["usage_bytes"] = usage["bytes"]
            share["usage_files"] = usage["files"]
            share["usage_status"] = usage["status"]
        warning = state["settings"].get("warning_percent", self.service.config.get("warning_percent", 80))
        critical = state["settings"].get("critical_percent", self.service.config.get("critical_percent", 90))
        observations = set()
        alerts = storage_alerts(mounts, users, state["shares"], quotas, warning, critical, observations)
        previous = state.get("storage_alert_states", {})
        current = {a["id"]: a for a in alerts}
        for ident, alert in current.items():
            if (
                previous.get(ident, {}).get("severity") != alert["severity"]
                or previous.get(ident, {}).get("status") == "unavailable"
            ):
                self.service.event(
                    state, {}, "storage.alert", ident, previous.get(ident), alert, alert["severity"]
                )
        for ident, alert in previous.items():
            if ident not in current:
                if ident in observations:
                    self.service.event(state, {}, "storage.alert", ident, alert, None, "resolved")
                else:
                    unknown = dict(
                        alert,
                        status="unavailable",
                        message=alert["message"]
                        if alert.get("status") == "unavailable"
                        else alert["message"] + "; current measurement unavailable",
                    )
                    if alert.get("status") != "unavailable":
                        self.service.event(state, {}, "storage.alert", ident, alert, unknown, "unavailable")
                    current[ident] = unknown
                    alerts.append(unknown)
        state["storage_alert_states"] = current
        return dict(
            capabilities={
                "acl": {
                    "status": ("verified" if state.get("acl_verified_at") else "tools_present_unverified")
                    if shutil.which("setfacl") and shutil.which("getfacl")
                    else "unavailable",
                    "verified_at": state.get("acl_verified_at"),
                    "message": (
                        "Share directory ACL applied and numeric readback verified"
                        if state.get("acl_verified_at")
                        else "ACL tools installed; native ACL verified only by an actual share operation"
                    )
                    if shutil.which("setfacl") and shutil.which("getfacl")
                    else "Install Ubuntu acl package and verify native filesystem ACL support",
                }
            },
            filesystems=mounts,
            users=users,
            quotas=quotas,
            shares=state["shares"],
            alerts=alerts,
            collected_at=utcnow().isoformat(),
            source="host",
        )

    def dispatch(self, state, method, p):
        service = self.service
        if method == "list_shares":
            return state["shares"]
        if method == "storage_snapshot":
            interval = state["settings"].get(
                "storage_scan_interval_seconds", service.config.get("storage_scan_interval_seconds", 900)
            )
            previous = state.get("storage")
            stale = (
                not previous
                or (
                    utcnow()
                    - __import__("gpupm.domain.rules", fromlist=["parse_time"]).parse_time(
                        previous["collected_at"]
                    )
                ).total_seconds()
                >= interval
            )
            if stale and (service.storage_worker is None or not service.storage_worker.is_alive()):
                import threading

                worker = threading.Thread(target=service.collect_storage, daemon=True)
                service.storage_worker = worker
                worker.start()
            if previous:
                return dict(previous, stale=stale)
            return dict(
                filesystems=[],
                users=[],
                shares=state["shares"],
                quotas=[],
                alerts=[],
                collected_at=None,
                source="host",
                status="pending",
                stale=True,
                capabilities={
                    "acl": dict(
                        status="tools_present_unverified"
                        if shutil.which("setfacl") and shutil.which("getfacl")
                        else "unavailable",
                        message="Storage background collection pending; native ACL not yet verified",
                    )
                },
            )
        if method in {"get_quotas", "preview_quota", "apply_quota"}:
            account = service.accounts.find(state, p["id"])
            if method == "get_quotas":
                return self.quotas(state, account)
            service.accounts.writable(state, p["id"])
            policy = p["policy"]
            validate_quota(policy)
            fs = self.filesystem(policy["filesystem_id"])
            current = native_quota(fs["device"], account["uid"])
            if method == "preview_quota":
                preview = service.preview(state, "quota", account, "update", policy)
                preview.update(
                    grace_scope="Current overage expiry only; future grace remains the filesystem default. No global quota grace changes.",
                    current=current,
                    proposed=policy,
                    impact=dict(
                        below_usage=bool(
                            policy.get("hard_bytes")
                            and policy["hard_bytes"] < current["used_bytes"]
                            or policy.get("hard_inodes")
                            and policy["hard_inodes"] < current["used_inodes"]
                        )
                    ),
                )
                return preview
            service.checked(state, p, "quota", account, "update", policy)
            result = native_quota(fs["device"], account["uid"], policy)
            expected = dict(
                soft_bytes=quota_blocks(policy.get("soft_bytes", 0)) * 1024,
                hard_bytes=quota_blocks(policy.get("hard_bytes", 0)) * 1024,
                soft_inodes=policy.get("soft_inodes", 0),
                hard_inodes=policy.get("hard_inodes", 0),
            )
            if any(result[k] != v for k, v in expected.items()):
                raise DomainError(
                    "quota_readback_mismatch",
                    "native quota readback differs; inspect host limits before retry",
                    503,
                )
            result["filesystem_id"] = fs["id"]
            state["quotas"][account["id"]] = result
            state["previews"].pop(p["token"])
            service.event(state, p, "quota.update", account["id"], current, result)
            return result
        if method in {"preview_share_change", "execute_share_change"}:
            changes = p["changes"]
            if set(changes) - {"name", "reader_group", "writer_group", "notes"}:
                raise DomainError("invalid_share", "arbitrary share paths prohibited", 422)
            existing = service.find(state, "shares", p["id"]) if p.get("id") else None
            merged = dict(existing or {})
            merged.update(changes)
            name = validate_name(merged["name"])
            changed_groups = [
                merged[field]
                for field in ("reader_group", "writer_group")
                if not existing or merged[field] != existing[field]
            ]
            if changed_groups:
                service.accounts.validate_permission_groups(
                    state, [merged["reader_group"], merged["writer_group"]]
                )
            if merged["reader_group"] == merged["writer_group"]:
                raise DomainError("invalid_share", "reader and writer groups must differ", 422)
            if existing and name != existing["name"]:
                raise DomainError("share_rename_forbidden", "share paths are immutable", 422)
            if not existing and any(s["name"] == name for s in state["shares"]):
                raise DomainError("share_exists", "share exists")
            item = existing or dict(id="create:" + name, revision=0)
            if existing:
                service.revision(existing, p)
            action = "update" if existing else "create"
            if method == "preview_share_change":
                result = service.preview(state, "share", item, action, changes)
                result["path"] = str(Path(service.config.get("share_base", "/data/shared")) / name)
                result["impact"] = (
                    "root directory access and default ACL for new descendants; existing nested ACLs retained"
                )
                return result
            service.checked(state, p, "share", item, action, changes)
            if existing and not changed_groups:
                before = dict(existing)
                existing.update(changes)
                existing["revision"] += 1
                state["previews"].pop(p["token"])
                service.event(state, p, "share.update", existing["id"], before, existing)
                return existing
            base = secure_directory(service.config.get("share_base", "/data/shared"))
            parent = open_directory(base)
            try:
                if not existing:
                    try:
                        os.mkdir(name, 0o2770, dir_fd=parent)
                    except FileExistsError as exc:
                        raise DomainError("path_conflict", "share path already exists") from exc
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    if os.fstat(fd).st_uid != 0:
                        raise DomainError("unsafe_share", "share must remain root-owned", 403)
                    os.fchown(fd, 0, grp.getgrnam(merged["writer_group"]).gr_gid)
                    os.fchmod(fd, 0o2770)
                    # Descriptor path prevents ACL command from resolving a swapped share name.
                    acl = f"u::rwx,g::rwx,g:{merged['reader_group']}:r-x,g:{merged['writer_group']}:rwx,m::rwx,o::---,d:u::rwx,d:g::rwx,d:g:{merged['reader_group']}:r-x,d:g:{merged['writer_group']}:rwx,d:m::rwx,d:o::---"
                    # /proc/self/fd requires fd inheritance; invoke through pinned directory cwd instead.
                    path = f"/proc/{os.getpid()}/fd/{fd}"
                    service.accounts.run(["setfacl", "--set", acl, "--", path])
                    actual = service.accounts.run(["getfacl", "--numeric", "--absolute-names", "--", path])
                    if not all(
                        f"group:{grp.getgrnam(merged[g]).gr_gid}:" in actual
                        for g in ("reader_group", "writer_group")
                    ):
                        raise DomainError("acl_readback_mismatch", "share ACL readback failed", 503)
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
            state["acl_verified_at"] = utcnow().isoformat()
            if state.get("storage"):
                state["storage"].setdefault("capabilities", {})["acl"] = {
                    "status": "verified",
                    "message": "Share directory ACL applied and numeric readback verified",
                    "verified_at": state["acl_verified_at"],
                }
            if existing:
                before = dict(existing)
                existing.update(changes)
                existing["revision"] += 1
                result = existing
            else:
                from uuid import uuid4

                before = None
                result = dict(
                    id=str(uuid4()),
                    name=name,
                    path=str(base / name),
                    reader_group=merged["reader_group"],
                    writer_group=merged["writer_group"],
                    notes=merged.get("notes", ""),
                    status="active",
                    revision=1,
                    usage_bytes=0,
                )
                state["shares"].append(result)
            state["previews"].pop(p["token"])
            service.event(state, p, "share." + action, result["id"], before, result)
            return result
        raise DomainError("unsupported", "unsupported storage action", 422)
