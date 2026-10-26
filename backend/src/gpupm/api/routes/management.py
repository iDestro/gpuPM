from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from gpupm.api.routes.common import actor, context, safe_audit
from gpupm.db.models import AuditLog, ManagementGroup, ManagedUser, Setting
from gpupm.db.session import columns
from gpupm.domain.rules import parse_time
from gpupm.domain.schemas import GroupInput, GroupMembers, GroupPatch, SettingsPatch, UserPatch
from gpupm.errors import DomainError
from gpupm.domain.user_policy import policy_editable, resolve_policy

router = APIRouter(prefix="/api")


@router.get("/groups")
def groups(request: Request):
    ctx = context(request)
    human_uids = [u["uid"] for u in ctx.users() if u["is_human"]]
    with ctx.sessions() as db:
        return [
            group_row(db, g, human_uids)
            for g in db.scalars(select(ManagementGroup).order_by(ManagementGroup.id))
        ]


def group_row(db, group, human_uids):
    policy, sources = resolve_policy(db.get(Setting, 1).values, group)
    return dict(
        columns(group),
        effective_policy={} if group.is_custom else policy,
        policy_sources={} if group.is_custom else sources,
        member_count=db.scalar(
            select(func.count())
            .select_from(ManagedUser)
            .where(ManagedUser.group_id == group.id, ManagedUser.uid.in_(human_uids))
        ),
    )


@router.post("/groups")
def create_group(body: GroupInput, request: Request):
    ctx = context(request)
    human_uids = [u["uid"] for u in ctx.users() if u["is_human"]]
    with ctx.lock, ctx.sessions.begin() as db:
        values = body.model_dump()
        if "priority" in body.model_fields_set:
            values["policy_overrides"] = dict(values["policy_overrides"], priority=body.priority)
        group = ManagementGroup(**values)
        db.add(group)
        db.flush()
        result = group_row(db, group, human_uids)
        ctx.audit(db, actor(request), "group.create", group.id, None, result)
    return result


@router.patch("/groups/{ident}")
def edit_group(ident: int, body: GroupPatch, request: Request):
    ctx = context(request)
    ctx.heartbeat()
    human_uids = [u["uid"] for u in ctx.users() if u["is_human"]]
    with ctx.lock, ctx.sessions.begin() as db:
        group = db.get(ManagementGroup, ident)
        if not group:
            raise DomainError("not_found", "用户组不存在", 404)
        if group.is_default or group.is_custom:
            raise DomainError("builtin_group", "内置组由策略配置或个人配置管理", 409)
        before = columns(group)
        for key, value in body.model_dump(exclude_unset=True).items():
            if value is None:
                raise DomainError("invalid_value", "组配置不能为空", 422)
            setattr(group, key, value)
        if "priority" in body.model_fields_set:
            group.policy_overrides = dict(group.policy_overrides, priority=body.priority)
        db.flush()
        result = group_row(db, group, human_uids)
        ctx.audit(db, actor(request), "group.update", ident, before, result)
    return result


@router.delete("/groups/{ident}")
def delete_group(ident: int, request: Request, move_to: int = Query(default=1, gt=0)):
    ctx = context(request)
    ctx.heartbeat()
    with ctx.lock, ctx.sessions.begin() as db:
        group = db.get(ManagementGroup, ident)
        if not group:
            raise DomainError("not_found", "用户组不存在", 404)
        if group.is_default or group.is_custom or ident == move_to:
            raise DomainError("default_group", "不能删除默认组或迁移到自身")
        if not db.get(ManagementGroup, move_to):
            raise DomainError("not_found", "迁移目标不存在", 404)
        before = columns(group)
        for user in db.scalars(select(ManagedUser).where(ManagedUser.group_id == ident)):
            user.group_id = move_to
        db.flush()
        db.delete(group)
        ctx.audit(db, actor(request), "group.delete", ident, before, {"move_to": move_to})
    return {"status": "succeeded"}


