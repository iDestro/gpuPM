from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import Field, StrictBool

from gpupm.api.routes.common import agent_mutation, context
from gpupm.db.models import ManagedUser, ManagementGroup
from gpupm.domain.schemas import (
    AccountCreate,
    AccountPatch,
    AccountPreview,
    Confirm,
    Input,
    PasswordReset,
    QuotaInput,
    QuotaPatch,
    ShareInput,
    SystemGroupInput,
)
from gpupm.errors import DomainError

router = APIRouter(prefix="/api")


class SystemGroupPatch(Input):
    managed: StrictBool | None = None
    reason: str = Field(default="系统组修改", max_length=1024)
    revision: int = Field(gt=0)
    token: str
    name: str | None = None
    members: list[str] | None = None


class ChangePreview(Input):
    action: str = "update"
    revision: int = Field(gt=0)
    changes: dict = Field(default_factory=dict)


class SharePatch(Input):
    reason: str = Field(default="共享授权修改", max_length=1024)
    name: str | None = None
    token: str
    revision: int = Field(gt=0)
    reader_group: str | None = None
    writer_group: str | None = None
    notes: str | None = None
    status: str | None = None


@router.get("/system-users")
def accounts(request: Request, state: str = "active", scope: Literal["human", "other", "all"] = "human"):
    ctx = context(request)
    profiles = {u["uid"]: u for u in ctx.users()}
    result = [
        dict(
            a,
            group_id=profiles.get(a["uid"], {}).get("group_id", 1),
            priority=profiles.get(a["uid"], {}).get("priority", 50),
        )
        for a in ctx.agent.call("list_accounts")
    ]
    result = [a for a in result if scope == "all" or bool(a.get("is_human", False)) == (scope == "human")]
    if state == "all":
        return result
    if state == "active":
        return [a for a in result if a["status"] != "deleted"]
    if state not in {"disabled", "expired", "deleted"}:
        raise DomainError("invalid_state", "状态筛选无效", 422)
    return [a for a in result if a["status"] == state]


@router.get("/system-users/{ident}")
def account(ident: str, request: Request):
    for item in accounts(request, state="all", scope="all"):
        if item["id"] == ident:
            return item
    raise DomainError("not_found", "账号不存在", 404)


def business_fields(request, result, fields):
    ctx = context(request)
    ctx.invalidate()
    ctx.users()
    if not any(k in fields for k in {"group_id", "priority"}):
        return
    with ctx.sessions.begin() as db:
        user = db.get(ManagedUser, result["uid"])
        if "group_id" in fields:
            if not db.get(ManagementGroup, fields["group_id"]):
                raise DomainError("not_found", "业务组不存在", 404)
            user.group_id = fields["group_id"]
        if "priority" in fields:
            user.priority = fields["priority"]


@router.post("/system-users")
def create_account(body: AccountCreate, request: Request):
    ctx = context(request)
    with ctx.lock:
        with ctx.sessions() as db:
            if not db.get(ManagementGroup, body.group_id):
                raise DomainError("not_found", "业务组不存在", 404)
        fields = body.model_dump(mode="json")
        changes = {k: v for k, v in fields.items() if k not in {"password", "group_id", "priority"}}
        changes["password"] = body.password.get_secret_value() if body.password else None
        result = agent_mutation(
            request,
            "execute_account_change",
            {"action": "create", "changes": changes},
            "account.create",
            body.username,
        )
        if "uid" in result:
            business_fields(request, result, fields)
        return result


@router.patch("/system-users/{ident}")
def update_account(ident: str, body: AccountPatch, request: Request):
    ctx = context(request)
    with ctx.lock:
        fields = body.model_dump(exclude_unset=True, mode="json")
        revision = fields.pop("revision")
        token = fields.pop("token", None)
        reason = fields.pop("reason", "管理员修改")
        changes = {k: v for k, v in fields.items() if k not in {"group_id", "priority"}}
        if "group_id" in fields:
            with context(request).sessions() as db:
                if not db.get(ManagementGroup, fields["group_id"]):
                    raise DomainError("not_found", "业务组不存在", 404)
        if not token:
            raise DomainError("invalid_preview", "请先预览账号变更")
        result = agent_mutation(
            request,
            "execute_account_change",
            dict(action="update", id=ident, revision=revision, token=token, changes=changes, reason=reason),
            "account.update",
            ident,
        )
        if "uid" in result:
            business_fields(request, result, fields)
        return result


@router.post("/system-users/{ident}/change-preview")
def preview_account(ident: str, body: AccountPreview, request: Request):
    if "password" in body.changes:
        raise DomainError("secret_in_preview", "密码不能提交到持久化预览，请使用专用密码重置流程", 422)
    changes = {
        k: v for k, v in body.changes.items() if k not in {"group_id", "priority", "token", "revision"}
    }
    return context(request).agent.call(
        "preview_account_change", dict(action=body.action, id=ident, revision=body.revision, changes=changes)
    )


def account_action(action):
    def handler(ident: str, body: Confirm, request: Request):
        return agent_mutation(
            request,
            "execute_account_change",
            dict(action=action, id=ident, **body.model_dump()),
            "account." + action,
            ident,
        )

    return handler


router.add_api_route("/system-users/{ident}", account_action("delete"), methods=["DELETE"])
for action in ["disable", "enable", "restore"]:
    router.add_api_route("/system-users/{ident}/" + action, account_action(action), methods=["POST"])


