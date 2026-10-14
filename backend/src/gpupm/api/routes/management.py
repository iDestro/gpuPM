from datetime import datetime

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from gpupm.api.routes.common import actor, context, safe_audit
from gpupm.db.models import AuditLog, ManagementGroup, ManagedUser, Setting
from gpupm.db.session import columns
from gpupm.domain.rules import parse_time
from gpupm.domain.schemas import GroupInput, GroupPatch, SettingsPatch, UserPatch
from gpupm.errors import DomainError

router = APIRouter(prefix="/api")


@router.get("/groups")
def groups(request: Request):
    with context(request).sessions() as db:
        return [columns(g) for g in db.scalars(select(ManagementGroup).order_by(ManagementGroup.id))]


@router.post("/groups")
def create_group(body: GroupInput, request: Request):
    ctx = context(request)
    with ctx.lock, ctx.sessions.begin() as db:
        group = ManagementGroup(**body.model_dump())
        db.add(group)
        db.flush()
        result = columns(group)
        ctx.audit(db, actor(request), "group.create", group.id, None, result)
    return result


@router.patch("/groups/{ident}")
def edit_group(ident: int, body: GroupPatch, request: Request):
    ctx = context(request)
    with ctx.lock, ctx.sessions.begin() as db:
        group = db.get(ManagementGroup, ident)
        if not group:
            raise DomainError("not_found", "业务组不存在", 404)
        before = columns(group)
        for key, value in body.model_dump(exclude_unset=True).items():
            if value is None:
                raise DomainError("invalid_value", "组配置不能为空", 422)
            setattr(group, key, value)
        db.flush()
        result = columns(group)
        ctx.audit(db, actor(request), "group.update", ident, before, result)
    return result


@router.delete("/groups/{ident}")
def delete_group(ident: int, request: Request, move_to: int = Query(gt=0)):
    ctx = context(request)
    with ctx.lock, ctx.sessions.begin() as db:
        group = db.get(ManagementGroup, ident)
        if not group:
            raise DomainError("not_found", "业务组不存在", 404)
        if group.is_default or ident == move_to:
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


@router.get("/users")
def users(request: Request):
    return context(request).users()


@router.patch("/users/{uid}")
def update_user(uid: int, body: UserPatch, request: Request):
    ctx = context(request)
    ctx.users()
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
        result = columns(user)
        ctx.audit(db, actor(request), "user.update", uid, before, result)
    return result


@router.get("/settings")
def settings(request: Request):
    return context(request).settings()


@router.patch("/settings")
def update_settings(body: SettingsPatch, request: Request):
    ctx = context(request)
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
