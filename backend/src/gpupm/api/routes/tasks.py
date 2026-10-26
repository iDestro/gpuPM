from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import Field

from gpupm.api.routes.common import actor, agent_mutation, context
from gpupm.db.models import TaskConfig
from gpupm.domain.schemas import Input, ProcessIdentity, TaskPatch, Terminate, TerminationPreview
from gpupm.errors import DomainError

router = APIRouter(prefix="/api")


class Merge(Input):
    task_ids: list[str] = Field(min_length=2, max_length=100)
    revisions: dict[str, int]


class Membership(Input):
    revision: int = Field(gt=0)
    excluded_identities: list[ProcessIdentity] = Field(default_factory=list, max_length=10000)


class Split(Input):
    revision: int = Field(gt=0)
    identities: list[ProcessIdentity] = Field(min_length=1, max_length=10000)


@router.get("/overview")
def overview(request: Request):
    ctx = context(request)
    tasks, snap = ctx.tasks()
    return dict(
        gpus=snap["gpus"],
        task_count=sum(t["status"] != "finished" for t in tasks),
        awaiting_cleanup_count=sum(t["status"] == "awaiting_cleanup" for t in tasks),
        overdue_count=sum(t["overdue"] for t in tasks),
        anomaly_count=sum(bool(t["anomalies"]) for t in tasks),
        collected_at=snap["collected_at"],
        source=snap["source"],
        stale=snap["stale"],
        agent_error=ctx.agent_error,
    )


@router.get("/gpus")
def gpus(request: Request):
    snap = context(request).snapshot()
    return dict(
        items=snap["gpus"], collected_at=snap["collected_at"], source=snap["source"], stale=snap["stale"]
    )