@router.post("/groups/{ident}/members")
def assign_group_members(ident: int, body: GroupMembers, request: Request):
    ctx = context(request)
    with ctx.lock:
        # Freeze existing tasks before changing the policy source for future tasks.
        ctx.heartbeat()
        ctx.users()
        accounts = {a["uid"]: a for a in ctx.agent.call("list_accounts")}
        with ctx.sessions.begin() as db:
            if not db.get(ManagementGroup, ident):
                raise DomainError("not_found", "用户组不存在", 404)
            pending = []
            for member in body.members:
                current = accounts.get(member.uid)
                if not policy_editable(current):
                    raise DomainError("policy_readonly", "仅正常启用的纳管人员账号可修改任务策略", 403)
                user = db.get(ManagedUser, member.uid)
                if not user or user.group_id != member.group_id:
                    raise DomainError("membership_changed", "成员所属组已变化，请刷新后重新选择。", 409)
                pending.append(user)
            for user in pending:
                if user.group_id == ident:
                    continue
                before = columns(user)
                user.group_id = ident
                ctx.audit(db, actor(request), "user.update", user.uid, before, columns(user))
    return {"status": "succeeded", "count": len(pending)}


@router.get("/users")
def users(request: Request, scope: Literal["human", "other", "all"] = "human"):
    return [u for u in context(request).users() if scope == "all" or u["is_human"] == (scope == "human")]


@router.patch("/users/{uid}")
def update_user(uid: int, body: UserPatch, request: Request):
    ctx = context(request)
    ctx.heartbeat()
    ctx.users()
    ctx.require_policy_user(uid)
    with ctx.lock, ctx.sessions.begin() as db:
        user = db.get(ManagedUser, uid)
        if not user:
            raise DomainError("not_found", "用户不存在", 404)
        values = body.model_dump(exclude_unset=True)
        if any(v is None for v in values.values()):
            raise DomainError("invalid_value", "用户配置不能为空", 422)
        if "group_id" in values and not db.get(ManagementGroup, values["group_id"]):
            raise DomainError("not_found", "管理组不存在", 404)
        before = columns(user)
        for key, value in values.items():
            setattr(user, key, value)
        if "priority" in values:
            user.personal_policy = dict(user.personal_policy, priority=values["priority"])
            if "group_id" not in values:
                user.group_id = db.scalar(
                    select(ManagementGroup.id).where(ManagementGroup.is_custom.is_(True))
                )
        result = columns(user)
        ctx.audit(db, actor(request), "user.update", uid, before, result)
    return next(u for u in ctx.users() if u["uid"] == uid)


@router.get("/settings")
def settings(request: Request):
    return context(request).settings()


@router.patch("/settings")
def update_settings(body: SettingsPatch, request: Request):
    ctx = context(request)
    ctx.heartbeat()
    changes = body.model_dump(exclude_unset=True)
    if any(v is None and k != "default_max_runtime_seconds" for k, v in changes.items()):
        raise DomainError("invalid_value", "配置不能为空", 422)
    with ctx.lock:
        with ctx.lock, ctx.sessions.begin() as db:
            setting = db.get(Setting, 1)
            before = setting.values.copy()
            values = dict(before, **changes)
            if values["warning_percent"] >= values["critical_percent"]:
                raise DomainError("invalid_threshold", "告警阈值必须小于严重阈值", 422)
            ctx.agent.call("configure", {"settings": values})
            setting.values = values
            ctx.audit(db, actor(request), "settings.update", "settings", before, values)
    ctx.invalidate()
    return ctx.settings()


@router.get("/audit-logs")
def audit_logs(
    request: Request,
    action: str | None = None,
    actor: str | None = None,
    result: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    ctx = context(request)
    if any(value is not None and value.tzinfo is None for value in (since, until)):
        raise DomainError("invalid_time", "筛选时间必须包含时区", 422)
    ctx.synchronize_events()
    stmt = select(AuditLog)
    for field, value in [("action", action), ("actor", actor), ("result", result)]:
        if value:
            stmt = stmt.where(getattr(AuditLog, field) == value)
    if since:
        stmt = stmt.where(AuditLog.time >= parse_time(since).isoformat())
    if until:
        stmt = stmt.where(AuditLog.time <= parse_time(until).isoformat())
    with ctx.sessions() as db:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.scalars(
            stmt.order_by(AuditLog.time.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return {"items": [safe_audit(columns(r)) for r in rows], "total": total}
