from fastapi import APIRouter, Request, Response

from gpupm.domain.schemas import Login
from gpupm.errors import DomainError
from gpupm.api.routes.common import context

router = APIRouter(prefix="/api")


@router.get("/health")
def health(request: Request):
    ctx = context(request)
    try:
        agent = ctx.agent.call("health")
    except DomainError:
        agent = {"status": "unavailable"}
    return {
        "status": "ok" if agent.get("status") == "ok" else "degraded",
        "mode": ctx.config.mode,
        "agent": agent.get("status"),
    }


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response):
    ctx = context(request)
    ip = request.client.host if request.client else "unknown"
    try:
        token, identity = request.app.state.auth.login(body.username, body.password.get_secret_value(), ip)
    except DomainError as exc:
        with ctx.sessions.begin() as db:
            ctx.audit(db, body.username, "auth.login", "admin", None, {"ip": ip}, "failed", exc.code)
        raise
    response.set_cookie(
        "gpupm_session",
        token,
        httponly=True,
        secure=ctx.config.secure_cookie,
        samesite="strict",
        max_age=28800,
        path="/",
    )
    with ctx.sessions.begin() as db:
        ctx.audit(db, body.username, "auth.login", "admin", None, {"ip": ip})
    return identity


@router.get("/auth/me")
def me(request: Request):
    return request.state.identity


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    request.app.state.auth.logout(request.cookies.get("gpupm_session", ""))
    response.delete_cookie("gpupm_session", path="/")
    return {"status": "ok"}
