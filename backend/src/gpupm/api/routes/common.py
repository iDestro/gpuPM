from gpupm.errors import DomainError


def context(request):
    return request.app.state.ctx


def actor(request):
    return request.state.identity["username"]


def safe_audit(value):
    if isinstance(value, dict):
        return {
            k: safe_audit(v)
            for k, v in value.items()
            if k not in {"password", "password_hash", "private_key", "public_keys", "csrf_token", "token"}
        }
    if isinstance(value, list):
        return [safe_audit(v) for v in value]
    return value


def agent_mutation(request, method, params, action, target):
    ctx = context(request)
    params["actor"] = actor(request)
    with ctx.lock:
        with ctx.sessions.begin() as db:
            ctx.audit(
                db,
                actor(request),
                action,
                target,
                None,
                safe_audit(params),
                "pending",
                params.get("reason", ""),
            )
        try:
            result = ctx.agent.call(method, params)
        except DomainError as exc:
            with ctx.sessions.begin() as db:
                ctx.audit(db, actor(request), action, target, None, None, "failed", exc.message)
            raise
        with ctx.sessions.begin() as db:
            ctx.audit(
                db,
                actor(request),
                action,
                target,
                None,
                safe_audit(result),
                "demo" if ctx.config.mode == "demo" else "succeeded",
            )
        ctx.invalidate()
        return result
