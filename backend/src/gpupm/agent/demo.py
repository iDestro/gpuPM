import copy
import json
import secrets
import sqlite3
import threading
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from gpupm.domain.rules import account_status, parse_time, utcnow, validate_name
from gpupm.errors import DomainError

SENSITIVE_GROUPS = {"root", "sudo", "docker", "adm", "gpupm", "shadow", "disk", "lxd", "libvirt"}


def require_groups(groups):
    for group in groups:
        if group in SENSITIVE_GROUPS:
            raise DomainError("protected_group", "不能通过平台授予敏感系统组权限", 403)
        validate_name(group)


class DemoAgent:
    """Persistent simulation. It never accesses host accounts, files or signals."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
            if not db.execute("SELECT id FROM state WHERE id=1").fetchone():
                db.execute("INSERT INTO state VALUES (1,?)", (json.dumps(self.seed()),))
        path.chmod(0o600)

    def seed(self):
        now = utcnow()
        accounts = []
        for index, name in enumerate(["alice", "bob"]):
            accounts.append(
                dict(
                    id=f"demo-{name}",
                    username=name,
                    uid=1001 + index,
                    gid=1001 + index,
                    groups=[name],
                    primary_group=name,
                    shell="/bin/bash",
                    home=f"/home/{name}",
                    data_dir=f"/data/{name}",
                    status="active",
                    managed=True,
                    protected=False,
                    disabled=False,
                    deleted_at=None,
                    expires_on=None,
                    require_password_change=False,
                    notes="",
                    revision=1,
                    public_keys=[],
                    login_policy_status="demo",
                )
            )
        tasks = []
        for index, account in enumerate(accounts):
            pid = 4201 + index * 100

            def process(pid, ppid, gpu=True):
                return dict(
                    identity=dict(boot_id="demo-boot", pid=pid, start_ticks=pid * 100),
                    pid=pid,
                    ppid=ppid,
                    uid=account["uid"],
                    username=account["username"],
                    command="python train.py --epochs 100" if gpu else "python DataLoader worker",
                    create_time=(now - timedelta(hours=index + 2)).isoformat(),
                    status="S",
                    gpu_memory={"demo-gpu-0": (index + 2) * 1024**3} if gpu else {},
                    evidence="演示：已确认训练进程树",
                )

            tasks.append(
                dict(
                    id=f"demo-task-{index + 1}",
                    name=f"{account['username']} / training",
                    uid=account["uid"],
                    username=account["username"],
                    started_at=(now - timedelta(hours=index + 2)).isoformat(),
                    members=[process(pid, 4000), process(pid + 1, pid, False)],
                    context=[],
                    notes="",
                    priority=50,
                    protected=False,
                    revision=1,
                    status="running",
                    expires_at=None,
                    max_runtime_seconds=None,
                    deadline_action="notify",
                    cleanup_orphans=False,
                    policy_status="applied",
                    anomalies=[],
                )
            )
        return dict(
            gpus=[
                dict(
                    uuid="demo-gpu-0",
                    index=0,
                    name="NVIDIA RTX 2080 · 模拟设备",
                    memory_total=8 * 1024**3,
                    memory_used=5 * 1024**3,
                    utilization=72,
                    error=None,
                )
            ],
            tasks=tasks,
            accounts=accounts,
            system_groups=[
                dict(
                    id=a["username"],
                    name=a["username"],
                    gid=a["gid"],
                    members=[a["username"]],
                    managed=True,
                    protected=False,
                    revision=1,
                )
                for a in accounts
            ],
            shares=[],
            jobs={},
            previews={},
            idempotency={},
            events=[],
            quotas={},
            settings={},
            login_events=[],
        )

    def call(self, method, params=None):
        with self.lock, sqlite3.connect(self.path) as db:
            state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
            result = self.dispatch(state, method, params or {})
            db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
            return copy.deepcopy(result)

    def find(self, state, kind, ident):
        for item in state[kind]:
            if item["id"] == ident:
                return item
        raise DomainError("not_found", "目标不存在", 404)

    def preview(self, state, kind, item, action, targets=None, changes=None):
        token = secrets.token_urlsafe(32)
        result = dict(
            token=token,
            expires_at=(utcnow() + timedelta(seconds=30)).isoformat(),
            revision=item["revision"],
            targets=targets or [],
            excluded=[],
            id=item["id"],
        )
        if changes and "password" in changes:
            raise DomainError("secret_in_preview", "密码不能进入预览", 422)
        state["previews"][token] = dict(**result, kind=kind, action=action, changes=changes or {})
        return result

    def checked_preview(self, state, params, kind, item, action):
        token = params.get("token")
        preview = state["previews"].get(token)
        if (
            not preview
            or preview["kind"] != kind
            or preview["action"] != action
            or preview["id"] != item["id"]
        ):
            raise DomainError("invalid_preview", "请先获取有效操作预览")
        if parse_time(preview["expires_at"]) < utcnow() or preview["revision"] != item["revision"]:
            raise DomainError("scope_changed", "预览过期或范围/配置已经改变，请重新预览")
        if params.get("revision", item["revision"]) != item["revision"]:
            raise DomainError("revision_conflict", "配置版本已经改变")
        return preview

    def event(self, state, params, action, target, before, after):
        state["events"].append(
            dict(
                id=str(uuid4()),
                time=utcnow().isoformat(),
                actor=params.get("actor", "system"),
                action=action,
                target=target,
                before=before,
                after=after,
                result="demo",
                reason=params.get("reason", ""),
            )
        )

    def dispatch(self, state, method, p):
        for account in state["accounts"]:
            expired = bool(account.get("expires_on") and account["expires_on"] <= utcnow().date().isoformat())
            account["status"] = account_status(
                deleted=bool(account.get("deleted_at")),
                disabled=account.get("disabled", False),
                expired=expired,
            )
            account["expires_effective_at"] = (
                account["expires_on"] + "T00:00:00+00:00" if account.get("expires_on") else None
            )
        if method == "heartbeat":
            state["settings"].update(p.get("settings", {}))
            return {"status": "ok", "source": "demo"}
        if method == "health":
            return dict(status="ok", source="demo", mutations=True)
        if method == "snapshot":
            return dict(
                gpus=state["gpus"],
                tasks=state["tasks"],
                accounts=state["accounts"],
                system_groups=state["system_groups"],
                source="demo",
                collected_at=utcnow().isoformat(),
                stale=False,
                errors=[],
                capabilities={"mutations": True},
            )
        if method == "configure":
            state["settings"].update(p.get("settings", {}))
            return dict(status="applied", source="demo")
        if method == "list_accounts":
            return state["accounts"]
        if method == "list_system_groups":
            return state["system_groups"]
        if method == "list_shares":
            return state["shares"]
        if method == "apply_task_policy":
            task = self.find(state, "tasks", p["task_id"])
            if p["revision"] != task["revision"]:
                raise DomainError("revision_conflict", "任务版本已经改变")
            task.update(p["policy"])
            task["revision"] += 1
            return task
        if method == "preview_termination":
            task = self.find(state, "tasks", p["task_id"])
            if task["protected"] or task["status"] == "finished":
                raise DomainError("protected", "任务受保护或已结束")
            targets = task["members"]
            if p.get("identity"):
                targets = [m for m in targets if m["identity"] == p["identity"]]
                if not targets:
                    raise DomainError("identity_changed", "目标进程不属于已确认任务")
            result = self.preview(state, "task", task, "terminate", targets)
            result["task_id"] = task["id"]
            return result
        if method == "execute_termination":
            key = p["idempotency_key"]
            if key in state["idempotency"]:
                stored = state["idempotency"][key]
                if stored["token"] != p["token"]:
                    raise DomainError("idempotency_conflict", "幂等键已用于另一操作")
                return state["jobs"][stored["id"]]
            preview = state["previews"].get(p["token"])
            if not preview:
                raise DomainError("invalid_preview", "终止预览无效")
            task = self.find(state, "tasks", preview["id"])
            if p.get("task_id", task["id"]) != task["id"]:
                raise DomainError("scope_changed", "终止预览不属于此任务")
            preview = self.checked_preview(state, p, "task", task, "terminate")
            if task["protected"]:
                raise DomainError("protected", "任务受保护")
            job = dict(
                id=str(uuid4()),
                status="succeeded",
                reason=p["reason"],
                created_at=utcnow().isoformat(),
                source="demo",
                results=[dict(identity=m["identity"], status="demo_terminated") for m in preview["targets"]],
            )
            removed = [m["identity"] for m in preview["targets"]]
            task["members"] = [m for m in task["members"] if m["identity"] not in removed]
            if not task["members"]:
                task["status"] = "finished"
            task["revision"] += 1
            state["jobs"][job["id"]] = job
            state["idempotency"][key] = dict(id=job["id"], token=p["token"])
            del state["previews"][p["token"]]
            self.event(state, p, "task.terminate", task["id"], None, job)
            return job
        if method == "job_status":
            if p["id"] not in state["jobs"]:
                raise DomainError("not_found", "作业不存在", 404)
            return state["jobs"][p["id"]]
        if method == "audit_since":
            return state["events"]
        if method == "apply_membership":
            action = p["action"]
            if action == "merge":
                tasks = [self.find(state, "tasks", i) for i in p["task_ids"]]
                if len(tasks) < 2 or len({t["uid"] for t in tasks}) != 1:
                    raise DomainError("invalid_grouping", "合并必须至少两个同 UID 任务")
                for task in tasks:
                    if p["revisions"].get(task["id"]) != task["revision"]:
                        raise DomainError("revision_conflict", "任务版本已经改变")
                target = tasks[0]
                target["members"] = [m for t in tasks for m in t["members"]]
                target["started_at"] = min(t["started_at"] for t in tasks)
                target["revision"] += 1
                state["tasks"] = [t for t in state["tasks"] if t["id"] not in p["task_ids"][1:]]
                return target
            task = self.find(state, "tasks", p["task_id"])
            if task["revision"] != p["revision"]:
                raise DomainError("revision_conflict", "任务版本已经改变")
            if action == "exclude":
                task["members"] = [
                    m for m in task["members"] if m["identity"] not in p["excluded_identities"]
                ]
            elif action == "split":
                selected = [m for m in task["members"] if m["identity"] in p["identities"]]
                if not selected or len(selected) == len(task["members"]):
                    raise DomainError("invalid_split", "拆分应选择部分已确认成员")
                new = copy.deepcopy(task)
                new.update(id=str(uuid4()), name=task["name"] + " / split", members=selected, revision=1)
                task["members"] = [m for m in task["members"] if m not in selected]
                state["tasks"].append(new)
            task["revision"] += 1
            return task
        if method == "preview_account_change":
            account = self.find(state, "accounts", p["id"])
            if account["protected"]:
                raise DomainError("protected_account", "账号受保护", 403)
            if p["revision"] != account["revision"]:
                raise DomainError("revision_conflict", "账号版本已经改变")
            return self.preview(state, "account", account, p["action"], changes=p.get("changes", {}))
        if method == "execute_account_change":
            changes = dict(p.get("changes", {}))
            require_groups(changes.get("groups", []))
            if "primary_group" in changes:
                require_groups([changes["primary_group"]])
                if not any(g["name"] == changes["primary_group"] for g in state["system_groups"]):
                    raise DomainError("not_found", "主组不存在", 404)
            action = p["action"]
            if action == "create":
                name = validate_name(changes["username"])
                if any(a["username"] == name for a in state["accounts"]):
                    raise DomainError("account_exists", "账号已存在，包括软删除账号")
                if not changes.get("password") and not changes.get("public_keys"):
                    raise DomainError("credentials_required", "至少配置密码或公钥", 422)
                if changes.get("password") and len(changes["password"]) < 12:
                    raise DomainError("weak_password", "密码至少 12 位", 422)
                uid = max(a["uid"] for a in state["accounts"]) + 1
                account = dict(
                    id=str(uuid4()),
                    username=name,
                    uid=uid,
                    gid=uid,
                    groups=[name] + changes.get("groups", []),
                    primary_group=name,
                    shell="/bin/bash",
                    home=f"/home/{name}",
                    data_dir=f"/data/{name}",
                    status="active",
                    managed=True,
                    protected=False,
                    disabled=False,
                    deleted_at=None,
                    expires_on=changes.get("expires_on"),
                    require_password_change=changes.get("require_password_change", True),
                    notes=changes.get("notes", ""),
                    revision=1,
                    public_keys=changes.get("public_keys", []),
                    login_policy_status="demo",
                )
                state["accounts"].append(account)
                state["system_groups"].append(
                    dict(
                        id=name, name=name, gid=uid, members=[name], protected=False, managed=True, revision=1
                    )
                )
                self.event(state, p, "account.create", account["id"], None, account)
                return account
            account = self.find(state, "accounts", p["id"])
            if account["protected"]:
                raise DomainError("protected_account", "账号受保护", 403)
            if p.get("revision", account["revision"]) != account["revision"]:
                raise DomainError("revision_conflict", "账号版本已经改变")
            if action != "create":
                preview = self.checked_preview(state, p, "account", account, action)
                if (
                    preview["changes"] != {k: v for k, v in changes.items() if k not in {"password"}}
                    and action == "update"
                ):
                    raise DomainError("scope_changed", "预览变更内容已经改变")
                del state["previews"][p["token"]]
            if account.get("deleted_at") and action not in {"restore"}:
                raise DomainError("account_deleted", "先恢复已删除账号")
            before = copy.deepcopy(account)
            if action == "disable":
                account["disabled"] = True
            elif action == "enable":
                account["disabled"] = False
            elif action == "delete":
                account["deleted_at"] = utcnow().isoformat()
            elif action == "restore":
                account["deleted_at"] = None
            elif action == "update":
                if changes.get("username") and changes["username"] != account["username"]:
                    if any(t["uid"] == account["uid"] and t["status"] != "finished" for t in state["tasks"]):
                        raise DomainError("account_busy", "存在活动进程，不能在线改名")
                    name = validate_name(changes["username"])
                    if any(a["username"] == name for a in state["accounts"]):
                        raise DomainError("account_exists", "账号已存在")
                    account.update(home=f"/home/{name}", data_dir=f"/data/{name}")
                for field in [
                    "username",
                    "notes",
                    "shell",
                    "groups",
                    "primary_group",
                    "public_keys",
                    "expires_on",
                    "require_password_change",
                ]:
                    if field in changes:
                        account[field] = changes[field]
            else:
                raise DomainError("unsupported", "不支持的账号操作", 422)
            if "primary_group" in changes:
                account["gid"] = next(
                    g["gid"] for g in state["system_groups"] if g["name"] == changes["primary_group"]
                )
            expired = bool(account.get("expires_on") and account["expires_on"] <= utcnow().date().isoformat())
            account["status"] = account_status(
                deleted=bool(account["deleted_at"]), disabled=account["disabled"], expired=expired
            )
            account["revision"] += 1
            self.event(state, p, "account." + action, account["id"], before, account)
            return account
        if method == "account_activity":
            account = self.find(state, "accounts", p["id"])
            return dict(
                processes=[m for t in state["tasks"] for m in t["members"] if m["uid"] == account["uid"]],
                sessions=[],
                scheduled=[],
                coverage="演示数据，未读取宿主机会话/定时任务",
            )
        if method == "preview_group_change":
            group = self.find(state, "system_groups", p["id"])
            return self.preview(
                state, "group", group, p.get("action", "update"), changes=p.get("changes", {})
            )
        if method == "execute_group_change":
            changes = p.get("changes", {})
            require_groups([changes.get("name", p.get("id", ""))])
            if p["action"] == "create":
                name = validate_name(changes["name"])
                if any(g["name"] == name for g in state["system_groups"]):
                    raise DomainError("group_exists", "系统组已存在")
                group = dict(
                    id=name,
                    name=name,
                    gid=max(g["gid"] for g in state["system_groups"]) + 1,
                    members=changes.get("members", []),
                    protected=False,
                    managed=True,
                    revision=1,
                )
                state["system_groups"].append(group)
            else:
                group = self.find(state, "system_groups", p["id"])
                preview = self.checked_preview(state, p, "group", group, p["action"])
                if preview["changes"] != changes:
                    raise DomainError("scope_changed", "系统组变更与预览不一致")
                if p["action"] == "delete":
                    if group["members"] or any(a["gid"] == group["gid"] for a in state["accounts"]):
                        raise DomainError("group_in_use", "系统组有成员或主组引用")
                    state["system_groups"].remove(group)
                else:
                    group.update(changes)
                    group["revision"] += 1
                del state["previews"][p["token"]]
            self.event(state, p, "system_group." + p["action"], group["id"], None, group)
            return group
        if method == "storage_snapshot":
            return dict(
                filesystems=[
                    dict(
                        id="demo-fs",
                        path="/data",
                        fstype="demo",
                        total=1024**4,
                        available=700 * 1024**3,
                        quota_supported=True,
                        quota_enabled=True,
                        error=None,
                    )
                ],
                users=[
                    dict(
                        account_id=a["id"],
                        username=a["username"],
                        home_bytes=2 * 1024**3,
                        data_bytes=30 * 1024**3,
                        files=1024,
                        collected_at=utcnow().isoformat(),
                        status="demo",
                    )
                    for a in state["accounts"]
                ],
                shares=state["shares"],
                alerts=[],
                collected_at=utcnow().isoformat(),
                source="demo",
            )
        if method == "get_quotas":
            self.find(state, "accounts", p["id"])
            return state["quotas"].get(
                p["id"],
                [
                    dict(
                        filesystem_id="demo-fs",
                        soft_bytes=0,
                        hard_bytes=0,
                        soft_inodes=0,
                        hard_inodes=0,
                        grace_seconds=604800,
                        used_bytes=32 * 1024**3,
                        used_inodes=1024,
                        status="demo",
                        error=None,
                    )
                ],
            )
        if method == "preview_quota":
            account = self.find(state, "accounts", p["id"])
            policy = p["policy"]
            if policy["filesystem_id"] != "demo-fs":
                raise DomainError("quota_unsupported", "演示文件系统仅支持 demo-fs", 422)
            result = self.preview(state, "quota", account, "update", changes=policy)
            result.update(
                current={"used_bytes": 32 * 1024**3, "used_inodes": 1024},
                proposed=policy,
                impact="限额低于当前用量时，新写入可能被拒绝；演示不实际限制宿主机。",
            )
            return result
        if method == "apply_quota":
            account = self.find(state, "accounts", p["id"])
            preview = self.checked_preview(state, p, "quota", account, "update")
            if preview["changes"] != p["policy"]:
                raise DomainError("scope_changed", "预览的配额设置已改变")
            if p["policy"]["filesystem_id"] != "demo-fs":
                raise DomainError("quota_unsupported", "文件系统不支持配额", 422)
            quota = dict(**p["policy"], used_bytes=32 * 1024**3, used_inodes=1024, status="demo", error=None)
            state["quotas"][p["id"]] = [quota]
            del state["previews"][p["token"]]
            self.event(state, p, "quota.update", p["id"], None, quota)
            return quota
        if method == "login_events_since":
            return dict(
                items=state["login_events"],
                total=len(state["login_events"]),
                coverage="演示模式：无真实登录日志",
            )
        if method == "preview_share_change":
            if p.get("action") == "create":
                name = validate_name(p["changes"]["name"])
                candidate = dict(id="new-share:" + name, revision=1)
                return self.preview(state, "share", candidate, "create", changes=p["changes"])
            share = self.find(state, "shares", p["id"])
            return self.preview(state, "share", share, "update", changes=p.get("changes", {}))
        if method == "execute_share_change":
            changes = p["changes"]
            if p.get("id"):
                share = self.find(state, "shares", p["id"])
                preview = self.checked_preview(state, p, "share", share, "update")
                fields = dict(share, **changes)
            else:
                name = validate_name(changes["name"])
                candidate = dict(id="new-share:" + name, revision=1)
                preview = self.checked_preview(state, p, "share", candidate, "create")
                fields = changes
                if any(s["name"] == name for s in state["shares"]):
                    raise DomainError("share_exists", "共享项目已存在")
            if preview["changes"] != changes:
                raise DomainError("scope_changed", "共享授权与预览不同")
            require_groups([fields["reader_group"], fields["writer_group"]])
            known = {g["name"] for g in state["system_groups"]}
            if fields["reader_group"] not in known or fields["writer_group"] not in known:
                raise DomainError("group_missing", "共享授权组不存在", 422)
            if fields["reader_group"] == fields["writer_group"]:
                raise DomainError("invalid_share", "读写组与只读组必须不同", 422)
            if p.get("id"):
                share.update(changes)
                share["revision"] += 1
            else:
                share = dict(
                    id=str(uuid4()),
                    path="/data/shared/" + fields["name"],
                    status="active",
                    revision=1,
                    usage_bytes=0,
                    **fields,
                )
                state["shares"].append(share)
            del state["previews"][p["token"]]
            self.event(state, p, "share.update", share["id"], None, share)
            return share
        raise DomainError("unsupported", "未支持的 agent 方法：" + method, 422)