@router.get("/tasks")
def tasks(
    request: Request,
    scope: Literal["human", "other", "all"] = "human",
    gpu: str | None = None,
    uid: int | None = None,
    group_id: int | None = None,
    status: str | None = None,
    sort: Literal["priority", "runtime", "memory"] = "priority",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    result, snap = context(request).tasks()
    result = [t for t in result if scope == "all" or t["is_human"] == (scope == "human")]
    if uid is not None:
        result = [t for t in result if t["uid"] == uid]
    if group_id is not None:
        result = [t for t in result if t["group_id"] == group_id]
    if gpu:
        result = [
            t
            for t in result
            if gpu in t.get("gpu_uuids", []) or any(gpu in m.get("gpu_memory", {}) for m in t["members"])
        ]
    if status == "overdue":
        result = [t for t in result if t["overdue"]]
    elif status == "anomaly":
        result = [t for t in result if t["anomalies"]]
    elif status == "active":
        result = [
            t for t in result if t["status"] in {"running", "finalizing", "awaiting_cleanup", "cleaning"}
        ]
    elif status:
        result = [t for t in result if t["status"] == status]
    key = {"priority": "priority_tuple", "runtime": "runtime_seconds", "memory": "memory_used"}[sort]
    result.sort(
        key=lambda t: (t[key] is not None, t[key] if t[key] is not None else -1, t["id"]), reverse=True
    )
    total = len(result)
    return dict(
        items=result[(page - 1) * page_size : page * page_size],
        total=total,
        collected_at=snap["collected_at"],
        source=snap["source"],
        stale=snap["stale"],
    )


@router.get("/tasks/{ident}")
def task(ident: str, request: Request):
    return context(request).task(ident)


@router.patch("/tasks/{ident}")
def update_task(ident: str, body: TaskPatch, request: Request):
    ctx = context(request)
    changes = body.model_dump(exclude_unset=True, mode="json")
    revision = changes.pop("revision")
    if any(v is None and k not in {"expires_at", "max_runtime_seconds"} for k, v in changes.items()):
        raise DomainError("invalid_value", "任务配置不能为空", 422)
    with ctx.lock:
        before = ctx.task(ident)
        ctx.require_policy_user(before["uid"])
        if before["revision"] != revision:
            raise DomainError("revision_conflict", "任务版本已改变")
        with ctx.sessions() as db:
            registered = db.get(TaskConfig, ident)
            needs_enrollment = registered is None or not registered.policy_sources
        if needs_enrollment:
            ctx.heartbeat(expected_task=(ident, revision))
            with ctx.sessions() as db:
                registered = db.get(TaskConfig, ident)
                if registered is None or registered.status != "applied":
                    raise DomainError("policy_not_applied", "策略尚未同步，请重新加载", 409)
                revision = registered.revision
            before = ctx.task(ident)
            if before["revision"] != revision:
                raise DomainError("revision_conflict", "任务版本已改变", 409)
        with ctx.sessions.begin() as db:
            policy = db.get(TaskConfig, ident)
            if policy is None or policy.status != "applied":
                raise DomainError("policy_not_applied", "策略尚未同步，请重新加载", 409)
            updated = dict(policy.policy, **changes)
            sources = dict(policy.policy_sources or {}, **{k: "task" for k in changes})
            ranking = None if "priority" in changes else policy.priority_snapshot
            policy.status = "pending"
            ctx.audit(
                db,
                actor(request),
                "task.policy_attempt",
                ident,
                policy.policy,
                {
                    "revision": revision, "uid": before["uid"], "started_at": before["started_at"],
                    "policy": updated, "sources": sources, "priority_snapshot": ranking,
                },
                "pending",
            )
        try:
            applied = ctx.agent.call(
                "apply_task_policy",
                {"task_id": ident, "revision": revision, "policy": updated, "actor": actor(request)},
            )
        except DomainError as exc:
            with ctx.sessions.begin() as db:
                db.get(TaskConfig, ident).status = "failed"
                ctx.audit(db, actor(request), "task.policy", ident, None, None, "failed", exc.message)
            ctx.invalidate()
            raise
        with ctx.sessions.begin() as db:
            policy = db.get(TaskConfig, ident)
            policy.policy = updated
            policy.policy_sources = sources
            policy.priority_snapshot = ranking
            policy.status = "applied"
            policy.revision = applied["revision"]
            ctx.audit(db, actor(request), "task.policy", ident, None, updated, "succeeded")
        ctx.invalidate()
        return ctx.task(ident)


@router.post("/tasks/merge")
def merge(body: Merge, request: Request):
    for ident in body.task_ids:
        context(request).require_human(context(request).task(ident)["uid"])
    if len(set(body.task_ids)) != len(body.task_ids):
        raise DomainError("invalid_grouping", "不能重复选择同一任务", 422)
    return agent_mutation(
        request,
        "apply_membership",
        dict(action="merge", **body.model_dump()),
        "task.merge",
        ",".join(body.task_ids),
    )


@router.post("/tasks/{ident}/split")
def split(ident: str, body: Split, request: Request):
    context(request).require_human(context(request).task(ident)["uid"])
    return agent_mutation(
        request,
        "apply_membership",
        dict(action="split", task_id=ident, **body.model_dump()),
        "task.split",
        ident,
    )


@router.patch("/tasks/{ident}/members")
def members(ident: str, body: Membership, request: Request):
    context(request).require_human(context(request).task(ident)["uid"])
    return agent_mutation(
        request,
        "apply_membership",
        dict(action="exclude", task_id=ident, **body.model_dump()),
        "task.members",
        ident,
    )


@router.post("/tasks/{ident}/termination-preview")
def preview(ident: str, body: TerminationPreview, request: Request):
    ctx = context(request)
    selected = ctx.task(ident)
    ctx.require_human(selected["uid"])
    if selected["policy_status"] != "applied":
        raise DomainError("policy_not_applied", "策略尚未生效，请先恢复一致状态")
    snap = ctx.snapshot(force=True)
    if snap["stale"]:
        raise DomainError("stale_snapshot", "采集过期，禁止终止")
    return ctx.agent.call("preview_termination", dict(task_id=ident, **body.model_dump()))


@router.post("/tasks/{ident}/terminate")
def terminate(ident: str, body: Terminate, request: Request):
    context(request).require_human(context(request).task(ident)["uid"])
    return agent_mutation(
        request, "execute_termination", dict(task_id=ident, **body.model_dump()), "task.terminate", ident
    )


@router.get("/operations/{ident}")
def operation(ident: str, request: Request):
    return context(request).agent.call("job_status", {"id": ident})
