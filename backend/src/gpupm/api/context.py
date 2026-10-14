import threading
import time
from datetime import timedelta

from sqlalchemy import select

from gpupm.db.models import AuditLog, ManagedUser, ManagementGroup, Setting, TaskConfig
from gpupm.db.session import columns
from gpupm.domain.rules import deadline, parse_time, priority_key, utcnow
from gpupm.errors import DomainError


class Context:
    def __init__(self, sessions, agent, config):
        self.sessions, self.agent, self.config = sessions, agent, config
        self.lock = threading.RLock()
        self.cached = None
        self.last_fetch = 0
        self.agent_error = None

    def invalidate(self):
        with self.lock:
            self.last_fetch = 0

    def settings(self):
        with self.sessions() as db:
            values = db.get(Setting, 1).values.copy()
        return dict(
            **values,
            home_base=self.config.home_base,
            data_base=self.config.data_base,
            share_base=self.config.data_base + "/shared",
            mode=self.config.mode,
        )

    def audit(
        self,
        db,
        actor,
        action,
        target,
        before=None,
        after=None,
        result="succeeded",
        reason="",
        event_id=None,
        occurred_at=None,
    ):
        db.add(
            AuditLog(
                time=parse_time(occurred_at).isoformat() if occurred_at else utcnow().isoformat(),
                actor=actor,
                action=action,
                target=str(target),
                before=before,
                after=after,
                result=result,
                reason=reason,
                event_id=event_id,
            )
        )

    def synchronize_events(self):
        with self.lock:
            self._synchronize_events()

    def _synchronize_events(self):
        try:
            with self.sessions() as db:
                cursor = db.scalar(
                    select(AuditLog.event_id)
                    .where(AuditLog.event_id.is_not(None))
                    .order_by(AuditLog.id.desc())
                    .limit(1)
                )
            response = self.agent.call("audit_since", {"cursor": cursor, "limit": 100})
            events = response.get("items", []) if isinstance(response, dict) else response
            with self.sessions.begin() as db:
                existing = set(db.scalars(select(AuditLog.event_id).where(AuditLog.event_id.is_not(None))))
                for event in events:
                    if event["id"] not in existing:
                        self.audit(
                            db,
                            event.get("actor", "system"),
                            event["action"],
                            event["target"],
                            event.get("before"),
                            event.get("after"),
                            event.get("result", "succeeded"),
                            event.get("reason", ""),
                            event["id"],
                            event.get("time"),
                        )
                        existing.add(event["id"])
        except DomainError:
            pass

    def heartbeat(self):
        with self.lock:
            settings = self.settings()
            values = {
                k: v for k, v in settings.items() if k not in {"mode", "home_base", "data_base", "share_base"}
            }
            self.agent.call("configure", {"settings": values})
            snapshot = self.snapshot(force=True)
            if not snapshot["stale"]:
                for task in snapshot.get("tasks", []):
                    if task["status"] == "finished" or not task.get("is_human", False):
                        continue
                    with self.sessions() as db:
                        existing = db.get(TaskConfig, task["id"])
                        if existing and (
                            existing.status != "applied" or existing.revision == task["revision"]
                        ):
                            continue
                        policy = existing.policy.copy() if existing else {}
                    try:
                        applied = self.agent.call(
                            "apply_task_policy",
                            {
                                "task_id": task["id"],
                                "revision": task["revision"],
                                "policy": policy,
                                "actor": "system-policy-sync",
                            },
                        )
                    except DomainError:
                        continue
                    with self.sessions.begin() as db:
                        record = db.get(TaskConfig, task["id"])
                        if record is None:
                            record = TaskConfig(
                                task_id=task["id"],
                                policy=policy,
                                status="applied",
                                revision=applied["revision"],
                            )
                            db.add(record)
                        else:
                            record.revision = applied["revision"]
            with self.sessions() as db:
                versions = {
                    p.task_id: p.revision
                    for p in db.scalars(select(TaskConfig).where(TaskConfig.status == "applied"))
                }
            settings = self.settings()
            values = {
                k: v for k, v in settings.items() if k not in {"mode", "home_base", "data_base", "share_base"}
            }
            self.agent.call("heartbeat", {"policy_versions": versions, "settings": values})
            self.synchronize_events()

    def snapshot(self, force=False):
        with self.lock:
            now = time.monotonic()
            if (
                force
                or self.cached is None
                or now - self.last_fetch >= self.settings()["scan_interval_seconds"]
            ):
                try:
                    self.cached = self.agent.call("snapshot", {})
                    self.agent_error = None
                except DomainError as exc:
                    self.agent_error = exc.message
                    if self.cached is None:
                        self.cached = dict(
                            gpus=[],
                            tasks=[],
                            accounts=[],
                            system_groups=[],
                            source="host",
                            collected_at=None,
                            stale=True,
                            errors=[exc.message],
                        )
                self.last_fetch = now
            data = dict(self.cached)
            collected = parse_time(data.get("collected_at"))
            data["stale"] = bool(
                data.get("stale")
                or self.agent_error
                or collected is None
                or utcnow() - collected
                > timedelta(seconds=max(15, self.settings()["scan_interval_seconds"] * 3))
            )
            return data

    def users(self):
        snap = self.snapshot()
        with self.sessions.begin() as db:
            for account in snap.get("accounts", []):
                uid = account["uid"]
                lifecycle_id = account.get("lifecycle_id", account["id"])
                user = db.get(ManagedUser, uid)
                if not user:
                    db.add(
                        ManagedUser(
                            uid=uid,
                            username=account["username"],
                            account_id=lifecycle_id,
                            group_id=1,
                            priority=50,
                            notes="",
                        )
                    )
                elif user.account_id and user.account_id != lifecycle_id:
                    self.audit(
                        db,
                        "system",
                        "user.identity_changed",
                        uid,
                        columns(user),
                        {"account_id": lifecycle_id},
                    )
                    user.account_id = lifecycle_id
                    user.username = account["username"]
                    user.group_id, user.priority, user.notes = 1, 50, ""
                else:
                    user.username = account["username"]
                    user.account_id = lifecycle_id
            for task in snap.get("tasks", []):
                if db.get(ManagedUser, task["uid"]) is None:
                    db.add(
                        ManagedUser(
                            uid=task["uid"], username=task["username"], group_id=1, priority=50, notes=""
                        )
                    )
        with self.sessions() as db:
            human_uids = {a["uid"] for a in snap.get("accounts", []) if a.get("is_human", False)}
            return [
                dict(columns(u), is_human=u.uid in human_uids)
                for u in db.scalars(select(ManagedUser).order_by(ManagedUser.uid))
            ]

    def require_human(self, uid):
        accounts = self.agent.call("list_accounts")
        if not any(a["uid"] == uid and a.get("is_human", False) for a in accounts):
            raise DomainError("non_human_readonly", "非 human 账号及其任务仅供查看", 403)

    def tasks(self):
        snap = self.snapshot()
        self.users()
        result = []
        now = utcnow()
        with self.sessions() as db:
            groups = {g.id: g for g in db.scalars(select(ManagementGroup))}
            users = {u.uid: u for u in db.scalars(select(ManagedUser))}
            settings = self.settings()
            for original in snap["tasks"]:
                task = dict(original)
                task["is_human"] = bool(original.get("is_human", False))
                user = users[task["uid"]]
                group = groups[user.group_id]
                policy = db.get(TaskConfig, task["id"])
                if policy:
                    task.update(policy.policy)
                    task["protected"] = bool(original.get("protected") or policy.policy.get("protected"))
                    task["policy_status"] = (
                        policy.status if policy.status != "applied" else task.get("policy_status", "applied")
                    )
                    task["revision"] = max(task.get("revision", 1), policy.revision)
                task["stale"] = bool(snap["stale"])
                task.setdefault("orphan_reminder", settings["default_orphan_reminder"])
                task.setdefault("orphan_wait_seconds", settings["default_orphan_wait_seconds"])
                task.setdefault("priority", 50)
                task.setdefault("notes", "")
                task.setdefault("protected", False)
                task.setdefault("expires_at", None)
                task.setdefault("max_runtime_seconds", None)
                task.setdefault("deadline_action", settings["default_deadline_action"])
                task.setdefault("policy_status", "applied")
                task.setdefault("revision", 1)
                task.setdefault("context", [])
                task.setdefault("anomalies", [])
                started = parse_time(task["started_at"])
                end = deadline(started, task["max_runtime_seconds"], parse_time(task["expires_at"]))
                task["group_id"] = user.group_id
                task["priority_tuple"] = priority_key(group.priority, user.priority, task["priority"])
                task["deadline_at"] = end.isoformat() if end else None
                task["overdue"] = bool(end and end <= now and task["status"] != "finished")
                task["remaining_seconds"] = (end - now).total_seconds() if end else None
                task["runtime_seconds"] = max(0, (now - started).total_seconds())
                memory_values = [v for m in task["members"] for v in m.get("gpu_memory", {}).values()]
                task["memory_used"] = None if any(v is None for v in memory_values) else sum(memory_values)
                result.append(task)
        return result, snap

    def task(self, ident):
        tasks, _ = self.tasks()
        for task in tasks:
            if task["id"] == ident:
                return task
        raise DomainError("not_found", "任务不存在", 404)
