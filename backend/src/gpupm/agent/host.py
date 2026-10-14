"""Persistent root-only host authority, shared by RPC and periodic collection."""

import copy
import json
import os
import secrets
import signal
import stat
import sqlite3
import threading
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from gpupm.agent.accounts import Accounts, run, SENSITIVE_GROUPS
from gpupm.agent.processes import (
    collect,
    group_processes,
    identity_key,
    shell_process,
    signal_identity,
    process_state,
    residual_ready,
    residual_status,
    valid_leader_identity,
)
from gpupm.domain.rules import deadline, parse_time, utcnow
from gpupm.domain.settings import (
    DEFAULT_SETTINGS,
    task_defaults,
    validate_ignored_executables,
    ignored_process,
)
from gpupm.errors import DomainError


class AgentService:
    def __init__(
        self, config, collector=collect, executor=run, signaler=signal_identity, process_checker=process_state
    ):
        self.config = dict(config)
        validate_ignored_executables(
            config.get("ignored_task_executables", DEFAULT_SETTINGS["ignored_task_executables"])
        )
        self.collector = collector
        self.signaler = signaler
        self.process_checker = process_checker
        self.path = Path(config.get("store_path", "/var/lib/gpupm/agent.sqlite"))
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
                or info.st_mode & 0o077
            ):
                raise DomainError("unsafe_store", "agent store must be a private owned regular file", 403)
        finally:
            os.close(fd)
        self.lock = threading.RLock()
        self.accounts = Accounts(config, executor, self.event)
        self.workers = {}
        self.storage_scan_lock = threading.Lock()
        self.storage_worker = None
        self.interval_changed = threading.Condition()
        self.settings_version = 0
        self.stop = threading.Event()
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY,data TEXT NOT NULL)")
            initial = dict(
                tasks=[],
                gpus=[],
                accounts={},
                groups={},
                shares=[],
                quotas={},
                jobs={},
                previews={},
                idempotency={},
                events=[],
                excluded=[],
                settings={},
                login_events=[],
                collected_at=None,
                errors=[],
                storage=None,
            )
            db.execute("INSERT OR IGNORE INTO state VALUES(1,?)", (json.dumps(initial),))
        self.path.chmod(0o600)
        # Interrupted jobs never blindly replay a signal after a restart.
        with self.lock, self.database() as db:
            state = self.load(db)
            state["settings"].setdefault(
                "ignored_task_executables",
                self.config.get("ignored_task_executables", DEFAULT_SETTINGS["ignored_task_executables"]),
            )
            validate_ignored_executables(state["settings"]["ignored_task_executables"])
            for task in state["tasks"]:
                task["policy_status"] = "awaiting_sync"
            state["last_heartbeat"] = None
            for job in state["jobs"].values():
                if job["status"] in {"queued", "running"}:
                    job["status"] = "interrupted"
                    for target in job.get("targets", []):
                        result = self.process_checker(target["identity"])
                        job["results"].append(
                            dict(identity=target["identity"], status=result, recovered=True)
                        )
                    if job.get("actor") == "policy":
                        task = next((t for t in state["tasks"] if t["id"] == job.get("task_id")), None)
                        if task:
                            task.pop("deadline_handled_revision", None)
                            task.pop("cleanup_handled_revision", None)
                            task["recovery_attempt"] = task.get("recovery_attempt", 0) + 1
                    self.event(state, {}, "task.terminate", job["id"], None, job, "interrupted")
            self.normalize_cleanup_status(state)
            self.save(db, state)

    def runtime_setting(self, key, default):
        with self.lock, self.database() as db:
            return self.load(db)["settings"].get(key, self.config.get(key, default))

    def wait_interval(self, key, default):
        started = time.monotonic()
        version = -1
        interval = default
        while not self.stop.is_set():
            current = self.settings_version
            if current != version:
                interval = self.runtime_setting(key, default)
                version = current
            remaining = interval - (time.monotonic() - started)
            if remaining <= 0:
                return
            # Read settings before taking the condition to preserve configure’s lock order.
            with self.interval_changed:
                if self.settings_version != version:
                    continue
                self.interval_changed.wait(timeout=min(remaining, 1))

    def policy_freshness(self, state):
        interval = state["settings"].get("scan_interval_seconds", self.config.get("scan_interval_seconds", 5))
        return max(self.config.get("policy_freshness_seconds", 30), 3 * interval)

    def database(self):
        return sqlite3.connect(self.path, timeout=30)

    def load(self, db):
        return json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])

    def save(self, db, state):
        db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state),))

    def event(self, state, p, action, target, before, after, result="succeeded"):
        # Credentials never enter durable audit payloads.
        def redact(value):
            if isinstance(value, dict):
                return {
                    k: redact(v)
                    for k, v in value.items()
                    if k not in {"password", "baseline", "token", "password_hash", "public_keys"}
                }
            if isinstance(value, list):
                return [redact(v) for v in value]
            return value

        before = redact(before)
        after = redact(after)
        for key, value in [("before", before), ("after", after)]:
            serialized = json.dumps(value, ensure_ascii=False)
            if len(serialized.encode()) > 128 * 1024:
                import hashlib

                replacement = dict(
                    truncated=True,
                    sha256=hashlib.sha256(serialized.encode()).hexdigest(),
                    excerpt=serialized[:8192],
                )
                if key == "before":
                    before = replacement
                else:
                    after = replacement
        state["events"].append(
            dict(
                id=str(uuid4()),
                time=utcnow().isoformat(),
                actor=p.get("actor", "system"),
                action=action,
                target=str(target),
                before=redact(before),
                after=redact(after),
                result=result,
                reason=p.get("reason", ""),
            )
        )

    def normalize_cleanup_status(self, state):
        active = {
            j.get("task_id")
            for j in state["jobs"].values()
            if j.get("residual_only") and j["status"] in {"queued", "running"}
        }
        for task in state["tasks"]:
            if task["status"] == "cleaning" and task["id"] not in active:
                task["status"] = "finalizing"

    def refresh(self, state):
        for task in state["tasks"]:
            members = task["members"]
            removed = [
                m for m in members if ignored_process(m, state["settings"]["ignored_task_executables"])
            ]
            if removed:
                task["ignored_members"] = task.get("ignored_members", []) + removed
                task["members"] = [m for m in members if m not in removed]
                task["revision"] += 1
                task["ignored"] = not task["members"]
                if task["ignored"]:
                    task.update(status="finished", overdue=False, anomalies=[])
        self.normalize_cleanup_status(state)
        try:
            gpus, processes, errors = self.collector()
        except Exception as exc:
            state["errors"] = [dict(code="collector_failed", message=str(exc))]
            state["stale"] = True
            for task in state["tasks"]:
                task["is_human"] = self.accounts.is_human(task["uid"])
            return
        state["gpus"] = gpus
        state["errors"] = errors
        state["stale"] = bool(errors)
        if errors:
            return
        old_ids = {t["id"] for t in state["tasks"]}
        try:
            if any(
                not valid_leader_identity(i) for t in state["tasks"] for i in t.get("leader_identities", [])
            ):
                raise ValueError("invalid persisted leader identity")
            state["tasks"] = group_processes(
                processes, state["tasks"], state["excluded"], state["settings"]["ignored_task_executables"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            state["errors"] = [dict(code="membership_collection_incomplete", message=str(exc))]
            state["stale"] = True
            return
        for task in state["tasks"]:
            if task["id"] not in old_ids:
                task.update(task_defaults(state["settings"]))
        for task in state["tasks"]:
            for field in ("orphan_reminder", "orphan_wait_seconds"):
                task.setdefault(field, task_defaults(state["settings"])[field])
            task["is_human"] = self.accounts.is_human(task["uid"])
            protected_uids = {0, self.config.get("api_uid")}
            if (
                task["uid"] in protected_uids
                or task["username"] in self.config.get("maintenance_users", [])
                or task["uid"] < 1000
            ):
                task["protected"] = True
            residual_status(
                task,
                utcnow(),
                any(
                    j.get("residual_only")
                    and j.get("task_id") == task["id"]
                    and j["status"] in {"queued", "running"}
                    for j in state["jobs"].values()
                ),
            )
            task["memory_used"] = sum(
                v for p in task["members"] for v in p["gpu_memory"].values() if v is not None
            )
            if any(v is None for p in task["members"] for v in p["gpu_memory"].values()):
                task["memory_used"] = None
            task["runtime_seconds"] = max(0, int((utcnow() - parse_time(task["started_at"])).total_seconds()))
            due = deadline(
                parse_time(task["started_at"]),
                task.get("max_runtime_seconds"),
                parse_time(task.get("expires_at")),
            )
            task["deadline_at"] = due.isoformat() if due else None
            task["remaining_seconds"] = int((due - utcnow()).total_seconds()) if due else None
            task["overdue"] = bool(due and due <= utcnow() and task["status"] == "running")
        state["collected_at"] = utcnow().isoformat()

    def find(self, state, kind, ident):
        for item in state[kind]:
            if item["id"] == ident:
                return item
        raise DomainError("not_found", f"{kind} target not found", 404)

    def revision(self, item, p):
        if p.get("revision") != item["revision"]:
            raise DomainError("revision_conflict", "configuration or membership changed")

    def preview(self, state, kind, item, action, changes=None, targets=None, excluded=None):
        token = secrets.token_urlsafe(32)
        value = dict(
            token=token,
            expires_at=(utcnow() + timedelta(seconds=30)).isoformat(),
            kind=kind,
            id=item["id"],
            action=action,
            revision=item["revision"],
            changes=changes or {},
            targets=targets or [],
            excluded=excluded or [],
        )
        if kind in {"account", "group"}:
            value["host_scope"] = {
                k: item.get(k)
                for k in (
                    "username",
                    "uid",
                    "gid",
                    "home",
                    "shell",
                    "groups",
                    "primary_group",
                    "lifecycle_id",
                    "name",
                    "members",
                    "managed",
                    "protected",
                )
            }
        state["previews"][token] = value
        return copy.deepcopy(value)

    def checked(self, state, p, kind, item, action, changes=None):
        preview = state["previews"].get(p.get("token"))
        if (
            not preview
            or preview["kind"] != kind
            or preview["id"] != item["id"]
            or preview["action"] != action
        ):
            raise DomainError("invalid_preview", "valid scope preview required")
        if parse_time(preview["expires_at"]) <= utcnow() or preview["revision"] != item["revision"]:
            raise DomainError("scope_changed", "preview expired or scope changed")
        if p.get("revision", item["revision"]) != item["revision"]:
            raise DomainError("revision_conflict", "revision changed")
        if preview.get("host_scope") and preview["host_scope"] != {
            k: item.get(k) for k in preview["host_scope"]
        }:
            raise DomainError("scope_changed", "native account/group scope changed")
        if changes is not None and preview["changes"] != changes:
            raise DomainError("scope_changed", "preview changes differ")
        return preview

    def require_human_task(self, task):
        if not self.accounts.is_human(task["uid"]):
            raise DomainError("non_human_readonly", "only human tasks are editable", 403)

    def targets(self, task, identity=None, residual_only=False):
        self.require_human_task(task)
        if task.get("ignored") or task["protected"] or task["status"] == "finished":
            raise DomainError("protected", "task protected or finished", 403)
        if residual_only and not residual_ready(task, utcnow()):
            raise DomainError("residual_not_ready", "residual cleanup conditions changed", 409)
        targets = []
        excluded = []
        for member in task["members"]:
            if identity and member["identity"] != identity:
                continue
            if (
                member["uid"] != task["uid"]
                or not self.accounts.is_human(member["uid"])
                or member["uid"] < 1000
                or member["uid"] == self.config.get("api_uid")
                or member["username"] in self.config.get("maintenance_users", [])
                or shell_process(member)
            ):
                excluded.append(dict(identity=member["identity"], reason="protected"))
            elif member["status"] in {"zombie", "Z"}:
                excluded.append(dict(identity=member["identity"], reason="zombie; parent must reap"))
            elif member["ppid"] == 1 and not (residual_only or task.get("cleanup_orphans")):
                excluded.append(dict(identity=member["identity"], reason="orphan cleanup not authorized"))
            else:
                targets.append(member)
        if identity and not targets and not excluded:
            raise DomainError("identity_changed", "process is outside confirmed membership")
        return targets, excluded

    def call(self, method, params=None):
        p = params or {}
        mutation = method.startswith("execute_") or method == "apply_quota"
        if mutation and not self.config.get("allow_mutations", False):
            raise DomainError("mutations_disabled", "root config allow_mutations is false", 403)
        with self.lock, self.database() as db:
            state = self.load(db)
            try:
                result = self.dispatch(state, method, p)
            except (ValueError, TypeError, KeyError) as exc:
                raise DomainError("invalid_request", str(exc), 422) from exc
            except DomainError as exc:
                if mutation:
                    if method == "execute_account_change" and str(p.get("id")) in state["accounts"]:
                        meta = state["accounts"][str(p["id"])]
                        meta["revision"] += 1
                        meta["login_policy_status"] = "recheck_required"
                    self.event(state, p, method, p.get("id", p.get("task_id", "host")), None, None, exc.code)
                self.save(db, state)
                db.commit()
                raise
            self.save(db, state)
            return copy.deepcopy(result)

    def dispatch(self, state, method, p):
        if method == "health":
            return dict(status="ok", source="host", mutations=self.config.get("allow_mutations", False))
        if method == "heartbeat":
            versions = p.get("policy_versions", {})
            if not isinstance(versions, dict):
                raise DomainError("invalid_sync", "policy_versions must be a map", 422)
            for task in state["tasks"]:
                if task.get("policy_confirmed_at") and versions.get(task["id"]) == task["revision"]:
                    task["policy_status"] = "applied"
                    task["confirmed_revision"] = task["revision"]
                    task["policy_confirmed_at"] = utcnow().isoformat()
                elif task["status"] == "running":
                    task["policy_status"] = "awaiting_sync"
                    task["confirmed_revision"] = None
            state["last_heartbeat"] = utcnow().isoformat()
            if p.get("settings"):
                self.dispatch(state, "configure", dict(settings=p["settings"]))
            return dict(
                status="confirmed",
                source="host",
                confirmed=[t["id"] for t in state["tasks"] if t["policy_status"] == "applied"],
            )
        if method == "configure":
            settings = p.get("settings", {})
            if "ignored_task_executables" in settings:
                try:
                    validate_ignored_executables(settings["ignored_task_executables"])
                except ValueError as exc:
                    raise DomainError("invalid_settings", str(exc), 422) from exc
            permitted = DEFAULT_SETTINGS.keys()
            if set(settings) - permitted:
                raise DomainError("readonly_settings", "root config paths and mode are immutable", 403)
            for field in ("scan_interval_seconds", "term_grace_seconds", "storage_scan_interval_seconds"):
                if field in settings and (type(settings[field]) is not int or settings[field] < 1):
                    raise DomainError("invalid_settings", "positive interval required", 422)
            if "default_deadline_action" in settings and settings["default_deadline_action"] not in {
                "notify",
                "terminate",
            }:
                raise DomainError("invalid_settings", "default deadline action invalid", 422)
            if settings.get("default_max_runtime_seconds") is not None and (
                type(settings["default_max_runtime_seconds"]) is not int
                or not 1 <= settings["default_max_runtime_seconds"] <= 315360000
            ):
                raise DomainError("invalid_settings", "maximum runtime must be positive or null", 422)
            for field in ("default_task_protected", "default_cleanup_orphans", "default_orphan_reminder"):
                if field in settings and type(settings[field]) is not bool:
                    raise DomainError("invalid_settings", "task defaults require booleans", 422)
            if "default_task_priority" in settings and (
                type(settings["default_task_priority"]) is not int
                or not 0 <= settings["default_task_priority"] <= 100
            ):
                raise DomainError("invalid_settings", "task priority must be an integer from 0 to 100", 422)
            if "default_orphan_wait_seconds" in settings and (
                type(settings["default_orphan_wait_seconds"]) is not int
                or not 1 <= settings["default_orphan_wait_seconds"] <= 86400
            ):
                raise DomainError("invalid_settings", "orphan wait must be an integer 1..86400", 422)
            merged = dict(state["settings"], **settings)
            warning = merged.get("warning_percent", 80)
            critical = merged.get("critical_percent", 90)
            if type(warning) is not int or type(critical) is not int or not 0 < warning < critical <= 100:
                raise DomainError(
                    "invalid_settings", "storage thresholds require 0 < warning < critical <= 100", 422
                )
            allowlist_changed = merged.get("ignored_task_executables") != state["settings"].get(
                "ignored_task_executables"
            )
            state["settings"].update(settings)
            if allowlist_changed:
                state["previews"] = {k: v for k, v in state["previews"].items() if v.get("kind") != "task"}
                for task in state["tasks"]:
                    task["revision"] += 1
                    task["policy_status"] = "awaiting_sync"
                self.refresh(state)
            self.settings_version += 1
            with self.interval_changed:
                self.interval_changed.notify_all()
            return dict(status="applied", source="host")
        if method == "snapshot":
            self.refresh(state)
            return dict(
                gpus=state["gpus"],
                tasks=state["tasks"],
                accounts=self.accounts.list(state),
                system_groups=self.accounts.groups(state),
                collected_at=state["collected_at"],
                source="host",
                stale=state.get("stale", True),
                errors=state["errors"],
                capabilities=dict(
                    mutations=self.config.get("allow_mutations", False), pidfd=hasattr(os, "pidfd_open")
                ),
            )
        if method == "list_accounts":
            return self.accounts.list(state)
        if method == "list_system_groups":
            return self.accounts.groups(state)
        if method == "account_activity":
            return self.accounts.activity(state, p["id"])
        if method == "apply_task_policy":
            task = self.find(state, "tasks", p["task_id"])
            self.require_human_task(task)
            self.revision(task, p)
            policy = p["policy"]
            fields = {
                "name",
                "notes",
                "priority",
                "protected",
                "expires_at",
                "max_runtime_seconds",
                "deadline_action",
                "cleanup_orphans",
                "orphan_reminder",
                "orphan_wait_seconds",
            }
            if set(policy) - fields:
                raise DomainError("invalid_policy", "unsupported task policy fields", 422)
            if "priority" in policy and (
                type(policy["priority"]) is not int or not 0 <= policy["priority"] <= 100
            ):
                raise DomainError("invalid_policy", "priority 0..100 required", 422)
            if policy.get("deadline_action", "notify") not in {"notify", "terminate"}:
                raise DomainError("invalid_policy", "deadline action invalid", 422)
            if "orphan_reminder" in policy and type(policy["orphan_reminder"]) is not bool:
                raise DomainError("invalid_policy", "orphan reminder must be boolean", 422)
            if "orphan_wait_seconds" in policy and (
                type(policy["orphan_wait_seconds"]) is not int
                or not 1 <= policy["orphan_wait_seconds"] <= 86400
            ):
                raise DomainError("invalid_policy", "orphan wait must be an integer 1..86400", 422)
            deadline(
                parse_time(task["started_at"]),
                policy.get("max_runtime_seconds", task["max_runtime_seconds"]),
                parse_time(policy.get("expires_at", task["expires_at"])),
            )
            task.update(policy)
            task["revision"] += 1
            task["policy_status"] = "awaiting_sync"
            task["policy_confirmed_at"] = utcnow().isoformat()
            task["confirmed_revision"] = None
            self.event(state, p, "task.policy", task["id"], None, task)
            return task
        if method == "apply_membership":
            self.refresh(state)
            action = p["action"]
            if action == "merge":
                tasks = [self.find(state, "tasks", i) for i in p["task_ids"]]
                if len(tasks) < 2 or len({t["uid"] for t in tasks}) != 1:
                    raise DomainError("invalid_grouping", "merge requires same UID")
                for task in tasks:
                    self.require_human_task(task)
                    self.revision(task, dict(revision=p["revisions"].get(task["id"])))
                target = tasks[0]
                target["members"] = [m for t in tasks for m in t["members"]]
                target["historic_identities"] = list({i for t in tasks for i in t["historic_identities"]})
                target["leader_identities"] = [
                    identity for task in tasks for identity in task.get("leader_identities", [])
                ]
                target["started_at"] = min(t["started_at"] for t in tasks)
                target["revision"] += 1
                state["tasks"] = [t for t in state["tasks"] if t["id"] not in p["task_ids"][1:]]
                self.event(state, p, "task.merge", target["id"], None, target)
                return target
            task = self.find(state, "tasks", p["task_id"])
            self.require_human_task(task)
            self.revision(task, p)
            selected = p.get("identities", p.get("excluded_identities", []))
            keys = {identity_key(i) for i in selected}
            member_keys = {identity_key(m["identity"]) for m in task["members"]}
            if not keys or not keys <= member_keys:
                raise DomainError("invalid_grouping", "selection outside membership")
            members = [m for m in task["members"] if identity_key(m["identity"]) in keys]
            if action == "split":
                if keys == member_keys:
                    raise DomainError("invalid_split", "select part of task")
                new = copy.deepcopy(task)
                new.update(
                    id=str(uuid4()),
                    revision=1,
                    members=members,
                    historic_identities=list(keys),
                    leader_identities=[
                        m["identity"] for m in members if m["ppid"] not in {p["pid"] for p in members}
                    ],
                )
                state["tasks"].append(new)
            elif action == "exclude":
                state["excluded"] = list(set(state["excluded"]) | keys)
            else:
                raise DomainError("unsupported_action", "unknown grouping action", 422)
            task["members"] = [m for m in task["members"] if identity_key(m["identity"]) not in keys]
            task["historic_identities"] = [k for k in task["historic_identities"] if k not in keys]
            task["revision"] += 1
            self.event(state, p, "task." + action, task["id"], None, task)
            return task
        if method == "preview_termination":
            self.refresh(state)
            if state.get("stale", True):
                raise DomainError("stale_collection", "fresh complete process collection required", 503)
            task = self.find(state, "tasks", p["task_id"])
            targets, excluded = self.targets(task, p.get("identity"), p.get("residual_only", False))
            value = self.preview(state, "task", task, "terminate", targets=targets, excluded=excluded)
            value["residual_only"] = p.get("residual_only", False)
            state["previews"][value["token"]]["residual_only"] = value["residual_only"]
            value["task_id"] = task["id"]
            return value
        if method == "execute_termination":
            key = p["idempotency_key"]
            if not isinstance(key, str) or not key or len(key) > 200:
                raise DomainError("invalid_idempotency", "idempotency key required", 422)
            if key in state["idempotency"]:
                previous = state["idempotency"][key]
                if previous["token"] != p["token"]:
                    raise DomainError("idempotency_conflict", "key used for other scope")
                return state["jobs"][previous["id"]]
            self.refresh(state)
            if state.get("stale", True):
                raise DomainError("stale_collection", "fresh complete process collection required", 503)
            preview = state["previews"].get(p["token"])
            if not preview:
                raise DomainError("invalid_preview", "preview not found")
            task = self.find(state, "tasks", preview["id"])
            if p.get("task_id", task["id"]) != task["id"]:
                raise DomainError("scope_changed", "termination token belongs to another task")
            checked = self.checked(state, p, "task", task, "terminate")
            targets, _ = self.targets(task, residual_only=checked.get("residual_only", False))
            if not {(identity_key(m["identity"]), m["uid"]) for m in checked["targets"]} <= {
                (identity_key(m["identity"]), m["uid"]) for m in targets
            }:
                raise DomainError("scope_changed", "signal scope changed")
            job = dict(
                id=str(uuid4()),
                status="queued",
                reason=p.get("reason", ""),
                created_at=utcnow().isoformat(),
                source="host",
                results=[],
                targets=checked["targets"],
                task_id=task["id"],
                task_revision=task["revision"],
                residual_only=checked.get("residual_only", False),
                actor=p.get("actor", "system"),
            )
            if job["residual_only"]:
                task["status"] = "cleaning"
            state["jobs"][job["id"]] = job
            state["idempotency"][key] = dict(id=job["id"], token=p["token"])
            del state["previews"][p["token"]]
            # Worker acquires lock only after the caller has committed this durable job.
            worker = threading.Thread(target=self.execute_job, args=(job["id"],), daemon=True)
            self.workers[job["id"]] = worker
            worker.start()
            self.event(state, p, "task.terminate.request", task["id"], None, job)
            return job
        if method == "job_status":
            if p["id"] not in state["jobs"]:
                raise DomainError("not_found", "job not found", 404)
            return state["jobs"][p["id"]]
        if method == "audit_since":
            cursor = p.get("cursor")
            events = state["events"]
            start = 0
            if cursor:
                index = next((i for i, e in enumerate(events) if e["id"] == cursor), None)
                if index is None:
                    raise DomainError("invalid_cursor", "audit cursor not found", 422)
                start = index + 1
            count = min(100, max(1, int(p.get("limit", 100))))
            items = []
            size = 0
            for event in events[start : start + count]:
                amount = len(json.dumps(event).encode())
                if size + amount > 512 * 1024:
                    break
                items.append(event)
                size += amount
            return dict(
                items=items,
                cursor=items[-1]["id"] if items else cursor,
                has_more=start + len(items) < len(events),
            )
        if method == "preview_account_change":
            if "password" in p.get("changes", {}):
                raise DomainError(
                    "credentials_in_preview", "passwords must never be included in previews", 422
                )
            account = self.accounts.writable(
                state, p["id"], adopt=p.get("changes", {}).get("managed") is True
            )
            self.revision(account, p)
            preview = self.preview(
                state,
                "account",
                account,
                p["action"],
                changes={k: v for k, v in p.get("changes", {}).items() if k != "password"},
            )
            preview["activity"] = self.accounts.activity(state, p["id"])
            preview["paths"] = {key: account.get(key) for key in ("home", "data_dir")}
            preview["impact"] = (
                "Existing processes, sessions, scheduled activity and files are retained. Disabling/soft-deleting blocks new logins only; restore/enable preserve other restriction causes."
            )
            if p.get("changes", {}).get("username", account["username"]) != account["username"]:
                preview["impact"] = (
                    "Rename requires no processes, sessions or known scheduled activity, pauses new logins, and changes only controlled home/data paths; UID and files are retained."
                )
            if "primary_group" in p.get("changes", {}):
                preview["impact"] = (
                    "Primary group changes apply to new logins; native usermod may update old-GID files under home. Data directory and other paths remain unchanged; no directory migration."
                )
            return preview

        if method == "execute_account_change":
            changes = p.get("changes", {})
            action = p["action"]
            if action != "create":
                account = self.accounts.writable(state, p["id"], adopt=changes.get("managed") is True)
                self.revision(account, p)
                # All potentially dangerous changes are previewed, including public keys/adoption.
                self.checked(
                    state,
                    p,
                    "account",
                    account,
                    action,
                    {k: v for k, v in changes.items() if k != "password"},
                )
            before = self.accounts.find(state, p["id"]) if action != "create" else None
            result = self.accounts.execute(state, action, p.get("id"), changes)
            state["previews"].pop(p.get("token"), None)
            self.event(state, p, "account." + action, result["id"], before, result)
            return result
        if method in {"preview_group_change", "execute_group_change"}:
            return self.group_change(state, method, p)
        if method in {
            "storage_snapshot",
            "get_quotas",
            "preview_quota",
            "apply_quota",
            "list_shares",
            "preview_share_change",
            "execute_share_change",
        }:
            from gpupm.agent.storage import Storage

            return Storage(self).dispatch(state, method, p)
        if method == "login_events_since":
            from gpupm.agent.login import login_events

            return login_events(state, p)
        raise DomainError("unsupported", "unsupported agent method: " + method, 422)

    def group_change(self, state, method, p):
        import grp
        from gpupm.domain.rules import validate_name

        action = p.get("action", "update")
        changes = p.get("changes", {})
        if set(changes) - {"name", "members"}:
            raise DomainError("invalid_fields", "only group name and members editable", 422)
        if action == "create":
            name = validate_name(changes["name"])
            if name in SENSITIVE_GROUPS or name == "human":
                raise DomainError("protected_group", "sensitive group forbidden", 403)
            try:
                grp.getgrnam(name)
            except KeyError:
                pass
            else:
                raise DomainError("group_exists", "system group exists")
            group = dict(id=name, name=name, revision=0, gid=None, members=[])
        else:
            group = next((g for g in self.accounts.groups(state) if g["id"] == p["id"]), None)
            if not group:
                raise DomainError("not_found", "system group not found", 404)
            if group["protected"] or not group["managed"]:
                raise DomainError("protected_group", "only managed ordinary groups editable", 403)
            self.accounts.assert_human_group(group["name"])
            self.revision(group, p)
        if "members" in changes:
            if not isinstance(changes["members"], list):
                raise DomainError("invalid_members", "members must be a list", 422)
            for name in changes["members"]:
                entry = self.accounts.find(state, str(__import__("pwd").getpwnam(name).pw_uid))
                if not self.accounts.is_human(entry["uid"]):
                    raise DomainError("non_human_readonly", "group members must be human", 403)
                if entry["protected"] or not entry["managed"]:
                    raise DomainError("protected_account", "grant only to managed ordinary accounts", 403)
        if "name" in changes:
            name = validate_name(changes["name"])
            if name in SENSITIVE_GROUPS or name == "human":
                raise DomainError("protected_group", "sensitive group forbidden", 403)
        if method == "preview_group_change":
            return self.preview(state, "group", group, action, changes)
        if action != "create":
            self.checked(state, p, "group", group, action, changes)
        before = copy.deepcopy(group)
        if action == "create":
            self.accounts.run(["groupadd", changes["name"]])
            state["groups"][changes["name"]] = {"revision": 1}
        elif action == "delete":
            if group["members"] or any(
                entry.pw_gid == group["gid"] for entry in __import__("pwd").getpwall()
            ):
                raise DomainError("group_in_use", "group has members or primary-group references")
            if any(group["name"] in {s["reader_group"], s["writer_group"]} for s in state["shares"]):
                raise DomainError("group_in_use", "group grants shared path access")
            self.accounts.run(["groupdel", group["name"]])
            state["groups"].pop(group["name"], None)
        else:
            if "name" in changes and changes["name"] != group["name"]:
                if any(group["name"] in {s["reader_group"], s["writer_group"]} for s in state["shares"]):
                    raise DomainError("group_in_use", "group grants shared path access")
                self.accounts.run(["groupmod", "--new-name", changes["name"], group["name"]])
                state["groups"][changes["name"]] = state["groups"].pop(group["name"])
                group["name"] = changes["name"]
            state["groups"][group["name"]]["revision"] += 1
        if "members" in changes:
            self.accounts.run(
                ["gpasswd", "--members", ",".join(changes["members"]), changes.get("name", group["name"])]
            )
        state["previews"].pop(p.get("token"), None)
        self.event(state, p, "system_group." + action, group["id"], before, changes)
        return next(
            (g for g in self.accounts.groups(state) if g["name"] == changes.get("name", group["name"])),
            dict(id=group["id"], status="deleted"),
        )

    def signal_member(self, member, sig):
        def ignored_executables():
            return self.runtime_setting(
                "ignored_task_executables", DEFAULT_SETTINGS["ignored_task_executables"]
            )

        if ignored_process(member, ignored_executables()):
            return "ignored_executable"
        protected = {self.config.get("api_uid")} - {None}
        if self.signaler is signal_identity:
            return self.signaler(
                member["identity"],
                sig,
                protected,
                expected_uid=member["uid"],
                human_check=self.accounts.is_human,
                ignored_executables=ignored_executables,
            )
        return self.signaler(member["identity"], sig, protected)

    def execute_job(self, ident):
        try:
            with self.lock, self.database() as db:
                state = self.load(db)
                job = state["jobs"][ident]
                job["status"] = "running"
                grace = state["settings"].get("term_grace_seconds", self.config.get("term_grace_seconds", 10))
                job["term_grace_seconds"] = grace
                self.save(db, state)
                targets = copy.deepcopy(job["targets"])
            results = []
            for member in targets:
                if self.stop.is_set():
                    return
                with self.lock, self.database() as db:
                    state = self.load(db)
                    job = state["jobs"][ident]
                    task = self.find(state, "tasks", job["task_id"])
                    residual_valid = True
                    if job.get("residual_only") or job.get("actor") == "policy":
                        self.refresh(state)
                        task = self.find(state, "tasks", job["task_id"])
                        try:
                            eligible, _ = self.targets(task, residual_only=job.get("residual_only", False))
                            residual_valid = not state.get("stale", True) and any(
                                m["identity"] == member["identity"] and m["uid"] == member["uid"]
                                for m in eligible
                            )
                        except DomainError:
                            residual_valid = False
                    if not self.accounts.is_human(task["uid"]) or not self.accounts.is_human(member["uid"]):
                        job["human_scope_revoked"] = True
                    if (
                        not residual_valid
                        or task["protected"]
                        or job.get("human_scope_revoked")
                        or task["revision"] != job["task_revision"]
                        or (
                            job.get("actor") == "policy"
                            and (
                                task["status"] != "running"
                                or task["policy_status"] != "applied"
                                or not state.get("last_heartbeat")
                                or (utcnow() - parse_time(state["last_heartbeat"])).total_seconds()
                                > self.policy_freshness(state)
                                or task.get("confirmed_revision") != task["revision"]
                            )
                        )
                    ):
                        status = "scope_changed"
                    else:
                        try:
                            status = self.signal_member(member, signal.SIGTERM)
                        except Exception as exc:
                            status = "error: " + str(exc)
                    results.append(dict(identity=member["identity"], term=status))
                    job["results"] = copy.deepcopy(results)
                    self.save(db, state)
            if self.stop.wait(grace):
                return
            for member, result in zip(targets, results):
                if result["term"] != "signaled":
                    continue
                with self.lock, self.database() as db:
                    state = self.load(db)
                    job = state["jobs"][ident]
                    task = self.find(state, "tasks", job["task_id"])
                    residual_valid = True
                    if job.get("residual_only") or job.get("actor") == "policy":
                        self.refresh(state)
                        task = self.find(state, "tasks", job["task_id"])
                        try:
                            eligible, _ = self.targets(task, residual_only=job.get("residual_only", False))
                            residual_valid = not state.get("stale", True) and any(
                                m["identity"] == member["identity"] and m["uid"] == member["uid"]
                                for m in eligible
                            )
                        except DomainError:
                            residual_valid = False
                    if not self.accounts.is_human(task["uid"]) or not self.accounts.is_human(member["uid"]):
                        job["human_scope_revoked"] = True
                    if (
                        not residual_valid
                        or task["protected"]
                        or job.get("human_scope_revoked")
                        or task["revision"] != job["task_revision"]
                        or (
                            job.get("actor") == "policy"
                            and (
                                task["status"] != "running"
                                or task["policy_status"] != "applied"
                                or not state.get("last_heartbeat")
                                or (utcnow() - parse_time(state["last_heartbeat"])).total_seconds()
                                > self.policy_freshness(state)
                                or task.get("confirmed_revision") != task["revision"]
                            )
                        )
                    ):
                        result["kill"] = "scope_changed"
                    else:
                        try:
                            result["kill"] = self.signal_member(member, signal.SIGKILL)
                        except Exception as exc:
                            result["kill"] = "error: " + str(exc)
                    job["results"] = copy.deepcopy(results)
                    self.save(db, state)
            # Record kernel-observed residue, not merely successful signal dispatch.
            if any(r["term"] == "signaled" for r in results):
                if self.stop.wait(self.config.get("termination_recheck_seconds", 1)):
                    return
            for member, result in zip(targets, results):
                result["final"] = self.process_checker(member["identity"])
            with self.lock, self.database() as db:
                state = self.load(db)
                job = state["jobs"][ident]
                job["results"] = results
                if any(
                    r["final"] == "unavailable" or any(str(v).startswith("error:") for v in r.values())
                    for r in results
                ):
                    status = "failed"
                elif all(r["final"] in {"exited", "identity_changed"} for r in results):
                    status = "completed"
                else:
                    status = "partial"
                job["status"] = status
                if job.get("residual_only"):
                    self.refresh(state)
                self.event(state, job, "task.terminate", job["task_id"], None, job, status)
                self.save(db, state)
        finally:
            self.workers.pop(ident, None)

    def collect_storage(self):
        from gpupm.agent.storage import Storage

        if not self.storage_scan_lock.acquire(blocking=False):
            return
        try:
            with self.lock, self.database() as db:
                copied = self.load(db)
                original_events = len(copied["events"])
            # Directory traversal and native quota reads cannot block process authority/heartbeat.
            result = Storage(self).snapshot(copied)
            with self.lock, self.database() as db:
                state = self.load(db)
                for share in state["shares"]:
                    scanned = next(
                        (
                            s
                            for s in copied["shares"]
                            if s["id"] == share["id"] and s["revision"] == share["revision"]
                        ),
                        None,
                    )
                    if scanned:
                        for field in ("usage_bytes", "usage_files", "usage_status"):
                            share[field] = scanned.get(field)
                result["shares"] = copy.deepcopy(state["shares"])
                if state.get("acl_verified_at"):
                    result["capabilities"]["acl"] = dict(
                        status="verified",
                        message="Share directory ACL applied and numeric readback verified",
                        verified_at=state["acl_verified_at"],
                    )
                state["storage"] = result
                state["storage_alert_states"] = copied.get("storage_alert_states", {})
                state["events"].extend(
                    event
                    for event in copied["events"][original_events:]
                    if event["action"] != "account.identity_conflict"
                )
                self.save(db, state)
        finally:
            self.storage_scan_lock.release()

    def tick(self):
        with self.lock, self.database() as db:
            state = self.load(db)
            self.refresh(state)
            observed_accounts = self.accounts.list(state)
            if self.config.get("allow_mutations"):
                for account in observed_accounts:
                    if (
                        not account["managed"]
                        or account["protected"]
                        or not self.accounts.is_human(account["uid"])
                    ):
                        continue
                    meta = state["accounts"][account["id"]]
                    if meta.get("rename_recovery_required"):
                        continue
                    from gpupm.agent.accounts import restriction_active

                    if restriction_active(meta) != meta.get("agent_restricted", False):
                        try:
                            self.accounts.apply_login(account, meta)
                        except DomainError as exc:
                            meta["login_policy_status"] = exc.code
                            self.event(state, {}, "account.expiry", account["id"], None, None, exc.code)
                        else:
                            self.event(state, {}, "account.expiry", account["id"], None, account)
            pending = []
            for task in state["tasks"]:
                if (
                    task["status"] != "running"
                    or not task["overdue"]
                    or task["protected"]
                    or not self.accounts.is_human(task["uid"])
                    or task["policy_status"] != "applied"
                ):
                    continue
                if task.get("deadline_handled_revision") == task["revision"]:
                    continue
                if (
                    not state.get("last_heartbeat")
                    or (utcnow() - parse_time(state["last_heartbeat"])).total_seconds()
                    > self.policy_freshness(state)
                    or task.get("confirmed_revision") != task["revision"]
                ):
                    continue
                if task["deadline_action"] == "notify":
                    self.event(
                        state,
                        {},
                        "task.deadline",
                        task["id"],
                        None,
                        dict(deadline_at=task["deadline_at"]),
                        "notified",
                    )
                elif (
                    self.config.get("allow_mutations")
                    and not state["errors"]
                    and state.get("last_heartbeat")
                    and (utcnow() - parse_time(state["last_heartbeat"])).total_seconds()
                    <= self.policy_freshness(state)
                    and task.get("confirmed_revision") == task["revision"]
                ):
                    targets, excluded = self.targets(task)
                    preview = self.preview(
                        state, "task", task, "terminate", targets=targets, excluded=excluded
                    )
                    pending.append(
                        dict(
                            token=preview["token"],
                            reason="confirmed policy deadline",
                            idempotency_key="deadline:"
                            + task["id"]
                            + ":"
                            + str(task["revision"])
                            + ":"
                            + str(task.get("recovery_attempt", 0)),
                            actor="policy",
                        )
                    )
                if task["deadline_action"] == "notify" or any(
                    j.get("idempotency_key")
                    == "deadline:"
                    + task["id"]
                    + ":"
                    + str(task["revision"])
                    + ":"
                    + str(task.get("recovery_attempt", 0))
                    for j in pending
                ):
                    task["deadline_handled_revision"] = task["revision"]
            self.save(db, state)
        for params in pending:
            self.call("execute_termination", params)
