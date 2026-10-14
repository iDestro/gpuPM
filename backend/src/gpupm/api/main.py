import logging
import secrets
import threading
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from gpupm.api.agent_client import AgentClient
from gpupm.api.auth import Auth
from gpupm.api.context import Context
from gpupm.config import Config
from gpupm.db.session import database
from gpupm.errors import DomainError


def create_app(config=None, agent=None):
    config = config or Config.from_env()
    engine, sessions = database(config.database)
    if agent is None:
        if config.mode == "demo":
            from gpupm.agent.demo import DemoAgent

            agent = DemoAgent(config.agent_database)
        else:
            agent = AgentClient(config.agent_socket)

    @asynccontextmanager
    async def lifespan(app):
        stopping = threading.Event()

        def synchronize():
            while not stopping.is_set():
                try:
                    app.state.ctx.heartbeat()
                except (DomainError, OSError):
                    pass
                except Exception as exc:
                    logging.getLogger("gpupm").error(
                        "Background policy synchronization failed: %s", type(exc).__name__
                    )
                try:
                    interval = app.state.ctx.settings()["scan_interval_seconds"]
                except Exception:
                    interval = 5
                stopping.wait(interval)

        worker = threading.Thread(target=synchronize, name="gpupm-policy-sync", daemon=True)
        worker.start()
        try:
            yield
        finally:
            stopping.set()
            worker.join(timeout=20)

    app = FastAPI(title="gpuPM", version="0.1.0", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.config = config
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.auth = Auth(sessions)
    app.state.ctx = Context(sessions, agent, config)

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(
            status_code=exc.status, content={"detail": {"code": exc.code, "message": exc.message}}
        )

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request, exc):
        issues = [{"type": e["type"], "loc": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "validation", "message": "请求参数无效", "issues": issues}},
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(
            status_code=409, content={"detail": {"code": "conflict", "message": "名称或记录已经存在"}}
        )

    @app.middleware("http")
    async def protect(request: Request, call_next):
        public = request.url.path in {"/api/auth/login", "/api/health"}
        if request.url.path.startswith("/api") and not public:
            try:
                identity = app.state.auth.identity(request.cookies.get("gpupm_session"))
                request.state.identity = identity
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    csrf = request.headers.get("X-CSRF-Token", "")
                    if not secrets.compare_digest(csrf, identity["csrf_token"]):
                        raise DomainError("csrf", "CSRF 校验失败", 403)
            except DomainError as exc:
                return await domain_error(request, exc)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.url.netloc:
                return JSONResponse(
                    status_code=403, content={"detail": {"code": "origin", "message": "请求来源无效"}}
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    from gpupm.api.routes import router

    app.include_router(router)

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise DomainError("not_found", "接口不存在", 404)
        base = config.frontend_dist.resolve()
        candidate = (base / path).resolve()
        if not candidate.is_relative_to(base):
            raise DomainError("not_found", "路径不存在", 404)
        if candidate.is_file():
            return FileResponse(candidate)
        if (base / "index.html").is_file():
            return FileResponse(base / "index.html")
        return JSONResponse(
            {"service": "gpuPM", "message": "前端尚未构建，请运行 npm run build", "mode": config.mode}
        )

    return app