@router.patch("/system-users/{ident}/expiry")
@router.patch("/system-users/{ident}/password-policy")
def expiry(ident: str, body: AccountPatch, request: Request):
    return update_account(ident, body, request)


@router.post("/system-users/{ident}/password")
def password(ident: str, body: PasswordReset, request: Request):
    changes = {
        "password": body.password.get_secret_value(),
        "require_password_change": body.require_password_change,
    }
    return agent_mutation(
        request,
        "execute_account_change",
        dict(
            action="update",
            id=ident,
            revision=body.revision,
            token=body.token,
            changes=changes,
            reason=body.reason,
        ),
        "account.password",
        ident,
    )


@router.get("/system-users/{ident}/activity")
def activity(ident: str, request: Request):
    return context(request).agent.call("account_activity", {"id": ident})


@router.get("/system-groups")
def system_groups(request: Request, scope: Literal["managed", "other", "all"] = "managed"):
    return context(request).agent.call("list_system_groups", {"scope": scope})


@router.post("/system-groups")
def create_system_group(body: SystemGroupInput, request: Request):
    return agent_mutation(
        request,
        "execute_group_change",
        dict(action="create", changes=body.model_dump()),
        "system_group.create",
        body.name,
    )


@router.post("/system-groups/{ident}/change-preview")
def preview_system_group(ident: str, body: ChangePreview, request: Request):
    return context(request).agent.call("preview_group_change", dict(id=ident, **body.model_dump()))


@router.patch("/system-groups/{ident}")
def update_system_group(ident: str, body: SystemGroupPatch, request: Request):
    changes = body.model_dump(exclude={"revision", "token", "reason"}, exclude_unset=True)
    return agent_mutation(
        request,
        "execute_group_change",
        dict(
            action="update",
            id=ident,
            revision=body.revision,
            token=body.token,
            changes=changes,
            reason=body.reason,
        ),
        "system_group.update",
        ident,
    )


@router.delete("/system-groups/{ident}")
def delete_system_group(ident: str, body: Confirm, request: Request):
    return agent_mutation(
        request,
        "execute_group_change",
        dict(action="delete", id=ident, **body.model_dump()),
        "system_group.delete",
        ident,
    )


@router.get("/storage")
def storage(request: Request):
    return context(request).agent.call("storage_snapshot")


@router.get("/system-users/{ident}/quotas")
def quotas(ident: str, request: Request):
    return context(request).agent.call("get_quotas", {"id": ident})


@router.post("/system-users/{ident}/quotas/preview")
def preview_quota(ident: str, body: QuotaInput, request: Request):
    return context(request).agent.call(
        "preview_quota", {"id": ident, "policy": body.model_dump(exclude_none=True)}
    )


@router.patch("/system-users/{ident}/quotas")
def update_quota(ident: str, body: QuotaPatch, request: Request):
    if not body.token:
        raise DomainError("invalid_preview", "请先预览实际用量和限额影响")
    return agent_mutation(
        request,
        "apply_quota",
        {
            "id": ident,
            "policy": body.model_dump(exclude={"token", "reason"}, exclude_none=True),
            "token": body.token,
            "reason": body.reason,
        },
        "quota.update",
        ident,
    )


@router.get("/login-events")
def login_events(
    request: Request,
    username: str | None = None,
    ip: str | None = None,
    result: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    params = dict(
        username=username,
        ip=ip,
        result=result,
        since=since.isoformat() if since else None,
        until=until.isoformat() if until else None,
        page=page,
        page_size=page_size,
    )
    return context(request).agent.call("login_events_since", params)


@router.get("/shares")
def shares(request: Request):
    return context(request).agent.call("list_shares")


@router.post("/shares/change-preview")
def preview_create_share(body: dict, request: Request):
    if body.get("action") != "create":
        raise DomainError("invalid_action", "共享创建预览的 action 必须为 create", 422)
    fields = ShareInput.model_validate(body.get("changes", {})).model_dump(exclude={"token", "reason"})
    return context(request).agent.call("preview_share_change", {"action": "create", "changes": fields})


@router.post("/shares")
def create_share(body: ShareInput, request: Request):
    if not body.token:
        raise DomainError("invalid_preview", "请先预览共享目录的初始授权")
    return agent_mutation(
        request,
        "execute_share_change",
        {"changes": body.model_dump(exclude={"token", "reason"}), "token": body.token, "reason": body.reason},
        "share.create",
        body.name,
    )


def share_changes(request, ident, changes):
    existing = next((s for s in context(request).agent.call("list_shares") if s["id"] == ident), None)
    if not existing:
        raise DomainError("not_found", "共享项目不存在", 404)
    if "name" in changes and changes["name"] != existing["name"]:
        raise DomainError("share_rename", "共享项目名称及路径不能在线修改", 422)
    return {k: v for k, v in changes.items() if k not in {"name", "revision", "reason", "token"}}


@router.post("/shares/{ident}/change-preview")
def preview_share(ident: str, body: ChangePreview, request: Request):
    return context(request).agent.call(
        "preview_share_change",
        dict(id=ident, revision=body.revision, changes=share_changes(request, ident, body.changes)),
    )


@router.patch("/shares/{ident}")
def update_share(ident: str, body: SharePatch, request: Request):
    changes = share_changes(
        request, ident, body.model_dump(exclude={"token", "revision", "reason"}, exclude_unset=True)
    )
    return agent_mutation(
        request,
        "execute_share_change",
        dict(id=ident, token=body.token, revision=body.revision, changes=changes, reason=body.reason),
        "share.update",
        ident,
    )
