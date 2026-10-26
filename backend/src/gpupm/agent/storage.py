import logging
import grp
import os
import re
import stat
import shutil
from pathlib import Path

from gpupm.agent.accounts import open_directory, secure_directory
from gpupm.domain.rules import utcnow, validate_name
from gpupm.errors import DomainError


def share_directory_identity(path):
    """Pin a registered directory's identity without following symlinks."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise DomainError("unsafe_path", "absolute registered share path required", 422)
    try:
        parent = open_directory(secure_directory(path.parent))
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                info = os.fstat(fd)
                if info.st_uid != 0:
                    raise DomainError("unsafe_share", "share must remain root-owned", 403)
                return dict(path=str(path), device=info.st_dev, inode=info.st_ino)
            finally:
                os.close(fd)
        finally:
            os.close(parent)
    except OSError as exc:
        raise DomainError("unsafe_path", "registered shared directory missing or unsafe", 409) from exc


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
        result.append(
            dict(
                id=path,
                path=path,
                device=device,
                fstype=fstype,
                mount_id=parts[0],
                total=usage.f_blocks * usage.f_frsize,
                available=usage.f_bavail * usage.f_frsize,
                total_inodes=usage.f_files,
                available_inodes=usage.f_favail,
            )
        )
    return result


def directory_usage(path):
    """Allocated 512-byte blocks, deduplicated per root without crossing devices."""
    total = 0
    errors = 0
    try:
        root = open_directory(path)
    except DomainError as exc:
        return dict(bytes=None, status=exc.code)

    root_device = os.fstat(root).st_dev
    seen = set()

    def count(info):
        nonlocal total
        identity = (info.st_dev, info.st_ino)
        if info.st_dev != root_device or identity in seen:
            return False
        seen.add(identity)
        total += info.st_blocks * 512
        return True

    def walk(fd):
        nonlocal errors
        if not count(os.fstat(fd)):
            return
        try:
            names = os.listdir(fd)
        except OSError:
            errors += 1
            return
        for name in names:
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if info.st_dev != root_device:
                    continue
                if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                    count(info)
                elif stat.S_ISDIR(info.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        walk(child)
                    finally:
                        os.close(child)
            except OSError:
                errors += 1

    try:
        walk(root)
    finally:
        os.close(root)
    return dict(bytes=total, status="partial" if errors else "available")


def filesystem_for(path, mounts):
    candidates = [
        fs for fs in mounts if Path(path) == Path(fs["path"]) or Path(fs["path"]) in Path(path).parents
    ]
    return max(candidates, key=lambda fs: len(fs["path"])) if candidates else None


def storage_alerts(mounts, users, shares, warning, critical, observations=None):
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
    return alerts


class Storage:
    def __init__(self, service):
        self.service = service

    def snapshot(self, state, scan_directories=False):
        cached = state.get("storage") or {}
        users = [] if scan_directories else cached.get("users", [])
        users = [{k: v for k, v in user.items() if k not in {"files", "home_files", "data_files"}} for user in users]
        for share in state["shares"]:
            share.pop("usage_files", None)
        mounts = filesystems()
        for account in (self.service.accounts.list(state) if scan_directories else []):
            if not account["managed"]:
                continue
            home = directory_usage(account["home"])
            data = directory_usage(account["data_dir"])
            users.append(
                dict(
                    account_id=account["id"],
                    username=account["username"],
                    account_status=account.get("status"),
                    deleted_at=account.get("deleted_at"),
                    home_bytes=home["bytes"],
                    data_bytes=data["bytes"],
                    home_filesystem_id=(filesystem_for(account["home"], mounts) or {}).get("id"),
                    data_filesystem_id=(filesystem_for(account["data_dir"], mounts) or {}).get("id"),
                    status="available" if home["status"] == data["status"] == "available" else "partial",
                    collected_at=utcnow().isoformat(),
                )
            )
        for share in (state["shares"] if scan_directories else []):
            usage = directory_usage(share["path"])
            share["usage_bytes"] = usage["bytes"]
            share["usage_status"] = usage["status"]
            share["collected_at"] = utcnow().isoformat()
        warning = state["settings"].get("warning_percent", self.service.config.get("warning_percent", 80))
        critical = state["settings"].get("critical_percent", self.service.config.get("critical_percent", 90))
        observations = set()
        alerts = storage_alerts(mounts, users, state["shares"], warning, critical, observations)
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
            if alert.get("metric") == "inodes" and alert.get("scope") != "filesystem":
                continue
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
        acl_needs_review = any(s.get("status") == "access_recheck_required" for s in state["shares"])
        return dict(
            capabilities={
                "acl": {
                    "status": ("requires_attention" if acl_needs_review else "verified" if state.get("acl_verified_at") else "tools_present_unverified")
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

            shares=state["shares"],
            alerts=alerts,
            collected_at=utcnow().isoformat(),
            source="host",
            directory_collected_at=utcnow().isoformat() if scan_directories else cached.get("directory_collected_at", cached.get("collected_at") if cached.get("users") else None),
        )

    def dispatch(self, state, method, p):
        service = self.service
        if method == "list_shares":
            from gpupm.agent.share_members import member_rows
            groups = service.accounts.groups(state)
            result = []
            for share in state["shares"]:
                row = dict(share, usage_stale=not share.get("collected_at"))
                try:
                    row["members"] = member_rows(share, groups)
                except DomainError:
                    row.update(members=None, membership_error="share_members_unavailable")
                result.append(row)
            return result
        if method == "refresh_storage":
            if service.storage_worker is None or not service.storage_worker.is_alive():
                import threading

                service.storage_scan_error = None

                def refresh():
                    try:
                        service.collect_storage(scan_directories=True)
                    except Exception:
                        logging.getLogger(__name__).exception("Directory usage collection failed")
                        service.storage_scan_error = "目录统计失败，请重试或检查服务器日志。"

                worker = threading.Thread(target=refresh, daemon=True)
                service.storage_worker = worker
                worker.start()
                service.event(state, p, "storage.refresh", "directories", None, None)
            return dict(scanning=True)
        if method == "storage_snapshot":
            snapshot = self.snapshot(state, scan_directories=False)
            return dict(snapshot, stale=False,
                        scanning=bool(service.storage_worker and service.storage_worker.is_alive()),
                        scan_error=getattr(service, "storage_scan_error", None))
        if method in {"preview_share_change", "execute_share_change"}:
            changes = p["changes"]
            if set(changes) - {"name", "reader_group", "writer_group", "notes", "members"}:
                raise DomainError("invalid_share", "arbitrary share paths prohibited", 422)
            existing = service.find(state, "shares", p["id"]) if p.get("id") else None
            merged = dict(existing or {})
            merged.update(changes)
            name = validate_name(merged["name"])
            member_groups = None
            member_scope = None
            if existing and existing.get("access_mode") == "members" and {"reader_group", "writer_group"} & changes.keys():
                raise DomainError("invalid_share", "Use member permissions for this directory", 422)
            if "members" in changes:
                from gpupm.agent.share_members import MemberGroups, member_rows, validate_members
                if {"reader_group", "writer_group"} & changes.keys():
                    raise DomainError("invalid_share", "Cannot mix member and group grants", 422)
                accounts = service.accounts.list(state)
                desired = validate_members(changes["members"], accounts)
                member_groups = MemberGroups(service, state, name)
                groups = service.accounts.groups(state)
                member_scope = dict(
                    groups=member_groups.scope(),
                    current=member_rows(existing, groups) if existing else [],
                    bindings=[{k:g.get(k) for k in ("name", "gid", "members", "primary_users")} for g in groups if existing and g["name"] in {existing["reader_group"], existing["writer_group"]}],
                    identities=[{k: a.get(k) for k in ("username", "uid", "revision", "lifecycle_id")} for a in accounts if a["username"] in {m["username"] for m in desired}],
                )
                merged.update(member_groups.names, members=desired, access_mode="members")
            changed_groups = [
                merged[field]
                for field in ("reader_group", "writer_group")
                if not existing or merged[field] != existing[field]
            ]
            if not member_groups and (changed_groups or existing and existing.get("status") == "access_recheck_required"):
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
            path = Path(existing["path"]) if existing else Path(service.config.get("share_base", "/data/shared")) / name
            path_scope = None
            if existing and (member_groups or changed_groups or existing.get("status") == "access_recheck_required"):
                if path.name != name:
                    raise DomainError("unsafe_path", "registered shared directory name mismatch", 409)
                path_scope = share_directory_identity(path)
            if method == "preview_share_change":
                result = service.preview(state, "share", item, action, changes)
                result["path"] = str(path)
                if path_scope:
                    state["previews"][result["token"]]["path_scope"] = path_scope
                fields = ("name", "path", "members", "notes") if member_groups else ("name", "path", "reader_group", "writer_group", "notes")
                result["current"] = {key: existing.get(key) for key in fields} if existing else None
                result["proposed"] = {
                    key: merged.get(key, "") for key in fields
                } | {"path": result["path"]}
                if member_groups:
                    state["previews"][result["token"]]["member_scope"] = member_scope
                    if existing:
                        result["current"]["members"] = member_scope["current"]
                    result["migration"] = bool(existing and existing.get("access_mode") != "members")
                result["impact"] = (
                    "root directory access and default ACL for new descendants; existing nested ACLs retained"
                )
                return result
            checked = service.checked(state, p, "share", item, action, changes)
            if path_scope and checked.get("path_scope") != path_scope:
                raise DomainError("scope_changed", "Shared directory identity changed since preview", 409)
            if member_groups and checked.get("member_scope") != member_scope:
                raise DomainError("scope_changed", "Shared directory membership changed since preview", 409)
            if existing and not member_groups and not changed_groups and existing.get("status") != "access_recheck_required":
                before = dict(existing)
                existing.update(changes)
                existing["revision"] += 1
                state["previews"].pop(p["token"])
                service.event(state, p, "share.update", existing["id"], before, existing)
                return existing
            base = secure_directory(path.parent)
            service.accounts.assert_devices(
                secure_directory(service.config.get("home_base", "/home")),
                secure_directory(service.config.get("data_base", "/data")),
            )
            parent = open_directory(base)
            created = None
            membership_touched = False
            try:
                if not existing:
                    try:
                        os.mkdir(name, 0o700, dir_fd=parent)
                        created = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    except FileExistsError as exc:
                        raise DomainError("path_conflict", "share path already exists") from exc
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    if os.fstat(fd).st_uid != 0:
                        raise DomainError("unsafe_share", "share must remain root-owned", 403)
                    if path_scope:
                        info = os.fstat(fd)
                        if (info.st_dev, info.st_ino) != (path_scope["device"], path_scope["inode"]):
                            raise DomainError("scope_changed", "Shared directory identity changed during execution", 409)
                    if member_groups:
                        membership_touched = True
                        member_groups.apply(merged["members"])
                    reader_gid = grp.getgrnam(merged["reader_group"]).gr_gid
                    writer_gid = grp.getgrnam(merged["writer_group"]).gr_gid
                    os.fchown(fd, 0, writer_gid)
                    os.fchmod(fd, 0o2770)
                    # Descriptor path prevents ACL command from resolving a swapped share name.
                    acl = f"u::rwx,g::rwx,g:{reader_gid}:r-x,g:{writer_gid}:rwx,m::rwx,o::---,d:u::rwx,d:g::rwx,d:g:{reader_gid}:r-x,d:g:{writer_gid}:rwx,d:m::rwx,d:o::---"
                    # /proc/self/fd requires fd inheritance; invoke through pinned directory cwd instead.
                    path = f"/proc/{os.getpid()}/fd/{fd}"
                    service.accounts.run(["setfacl", "--set", acl, "--", path])
                    actual = service.accounts.run(["getfacl", "--numeric", "--absolute-names", "--", path])
                    access_acl = {"user::rwx", "group::rwx", f"group:{reader_gid}:r-x", f"group:{writer_gid}:rwx", "mask::rwx", "other::---"}
                    expected_acl = access_acl | {"default:" + entry for entry in access_acl}
                    actual_acl = {line.split("#", 1)[0].strip() for line in actual.splitlines() if line.split("#", 1)[0].strip()}
                    if actual_acl != expected_acl:
                        raise DomainError("acl_readback_mismatch", "share ACL permissions or inheritance readback failed", 503)
                except Exception:
                    if created is not None:
                        # Restrict only our pinned new directory; never delete files on a failed grant.
                        os.fchmod(fd, 0o700)
                    raise
                finally:
                    os.close(fd)
            except Exception as exc:
                if membership_touched:
                    member_groups.restrict_after_failure()
                if existing:
                    existing["status"] = "access_recheck_required"
                    existing["revision"] += 1
                    if state.get("storage"):
                        state["storage"].setdefault("capabilities", {})["acl"] = {"status": "requires_attention"}
                if created is not None:
                    current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                        try:
                            os.rmdir(name, dir_fd=parent)
                        except OSError:
                            raise DomainError("share_creation_incomplete", "New shared directory retained after failure; inspect its files and permissions before retrying", 409) from exc
                    else:
                        raise DomainError("share_creation_incomplete", "Shared directory identity changed; existing path was retained", 409) from exc
                if isinstance(exc, OSError):
                    raise DomainError("host_command_failed", "Shared filesystem operation failed; inspect permissions and preview again", 503) from exc
                raise
            finally:
                os.close(parent)
            state["acl_verified_at"] = utcnow().isoformat()
            if state.get("storage"):
                state["storage"].setdefault("capabilities", {})["acl"] = {
                    "status": "requires_attention" if any(s is not existing and s.get("status") == "access_recheck_required" for s in state["shares"]) else "verified",
                    "message": "Review per-project permission status and last successful ACL verification",
                    "verified_at": state["acl_verified_at"],
                }
            if existing:
                before = dict(existing)
                existing.update(changes)
                if member_groups:
                    existing.update(member_groups.names, access_mode="members")
                existing["status"] = "active"
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
                    usage_bytes=None,
                )
                if member_groups:
                    result.update(access_mode="members", members=merged["members"])
                state["shares"].append(result)
            state["previews"].pop(p["token"])
            service.event(state, p, "share." + action, result["id"], before, result)
            return result
        raise DomainError("unsupported", "unsupported storage action", 422)
