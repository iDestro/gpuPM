import re
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if result.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return result.astimezone(timezone.utc)


def priority_key(*values: int) -> tuple[int, ...]:
    if len(values) != 3 or any(type(v) is not int or not 0 <= v <= 100 for v in values):
        raise ValueError("优先级必须为 0～100 整数")
    return values


def deadline(start: datetime, max_runtime: int | None, expires: datetime | None) -> datetime | None:
    start = parse_time(start)
    candidates = []
    if max_runtime is not None:
        if type(max_runtime) is not int or max_runtime <= 0:
            raise ValueError("最大运行时长必须大于 0")
        candidates.append(start + timedelta(seconds=max_runtime))
    if expires is not None:
        candidates.append(parse_time(expires))
    return min(candidates) if candidates else None


def task_timing(task, now):
    started = parse_time(task["started_at"])
    due = deadline(started, task.get("max_runtime_seconds"), parse_time(task.get("expires_at")))
    finished = task["status"] == "finished"
    observed_end = parse_time(task.get("finished_at")) if finished else now
    return dict(
        deadline_at=due.isoformat() if due else None,
        runtime_seconds=max(0, (observed_end - started).total_seconds()) if observed_end else None,
        remaining_seconds=(due - now).total_seconds() if due and not finished else None,
        overdue=bool(due and due <= now and not finished),
    )


def account_status(*, deleted, disabled, expired):
    return "deleted" if deleted else "disabled" if disabled else "expired" if expired else "active"


def validate_name(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", name) or name in {"root", "shared", "gpupm"}:
        raise ValueError("名称必须为小写字母开头的 1～31 位字母、数字、下划线或连字符，且不能为保留名称")
    return name
