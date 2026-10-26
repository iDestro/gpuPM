from gpupm.domain.user_policy import policy_editable
from gpupm.agent.accounts import account_change_details, lifecycle_details, validate_keys
import copy
import json
import secrets
import sqlite3
import threading
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from gpupm.agent.processes import residual_ready, residual_status, shell_process
from gpupm.domain.schemas import TaskPatch, SettingsPatch
from gpupm.domain.rules import account_status, parse_time, utcnow, validate_name
from gpupm.domain.settings import DEFAULT_SETTINGS, task_defaults, ignored_process
from gpupm.errors import DomainError
from gpupm.domain.schemas import validate_business_changes
from gpupm.agent.groups import describe_group, filter_groups, require_assignable, validate_group_change

from gpupm.agent.accounts import SENSITIVE_GROUPS


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
            state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
            if not any(g["name"] == "human" for g in state["system_groups"]):
                members = [
                    a["username"] for a in state["accounts"] if a.get("managed") and not a.get("protected")
                ]
                gid = max(1000, max((g["gid"] for g in state["system_groups"]), default=999) + 1)
                state["system_groups"].append(
                    dict(
                        id="human",
                        name="human",
                        gid=gid,
                        members=members,
                        managed=False,
                        protected=True,
                        revision=1,
                    )
                )
                for account in state["accounts"]:
                    if account["username"] in members:
                        account["groups"] = sorted(set(account["groups"]) | {"human"})
                db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
            state["settings"] = dict(DEFAULT_SETTINGS, **state["settings"])
            for task in state["tasks"]:
                task.setdefault(
                    "original_name",
                    {"demo-task-1": "alice / training", "demo-task-2": "bob / training"}.get(
                        task["id"],
                        next((p["command"][:120] for p in task["members"] if p.get("gpu_memory")), None),
                    ),
                )
            db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))
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
                    groups=[name, "human"],
                    primary_group=name,
                    private_group=name,
                    private_gid=1001 + index,
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
                    original_name=f"{account['username']} / training",
                    uid=account["uid"],
                    username=account["username"],
                    started_at=(now - timedelta(hours=index + 2)).isoformat(),
                    members=[process(pid, 4000), process(pid + 1, pid, False)],
                    context=[],
                    notes="",
                    **task_defaults(DEFAULT_SETTINGS),
                    revision=1,
                    status="running",
                    expires_at=None,
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
                    id="human",
                    name="human",
                    gid=2000,
                    members=[a["username"] for a in accounts],
                    managed=False,
                    protected=True,
                    revision=1,
                )
            ]
            + [
                dict(
                    id=a["username"],
                    name=a["username"],
                    gid=a["gid"],
                    members=[],
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
            settings=DEFAULT_SETTINGS.copy(),
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
        if kind == "group":
            result["host_scope"] = {
                k: copy.deepcopy(item.get(k))
                for k in ("gid", "name", "members", "managed", "kind", "primary_users", "share_refs")
            }
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
        if preview.get("host_scope") != (
            {k: item.get(k) for k in preview["host_scope"]} if preview.get("host_scope") else None
        ):
            raise DomainError("scope_changed", "group native scope changed")
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

    def require_human(self, item):
        if not item.get("is_human"):
            raise DomainError("non_human_readonly", "only human accounts and tasks are editable", 403)

    def sync_account_groups(self, state, account):
        for group in state["system_groups"]:
            members = set(group["members"]) - {account["username"]}
            if group["name"] in account["groups"] and group["gid"] != account["gid"]:
                members.add(account["username"])
            group["members"] = sorted(members)

    def validate_group_scope(self, state, names):
        for name in names:
            if name == "human":
                raise DomainError("protected_group", "human is a classification group", 403)
            group = next((g for g in state["system_groups"] if g["name"] == name), None)
            if not group:
                raise DomainError("group_missing", "group does not exist", 422)
            members = set(group["members"])
            members.update(a["username"] for a in state["accounts"] if a["gid"] == group["gid"])
            for member in members:
                account = next((a for a in state["accounts"] if a["username"] == member), None)
                if not account:
                    raise DomainError("non_human_readonly", "unknown group member", 403)
                self.require_human(account)

    def dispatch(self, state, method, p):
        human = next((g for g in state["system_groups"] if g["name"] == "human"), None)
        for account in state["accounts"]:
            private = next(
                (
                    g
                    for g in state["system_groups"]
                    if g["name"] == account["username"] and g["gid"] == account["gid"]
                ),
                None,
            )
            if private and account.get("private_group", private["name"]) == private["name"]:
                account.setdefault("private_group", private["name"])
                account.setdefault("private_gid", private["gid"])
            account["is_human"] = bool(
                human and (account["gid"] == human["gid"] or account["username"] in human["members"])
            )
            account["lifecycle"] = lifecycle_details(account)
            account["readonly_reasons"] = [
                code
                for active, code in (
                    (account.get("protected"), "protected_account"),
                    (not account["is_human"], "non_human_readonly"),
                    (not account.get("managed"), "unmanaged_account"),
                    (bool(account.get("deleted_at")), "account_deleted"),
                    (account.get("creation", {}).get("status") == "incomplete", "creation_incomplete"),
                )
                if active
            ]
            account["recovery_required"] = account.get("creation", {}).get("status") == "incomplete"
        state["system_groups"] = [
            describe_group(
                g,
                state["accounts"],
                state["shares"],
                {
                    a.get("private_group", a.get("primary_group"))
                    for a in state["accounts"]
                    if a.get("primary_group") == a["username"] or a.get("private_group")
                },
            )
            for g in state["system_groups"]
        ]
        humans = {a["uid"] for a in state["accounts"] if a["is_human"]}
        for task in state["tasks"]:
            members = task["members"] + task.get("ignored_members", [])
            task["gpu_uuids"] = sorted(
                set(task.get("gpu_uuids", []))
                | {gpu for m in members for gpu in m.get("gpu_memory", {})}
            )
            task["ignored_members"] = [
                m for m in members if ignored_process(m, state["settings"]["ignored_task_executables"])
            ]
            task["members"] = [
                m for m in members if not ignored_process(m, state["settings"]["ignored_task_executables"])
            ]
            task["ignored"] = bool(task["ignored_members"] and not task["members"])
            for field in ("orphan_reminder", "orphan_wait_seconds"):
                task.setdefault(field, task_defaults(state["settings"])[field])
            task.setdefault(
                "leader_identities",
                [m["identity"] for m in members if m["ppid"] not in {p["pid"] for p in members}],
            )
            task["leaders_present"] = any(m["identity"] in task["leader_identities"] for m in members)
            task["is_human"] = task["uid"] in humans
            residual_status(task, utcnow())
        if method in {"preview_group_change", "execute_group_change"}:
            changes = p.get("changes", {})
            if p.get("id") == "human" or changes.get("name") == "human":
                raise DomainError("protected_group", "human membership is root-controlled", 403)
            if p.get("action") != "create":
                group = self.find(state, "system_groups", p["id"])
                validate_group_change(group, p.get("action", "update"), changes)
                self.validate_group_scope(state, [p["id"]])
            elif "managed" in changes:
                raise DomainError("invalid_adoption", "create cannot adopt", 422)
            if "members" in changes and not isinstance(changes["members"], list):
                raise DomainError("invalid_members", "members must be a list", 422)
            for member in changes.get("members", []):
                account = next((a for a in state["accounts"] if a["username"] == member), None)
                if not account:
                    raise DomainError("non_human_readonly", "unknown group member", 403)
                self.require_human(account)
                if account["protected"] or not account["managed"]:
                    raise DomainError("protected_account", "grant only to managed ordinary accounts", 403)
        member_changes = None
        member_scope = None
        member_names = None
        if method in {"preview_share_change", "execute_share_change"}:
            share = self.find(state, "shares", p["id"]) if p.get("id") else {}
            if share and p.get("revision") != share["revision"]:
                raise DomainError("revision_conflict", "configuration or membership changed", 409)
            changes = p.get("changes", {})
            fields = dict(share, **changes)
            if share.get("access_mode") == "members" and {"reader_group", "writer_group"} & changes.keys():
                raise DomainError("invalid_share", "Use member permissions for this directory", 422)
            if "members" in changes:
                from gpupm.agent.share_members import MemberGroups, member_rows, validate_members
                if {"reader_group", "writer_group"} & changes.keys():
                    raise DomainError("invalid_share", "Cannot mix members and groups", 422)
                member_changes = validate_members(changes["members"], state["accounts"])
                member_names = MemberGroups(None, state, validate_name(fields["name"])).names
                owned = [g for g in state["system_groups"] if g["name"] in member_names.values()]
                if any(g.get("share_owner") != fields["name"] for g in owned):
                    raise DomainError("identity_conflict", "Shared directory group conflict", 409)
                member_scope = dict(current=member_rows(share, state["system_groups"]) if share else [],
                    identities=[{k:a.get(k) for k in ("username","uid","revision")} for a in state["accounts"] if a["username"] in {m["username"] for m in member_changes}],
                    groups=[{k:g.get(k) for k in ("name","gid","members")} for g in owned])
            else:
                names = [fields[f] for f in ("reader_group", "writer_group") if not share or fields[f] != share[f]]
                if names:
                    names = [fields["reader_group"], fields["writer_group"]]
                    require_assignable(state["system_groups"], names)
                    self.validate_group_scope(state, names)
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
            self.dispatch(state, "configure", dict(settings=p.get("settings", {})))
            return {"status": "ok", "source": "demo"}
        if method == "health":
            return dict(
                status="ok",
                source="demo",
                mutations=True,
                roots=dict(home_base="/home", data_base="/data", share_base="/data/shared"),
                root_readiness=dict(ready=True, error_code=None, source="demo"),
            )
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
            settings = p.get("settings", {})
            SettingsPatch.model_validate(settings)
            changed = (
                settings.get("ignored_task_executables", state["settings"]["ignored_task_executables"])
                != state["settings"]["ignored_task_executables"]
            )
            state["settings"].update(settings)
            if changed:
                state["previews"] = {k: v for k, v in state["previews"].items() if v.get("kind") != "task"}
                for task in state["tasks"]:
                    task["revision"] += 1
            return dict(status="applied", source="demo")
        if method == "list_accounts":
            return state["accounts"]
        if method == "list_system_groups":
            return filter_groups(state["system_groups"], p.get("scope", "managed"))
        if method == "list_shares":
            from gpupm.agent.share_members import member_rows
            result = []
            for share in state["shares"]:
                try:
                    result.append(dict(share, members=member_rows(share, state["system_groups"])))
                except DomainError:
                    result.append(dict(share, members=None, membership_error="share_members_unavailable"))
            return result
        if method == "apply_task_policy":
            task = self.find(state, "tasks", p["task_id"])
            self.require_human(task)
            if p["revision"] != task["revision"]:
                raise DomainError("revision_conflict", "任务版本已经改变")
            if "is_human" in p["policy"]:
                raise DomainError("invalid_policy", "human membership is not a policy field", 422)
            account = next((a for a in state["accounts"] if a["uid"] == task["uid"]), None)
            if any(task.get(k) != v for k, v in p["policy"].items()) and not policy_editable(account):
                raise DomainError("policy_readonly", "account task policy is read-only", 403)
            TaskPatch.model_validate(dict(revision=p["revision"], **p["policy"]))
            task.update(p["policy"])
            task["revision"] += 1
            return task
        if method == "preview_termination":
            task = self.find(state, "tasks", p["task_id"])
            self.require_human(task)
            if task.get("ignored") or task["protected"] or task["status"] == "finished":
                raise DomainError("protected", "任务受保护或已结束")
            residual_only = p.get("residual_only", False)
            if residual_only and not residual_ready(task, utcnow()):
                raise DomainError("residual_not_ready", "residual cleanup conditions changed", 409)
            targets = [
                m
                for m in task["members"]
                if m["uid"] == task["uid"]
                and m["uid"] in humans
                and not shell_process(m)
                and m["status"] not in {"zombie", "Z"}
                and (m["ppid"] != 1 or m["identity"] in task.get("leader_identities", []) or residual_only or task.get("cleanup_orphans"))
            ]
            if p.get("identity"):
                targets = [m for m in targets if m["identity"] == p["identity"]]
                if not targets:
                    raise DomainError("identity_changed", "目标进程不属于已确认任务")
            result = self.preview(state, "task", task, "terminate", targets)
            result["excluded"] = [
                dict(identity=m["identity"], reason="protected, zombie, or unauthorized orphan")
                for m in task["members"]
                if m not in targets and (not p.get("identity") or m["identity"] == p["identity"])
            ]
            state["previews"][result["token"]]["excluded"] = result["excluded"]
            result["residual_only"] = residual_only
            state["previews"][result["token"]]["residual_only"] = residual_only
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
            self.require_human(task)
            if p.get("task_id", task["id"]) != task["id"]:
                raise DomainError("scope_changed", "终止预览不属于此任务")
            preview = self.checked_preview(state, p, "task", task, "terminate")
            if task["protected"]:
                raise DomainError("protected", "任务受保护")
            if preview.get("residual_only") and not residual_ready(task, utcnow()):
                raise DomainError("residual_not_ready", "residual cleanup conditions changed", 409)
            if not all(
                any(
                    m["identity"] == target["identity"]
                    and m["uid"] == target["uid"]
                    and m["uid"] == task["uid"]
                    and not shell_process(m)
                    and m["status"] not in {"zombie", "Z"}
                    and (m["ppid"] != 1 or m["identity"] in task.get("leader_identities", []) or preview.get("residual_only") or task.get("cleanup_orphans"))
                    for m in task["members"]
                )
                for target in preview["targets"]
            ):
                raise DomainError("scope_changed", "confirmed target scope changed")
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
            residual_status(task, utcnow())
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
                    self.require_human(task)
                    if p["revisions"].get(task["id"]) != task["revision"]:
                        raise DomainError("revision_conflict", "任务版本已经改变")
                target = tasks[0]
                target["members"] = [m for t in tasks for m in t["members"]]
                target["gpu_uuids"] = sorted({gpu for t in tasks for gpu in t.get("gpu_uuids", [])})
                target["started_at"] = min(t["started_at"] for t in tasks)
                target["revision"] += 1
                state["tasks"] = [t for t in state["tasks"] if t["id"] not in p["task_ids"][1:]]
                return target
            task = self.find(state, "tasks", p["task_id"])
            self.require_human(task)
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
                new["policy_parent_task_id"] = task["id"]
                new.update(
                    id=str(uuid4()), name=task["name"] + " / split", members=selected, revision=1,
                    gpu_uuids=sorted({gpu for m in selected for gpu in m.get("gpu_memory", {})}),
                )
                task["members"] = [m for m in task["members"] if m not in selected]
                state["tasks"].append(new)
            task["revision"] += 1
            return task
        if method == "preview_account_change":
            business_changes = validate_business_changes(p.get("business_changes", {}))
            account = self.find(state, "accounts", p["id"])
            if not account["managed"] and p.get("changes", {}).get("managed") is not True:
                raise DomainError("account_unmanaged", "explicit account adoption required", 403)
            self.require_human(account)
            if account["protected"]:
                raise DomainError("protected_account", "账号受保护", 403)
            if p["revision"] != account["revision"]:
                raise DomainError("revision_conflict", "账号版本已经改变")
            pending = account.get("creation", {}).get("status") == "incomplete"
            if pending and p["action"] != "resume":
                raise DomainError("creation_incomplete", "explicit creation recovery required", 409)
            if p["action"] == "resume" and not pending:
                raise DomainError("creation_not_pending", "account creation is not pending", 409)
            if p["action"] == "resume" and p.get("changes"):
                raise DomainError("credentials_in_preview", "recovery preview must have empty changes", 422)
            result = self.preview(state, "account", account, p["action"], changes=p.get("changes", {}))
            result["business_changes"] = business_changes
            state["previews"][result["token"]]["business_changes"] = business_changes
            result.update(
                kind="account",
                action=p["action"],
                changes=p.get("changes", {}),
                paths={k: account.get(k) for k in ("home", "data_dir")},
                activity=self.dispatch(state, "account_activity", {"id": account["id"]}),
                impact="Existing files and processes are retained; restrictions remain independent.",
            )
            result.update(account_change_details(account, p["action"], p.get("changes", {})))
            if p.get("changes", {}).get("managed") is True and not account["managed"]:
                checks = [
                    dict(
                        code=key + "_path",
                        path=account.get(key),
                        ok=account.get(key) == expected,
                        actual=account.get(key),
                        expected=expected,
                    )
                    for key, expected in (
                        ("home", "/home/" + account["username"]),
                        ("data_dir", "/data/" + account["username"]),
                    )
                ]
                result["adoption"] = dict(
                    ready=all(c["ok"] for c in checks),
                    checks=checks,
                    manual_steps=[]
                    if all(c["ok"] for c in checks)
                    else ["Prepare controlled private directories; demo does not migrate data."],
                )
            return result
        if method == "execute_account_change":
            changes = dict(p.get("changes", {}))
            if "public_keys" in changes:
                validate_keys(changes["public_keys"])
            if "managed" in changes and changes["managed"] is not True:
                raise DomainError("invalid_adoption", "managed account cannot be released", 422)
            current = self.find(state, "accounts", p["id"]) if p["action"] != "create" else {}
            if current and not current["managed"] and changes.get("managed") is not True:
                raise DomainError("account_unmanaged", "explicit account adoption required", 403)
            require_assignable(
                state["system_groups"],
                [g for g in changes.get("groups", []) if g not in current.get("groups", []) and g != "human"],
            )
            if "primary_group" in changes:
                if p["action"] == "create":
                    raise DomainError("private_primary_group", "new accounts receive private groups", 422)
                if changes["primary_group"] != current.get("primary_group"):
                    target = next(
                        (g for g in state["system_groups"] if g["name"] == changes["primary_group"]), None
                    )
                    own_private = (
                        changes["primary_group"] == current.get("private_group")
                        and current.get("private_gid") is not None
                    )
                    if own_private and (not target or target["gid"] != current["private_gid"]):
                        raise DomainError("identity_conflict", "private group GID changed", 403)
                    if own_private:
                        require_groups([target["name"]])
                        if target["gid"] < 1000:
                            raise DomainError("protected_group", "system group grant forbidden", 403)
                        self.validate_group_scope(state, [target["name"]])
                        members = set(target["members"]) | set(target["primary_users"])
                        if any(
                            a["username"] in members and (a["protected"] or not a["managed"])
                            for a in state["accounts"]
                        ):
                            raise DomainError(
                                "protected_account", "private primary group contains readonly accounts", 403
                            )
                    if not own_private:
                        require_assignable(state["system_groups"], [changes["primary_group"]])
                if not any(g["name"] == changes["primary_group"] for g in state["system_groups"]):
                    raise DomainError("not_found", "主组不存在", 404)
                if changes["primary_group"] == current.get("primary_group") and not any(
                    g["name"] == changes["primary_group"] and g["gid"] == current["gid"]
                    for g in state["system_groups"]
                ):
                    raise DomainError("identity_conflict", "current primary group GID changed", 403)
            action = p["action"]
            if action == "create":
                profile = p.get("profile")
                if profile is not None:
                    from gpupm.domain.schemas import AccountProfile

                    try:
                        profile = AccountProfile.model_validate(profile).model_dump()
                    except ValueError as exc:
                        raise DomainError("invalid_profile", "invalid account business profile", 422) from exc
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
                    groups=sorted({name, "human", *changes.get("groups", [])}),
                    is_human=True,
                    primary_group=name,
                    private_group=name,
                    private_gid=uid,
                    shell="/bin/bash",
                    home=f"/home/{name}",
                    data_dir=f"/data/{name}",
                    status="active",
                    managed=True,
                    protected=False,
                    disabled=False,
                    deleted_at=None,
                    expires_on=changes.get("expires_on"),
                    require_password_change=bool(changes.get("password"))
                    and changes.get("require_password_change", True),
                    notes=changes.get("notes", ""),
                    revision=1,
                    public_keys=changes.get("public_keys", []),
                    login_policy_status="demo",
                    creation=dict(
                        status="complete",
                        stage="initialized",
                        profile=profile,
                        started_at=utcnow().isoformat(),
                        updated_at=utcnow().isoformat(),
                    ),
                )
                state["accounts"].append(account)
                human["members"].append(name)
                state["system_groups"].append(
                    dict(
                        id=name, name=name, gid=uid, members=[name], protected=False, managed=True, revision=1
                    )
                )
                self.sync_account_groups(state, account)
                account.update(
                    lifecycle=lifecycle_details(account), readonly_reasons=[], recovery_required=False
                )
                self.event(state, p, "account.create", account["id"], None, account)
                return account
            account = self.find(state, "accounts", p["id"])
            self.require_human(account)
            if account["protected"]:
                raise DomainError("protected_account", "账号受保护", 403)
            if p.get("revision", account["revision"]) != account["revision"]:
                raise DomainError("revision_conflict", "账号版本已经改变")
            if action != "create":
                preview = self.checked_preview(state, p, "account", account, action)
                if preview.get("business_changes", {}) != validate_business_changes(
                    p.get("business_changes", {})
                ):
                    raise DomainError("scope_changed", "business changes differ from preview", 409)
                if (
                    preview["changes"] != {k: v for k, v in changes.items() if k not in {"password"}}
                    and action == "update"
                ):
                    raise DomainError("scope_changed", "预览变更内容已经改变")
                del state["previews"][p["token"]]
            if account.get("deleted_at") and action not in {"restore"}:
                raise DomainError("account_deleted", "先恢复已删除账号")
            pending = account.get("creation", {}).get("status") == "incomplete"
            if pending and action != "resume":
                raise DomainError("creation_incomplete", "explicit creation recovery required", 409)
            if action == "resume":
                if not pending:
                    raise DomainError("creation_not_pending", "account creation is not pending", 409)
                if not isinstance(p.get("reason"), str) or not p["reason"].strip():
                    raise DomainError("reason_required", "recovery requires an audit reason", 422)
                if set(changes) - {"password", "public_keys", "require_password_change"}:
                    raise DomainError("invalid_fields", "recovery only accepts fresh credentials", 422)
                if not changes.get("password") and not changes.get("public_keys"):
                    raise DomainError(
                        "credentials_required", "fresh password or SSH public key required", 422
                    )
                if changes.get("password") and len(changes["password"]) < 12:
                    raise DomainError("weak_password", "password requires at least 12 characters", 422)
            if (
                changes.get("managed")
                and not account["managed"]
                and (
                    account["home"] != "/home/" + account["username"]
                    or account.get("data_dir") != "/data/" + account["username"]
                )
            ):
                raise DomainError(
                    "adoption_path_conflict", "resolve adoption preview checks before retrying", 409
                )
            before = copy.deepcopy(account)
            if account["primary_group"] == account["username"]:
                account["private_group"] = account["primary_group"]
                account["private_gid"] = account["gid"]
            if action == "disable":
                account.update(
                    disabled=True, disabled_at=utcnow().isoformat(), disabled_reason=p.get("reason")
                )
            elif action == "enable":
                account.update(disabled=False, disabled_at=None, disabled_reason=None)
            elif action == "delete":
                account.update(deleted_at=utcnow().isoformat(), deleted_reason=p.get("reason"))
            elif action == "restore":
                account.update(deleted_at=None, deleted_reason=None)
            elif action == "resume":
                account["creation"].update(
                    status="complete", stage="initialized", updated_at=utcnow().isoformat()
                )
                account.update(
                    public_keys=changes.get("public_keys", []),
                    require_password_change=bool(changes.get("password"))
                    and changes.get("require_password_change", True),
                    recovery_required=False,
                    login_policy_status="demo",
                    readonly_reasons=[],
                )
            elif action == "update":
                if changes.get("username") and changes["username"] != account["username"]:
                    if any(t["uid"] == account["uid"] and t["status"] != "finished" for t in state["tasks"]):
                        raise DomainError("account_busy", "存在活动进程，不能在线改名")
                    name = validate_name(changes["username"])
                    if any(a["username"] == name for a in state["accounts"]):
                        raise DomainError("account_exists", "账号已存在")
                    for group in state["system_groups"]:
                        group["members"] = [
                            name if member == account["username"] else member for member in group["members"]
                        ]
                    account.update(home=f"/home/{name}", data_dir=f"/data/{name}")
                for field in [
                    "username",
                    "managed",
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
                        if field == "groups":
                            account[field] = sorted(
                                set(account[field])
                                | {
                                    g
                                    for g in before.get("groups", [])
                                    if not any(
                                        item["name"] == g and item["assignable"]
                                        for item in state["system_groups"]
                                    )
                                }
                            )
            else:
                raise DomainError("unsupported", "不支持的账号操作", 422)
            if "groups" in changes or "primary_group" in changes:
                account["groups"] = sorted(set(account["groups"]) | {"human"})
                if account["username"] not in human["members"]:
                    human["members"].append(account["username"])
            if "primary_group" in changes:
                old_primary = before["primary_group"]
                old_group = next((g for g in state["system_groups"] if g["name"] == old_primary), None)
                memberships = set(account["groups"])
                if "groups" not in changes and old_group and before["username"] not in old_group["members"]:
                    memberships.discard(old_primary)
                account["groups"] = sorted(memberships | {changes["primary_group"]})
                account["gid"] = next(
                    g["gid"] for g in state["system_groups"] if g["name"] == changes["primary_group"]
                )
            if "expires_on" in changes:
                account.update(expiry_reason=p.get("reason"), expiry_set_at=utcnow().isoformat())
            account["lifecycle"] = lifecycle_details(account)
            expired = bool(account.get("expires_on") and account["expires_on"] <= utcnow().date().isoformat())
            account["status"] = account_status(
                deleted=bool(account["deleted_at"]), disabled=account["disabled"], expired=expired
            )
            if "groups" in changes:
                self.sync_account_groups(state, account)
            account["readonly_reasons"] = [
                r for r in account.get("readonly_reasons", []) if r != "account_deleted"
            ]
            if account.get("deleted_at"):
                account["readonly_reasons"].append("account_deleted")
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
                    gid=max((g["gid"] for g in state["system_groups"]), default=999) + 1,
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
                    if "name" in changes and changes["name"] != group["name"]:
                        if any(g["name"] == changes["name"] for g in state["system_groups"]):
                            raise DomainError("group_exists", "system group exists")
                        for account in state["accounts"]:
                            if account["gid"] == group["gid"]:
                                account["primary_group"] = changes["name"]
                            account["groups"] = [
                                changes["name"] if name == group["name"] else name
                                for name in account["groups"]
                            ]
                        group["id"] = changes["name"]
                    group.update(changes)
                    group["revision"] += 1
                del state["previews"][p["token"]]
            if "members" in changes:
                for account in state["accounts"]:
                    memberships = set(account["groups"]) - {group["name"]}
                    if account["username"] in group["members"] or account["gid"] == group["gid"]:
                        memberships.add(group["name"])
                    account["groups"] = sorted(memberships)
            self.event(state, p, "system_group." + p["action"], group["id"], None, group)
            return describe_group(group, state["accounts"], state["shares"])
        if method == "refresh_storage":
            state["directory_collected_at"] = utcnow().isoformat()
            for share in state["shares"]:
                share.update(collected_at=state["directory_collected_at"], usage_status="demo", usage_bytes=share.get("usage_bytes") or 0)
            self.event(state, p, "storage.refresh", "directories", None, None)
            return dict(scanning=False)
        if method == "storage_snapshot":
            return dict(
                filesystems=[
                    dict(
                        id="demo-fs",
                        path="/data",
                        fstype="demo",
                        total=1024**4,
                        available=700 * 1024**3,
                        error=None,
                    )
                ],
                users=[
                    dict(
                        account_id=a["id"],
                        username=a["username"],
                        account_status=a.get("status"),
                        deleted_at=a.get("deleted_at"),
                        home_bytes=2 * 1024**3 if state.get("directory_collected_at") else None,
                        data_bytes=30 * 1024**3 if state.get("directory_collected_at") else None,
                        collected_at=state.get("directory_collected_at"),
                        status="demo",
                    )
                    for a in state["accounts"]
                ],
                shares=state["shares"],
                alerts=[],
                collected_at=utcnow().isoformat(),
                source="demo",
                directory_collected_at=state.get("directory_collected_at"),
                scanning=False,
            )
        if method == "login_events_since":
            return dict(
                items=state["login_events"],
                total=len(state["login_events"]),
                coverage="演示模式：无真实登录日志",
            )
        if method == "preview_share_change":
            changes = p.get("changes", {})
            if p.get("action") == "create":
                name = validate_name(changes["name"])
                candidate = dict(id="new-share:" + name, revision=1)
                result = self.preview(state, "share", candidate, "create", changes=changes)
                current = None
                proposed = dict(changes, path="/data/shared/" + name)
                action = "create"
            else:
                share = self.find(state, "shares", p["id"])
                result = self.preview(state, "share", share, "update", changes=changes)
                current = {
                    key: share.get(key)
                    for key in ("name", "path", "reader_group", "writer_group", "notes", "status")
                }
                current["path"] = current["path"] or "/data/shared/" + share["name"]
                proposed = dict(current, **changes)
                action = "update"
            if member_changes is not None:
                state["previews"][result["token"]]["member_scope"] = member_scope
                if current is not None:
                    current = {k:v for k,v in current.items() if k not in {"reader_group","writer_group"}}
                    current["members"] = member_scope["current"]
                proposed = {k:v for k,v in proposed.items() if k not in {"reader_group","writer_group"}}
                proposed["members"] = member_changes
                result["migration"] = bool(p.get("id") and share.get("access_mode") != "members")
            result.update(
                kind="share",
                action=action,
                changes=changes,
                current=current,
                proposed=proposed,
                path=proposed["path"],
                impact="Shared directory access and inheritance are simulated; user files are retained.",
            )
            return result
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
            if member_changes is not None:
                if preview.get("member_scope") != member_scope:
                    raise DomainError("scope_changed", "Directory membership changed since preview", 409)
                for field, permission in [("reader_group", "read"), ("writer_group", "write")]:
                    name = member_names[field]
                    group = next((g for g in state["system_groups"] if g["name"] == name), None)
                    if group is None:
                        group = dict(id=name, name=name, gid=max(g["gid"] for g in state["system_groups"])+1, members=[], revision=1, managed=True, protected=True, share_owner=fields["name"])
                        state["system_groups"].append(group)
                    group["members"] = [m["username"] for m in member_changes if m["permission"] == permission]
                    group["revision"] += 1
                    for account in state["accounts"]:
                        memberships = set(account["groups"]) - {name}
                        if account["username"] in group["members"]:
                            memberships.add(name)
                        account["groups"] = sorted(memberships)
                fields = dict(fields, **member_names, access_mode="members", members=member_changes)
            else:
                if not p.get("id"):
                    require_groups([fields["reader_group"], fields["writer_group"]])
                known = {g["name"] for g in state["system_groups"]}
                if fields["reader_group"] not in known or fields["writer_group"] not in known:
                    raise DomainError("group_missing", "共享授权组不存在", 422)
                if fields["reader_group"] == fields["writer_group"]:
                    raise DomainError("invalid_share", "读写组与只读组必须不同", 422)
            if p.get("id"):
                share.update(fields if member_changes is not None else changes)
                share["revision"] += 1
            else:
                share = dict(
                    id=str(uuid4()),
                    path="/data/shared/" + fields["name"],
                    status="active",
                    revision=1,
                    usage_bytes=None,
                    **fields,
                )
                state["shares"].append(share)
            del state["previews"][p["token"]]
            self.event(state, p, "share.update", share["id"], None, share)
            return share
        raise DomainError("unsupported", "未支持的 agent 方法：" + method, 422)
