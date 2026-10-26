import threading
import time
from datetime import timedelta

from sqlalchemy import select

from gpupm.db.models import AuditLog, ManagedUser, ManagementGroup, Setting, TaskConfig
from gpupm.db.session import columns
from gpupm.domain.rules import task_timing, parse_time, priority_key, utcnow
from gpupm.domain.schemas import AccountProfile
from gpupm.errors import DomainError
from gpupm.domain.settings import ignored_process, task_defaults
from gpupm.domain.user_policy import resolve_policy, policy_editable


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

    def policy_settings(self):
        with self.sessions() as db:
            return db.get(Setting, 1).values.copy()

    def settings(self):
        values = self.policy_settings()
        roots = self.agent.call("health").get("roots", {})
        names = ("home_base", "data_base", "share_base")
        if any(not isinstance(roots.get(name), str) or not roots[name].startswith("/") for name in names):
            raise DomainError("initialization_unverified", "agent initialization roots are unavailable", 503)
        return dict(**values, **{name: roots[name] for name in names}, mode=self.config.mode)

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

    def legacy_policy_context(self, db, task, user, group):
        migrated = db.scalar(
            select(AuditLog)
            .where(AuditLog.action == "user.policy_migration", AuditLog.target == str(user.uid))
            .order_by(AuditLog.id.desc())
        )
        user_priority = user.priority
        group_id = group.id
        if migrated:
            old = migrated.before
            group_id, user_priority = old["group_id"], old["priority"]
            group = db.get(ManagementGroup, group_id)
        group_event = db.scalar(
            select(AuditLog)
            .where(AuditLog.action == "group.policy_migration", AuditLog.target == str(group_id))
            .order_by(AuditLog.id.desc())
        )
        old_group = group_event.before if group_event else (columns(group) if group else {})
        return (
            list(priority_key(old_group.get("priority", 50), user_priority, task.get("priority", 50))),
            {"group_id": group_id, "group_name": old_group.get("name", str(group_id))},
        )

    def reconcile_policy(self, db, record, task, source):
        # A lost RPC response is ambiguous: observe root state, never replay an unconfirmed edit.
        attempt = db.scalar(
            select(AuditLog)
            .where(AuditLog.action == "task.policy_attempt", AuditLog.target == task["id"])
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
        candidate = attempt.after if attempt else None
        if not (
            candidate
            and candidate.get("revision") == record.revision
            and candidate.get("uid") == task["uid"]
            and candidate.get("started_at") == task["started_at"]
        ):
            candidate = None
        keys = set(record.policy) | (set(candidate["policy"]) if candidate else set())
        if not keys or any(k not in task for k in keys):
            return
        actual = {k: task[k] for k in keys}
        revision = task["revision"]
        if source == "host" and task["status"] != "finished" and not task.get("policy_confirmed_at"):
            # Very old failed records may never have registered with root. Register only observed values.
            try:
                revision = self.agent.call(
                    "apply_task_policy",
                    {"task_id": task["id"], "revision": revision, "policy": actual,
                     "actor": "system-policy-reconcile"},
                )["revision"]
            except DomainError:
                return
        before = record.policy
        if (
            candidate
            and task["revision"] == candidate["revision"] + 1
            and actual == candidate["policy"]
        ):
            record.policy_sources = candidate["sources"]
            record.priority_snapshot = candidate["priority_snapshot"]
        else:
            record.policy_sources = {
                k: (record.policy_sources or {}).get(k, "legacy")
                if k in before and before[k] == actual[k] else "legacy"
                for k in actual
            }
            if actual.get("priority") != before.get("priority"):
                record.priority_snapshot = None
        record.policy = actual
        record.revision = revision
        record.status = "applied"
        self.audit(
            db, "system-policy-sync", "task.policy_reconcile", task["id"], before, actual,
            "succeeded", "Reconciled with observed agent policy; no edit replayed",
        )
        db.commit()
        self.invalidate()

    def heartbeat(self, expected_task=None):
        with self.lock:
            settings = self.policy_settings()
            values = {
                k: v for k, v in settings.items() if k not in {"mode", "home_base", "data_base", "share_base"}
            }
            self.agent.call("configure", {"settings": values})
            snapshot = self.snapshot(force=True)
            if expected_task:
                ident, revision = expected_task
                current = next((t for t in snapshot.get("tasks", []) if t["id"] == ident), None)
                if snapshot["stale"] or not current or current["revision"] != revision:
                    raise DomainError("revision_conflict", "任务版本已改变，请重新加载", 409)
            if not snapshot["stale"]:
                user_rows = {u["uid"]: u for u in self.users()}
                for task in snapshot.get("tasks", []):
                    if not task.get("is_human", False):
                        continue
                    with self.sessions() as db:
                        existing = db.get(TaskConfig, task["id"])
                        if existing and existing.status != "applied":
                            self.reconcile_policy(db, existing, task, snapshot.get("source"))
                            continue
                        if existing and not existing.policy_sources:
                            complete = {k: task.get(k, v) for k, v in task_defaults(settings).items()}
                            explicit = existing.policy.copy()
                            complete.update(explicit)
                            existing.policy = complete
                            existing.policy_sources = {
                                k: "task" if k in explicit else "legacy" for k in complete
                            }
                            user = db.get(ManagedUser, task["uid"])
                            group = db.get(ManagementGroup, user.group_id)
                            existing.priority_snapshot, existing.assignment_snapshot = (
                                self.legacy_policy_context(db, task, user, group)
                            )
                            db.commit()
                        if existing and (
                            existing.status != "applied" or existing.revision == task["revision"]
                        ):
                            continue
                        if existing:
                            policy = existing.policy.copy()
                            sources = existing.policy_sources
                            ranking = existing.priority_snapshot
                            assignment = existing.assignment_snapshot
                        else:
                            user = db.get(ManagedUser, task["uid"])
                            group = db.get(ManagementGroup, user.group_id)
                            setting = db.get(Setting, 1)
                            legacy = parse_time(task["started_at"]) <= parse_time(setting.policy_epoch)
                            if (
                                legacy
                                or task["status"] == "finished"
                                or task.get("policy_parent_task_id")
                                or not user_rows[task["uid"]]["policy_editable"]
                            ):
                                policy = {k: task.get(k, v) for k, v in task_defaults(setting.values).items()}
                                policy.update(
                                    {k: task[k] for k in ("name", "notes", "expires_at") if k in task}
                                )
                                sources = {k: "legacy" for k in policy}
                                ranking, assignment = (
                                    self.legacy_policy_context(db, task, user, group)
                                    if legacy
                                    else (None, {"group_id": group.id, "group_name": group.name})
                                )
                                parent = (
                                    db.get(TaskConfig, task["policy_parent_task_id"])
                                    if task.get("policy_parent_task_id")
                                    else None
                                )
                                if parent:
                                    sources = parent.policy_sources.copy()
                                    ranking = parent.priority_snapshot
                                    assignment = parent.assignment_snapshot
                            else:
                                policy, sources = resolve_policy(setting.values, group, user)
                                policy["cleanup_orphans"] = False
                                ranking = None
                                assignment = {"group_id": group.id, "group_name": group.name}
                    try:
                        applied = (
                            {"revision": task["revision"]}
                            if task["status"] == "finished"
                            else self.agent.call(
                                "apply_task_policy",
                                {
                                    "task_id": task["id"],
                                    "revision": task["revision"],
                                    "policy": policy,
                                    "actor": "system-policy-sync",
                                },
                            )
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
                                policy_sources=sources,
                                priority_snapshot=ranking,
                                assignment_snapshot=assignment,
                            )
                            db.add(record)
                        else:
                            record.revision = applied["revision"]
                    self.invalidate()
            with self.sessions() as db:
                versions = {
                    p.task_id: p.revision
                    for p in db.scalars(select(TaskConfig).where(TaskConfig.status == "applied"))
                }
            settings = self.policy_settings()
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
                or now - self.last_fetch >= self.policy_settings()["scan_interval_seconds"]
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
                > timedelta(seconds=max(15, self.policy_settings()["scan_interval_seconds"] * 3))
            )
            return data

    def users(self):
        snap = self.snapshot()
        with self.sessions.begin() as db:
            for account in snap.get("accounts", []):
                uid = account["uid"]
                lifecycle_id = account.get("lifecycle_id", account["id"])
                user = db.get(ManagedUser, uid)
                group_id, priority = 1, 50
                if not user or (user.account_id and user.account_id != lifecycle_id):
                    profile = (account.get("creation") or {}).get("profile")
                    if profile is not None:
                        try:
                            profile = AccountProfile.model_validate(profile)
                        except ValueError:
                            profile = None
                        if profile is not None:
                            priority = profile.priority
                            if db.get(ManagementGroup, profile.group_id):
                                group_id = profile.group_id
                if not user:
                    db.add(
                        ManagedUser(
                            uid=uid,
                            username=account["username"],
                            account_id=lifecycle_id,
                            group_id=group_id,
                            priority=priority,
                            personal_policy={"priority": priority} if priority != 50 else {},
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
                    user.group_id, user.priority, user.notes = group_id, priority, ""
                    user.personal_policy = {"priority": priority} if priority != 50 else {}
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
            accounts = {a["uid"]: a for a in snap.get("accounts", [])}
            groups = {g.id: g for g in db.scalars(select(ManagementGroup))}
            settings = db.get(Setting, 1).values
            result = []
            for user in db.scalars(select(ManagedUser).order_by(ManagedUser.uid)):
                group = groups[user.group_id]
                policy, sources = resolve_policy(settings, group, user)
                account = accounts.get(user.uid, {})
                result.append(
                    dict(
                        columns(user),
                        is_human=bool(account.get("is_human")),
                        account_ref=account.get("id"),
                        group_name=group.name,
                        effective_policy=policy,
                        policy_sources=sources,
                        policy_editable=policy_editable(account),
                    )
                )
            return result

    def require_human(self, uid):
        accounts = self.agent.call("list_accounts")
        if not any(a["uid"] == uid and a.get("is_human", False) for a in accounts):
            raise DomainError("non_human_readonly", "非 human 账号及其任务仅供查看", 403)

    def require_policy_user(self, uid):
        self.require_human(uid)
        account = next((a for a in self.agent.call("list_accounts") if a["uid"] == uid), None)
        if not policy_editable(account):
            raise DomainError("policy_readonly", "仅正常启用的纳管人员账号可修改任务策略", 403)

    def tasks(self):
        snap = self.snapshot()
        user_rows = {u["uid"]: u for u in self.users()}
        result = []
        now = utcnow()
        with self.sessions() as db:
            users = {u.uid: u for u in db.scalars(select(ManagedUser))}
            settings = self.policy_settings()
            for original in snap["tasks"]:
                task = dict(original)
                members = original["members"]
                task["members"] = [
                    m for m in members if not ignored_process(m, settings["ignored_task_executables"])
                ]
                if task.get("ignored") or (members and not task["members"]):
                    continue
                task["is_human"] = bool(original.get("is_human", False))
                task["policy_editable"] = user_rows[task["uid"]]["policy_editable"]
                user = users[task["uid"]]
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
                task["group_id"] = user.group_id
                task["group_name"] = db.get(ManagementGroup, user.group_id).name
                task["policy_assignment"] = policy.assignment_snapshot if policy else {}
                task["priority_tuple"] = (
                    tuple(policy.priority_snapshot)
                    if policy and policy.priority_snapshot
                    else (task["priority"], task["priority"], task["priority"])
                )
                task["policy_sources"] = policy.policy_sources if policy else {}
                task.update(task_timing(task, now))
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
