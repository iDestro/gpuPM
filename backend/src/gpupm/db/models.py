from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Admin(Base):
    __tablename__ = "admins"
    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class WebSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(ForeignKey("admins.username"))
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    window: Mapped[float] = mapped_column(Float)


class ManagementGroup(Base):
    __tablename__ = "management_groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class ManagedUser(Base):
    __tablename__ = "managed_users"
    uid: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64))
    group_id: Mapped[int] = mapped_column(ForeignKey("management_groups.id"), default=1)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    notes: Mapped[str] = mapped_column(Text, default="")
    personal_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TaskConfig(Base):
    __tablename__ = "task_policies"
    assignment_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_sources: Mapped[dict] = mapped_column(JSON, default=dict)
    priority_snapshot: Mapped[list | None] = mapped_column(JSON, nullable=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="pending")


class Setting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    policy_epoch: Mapped[str | None] = mapped_column(String(40), nullable=True)
    values: Mapped[dict] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    time: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(128))
    before: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    result: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text, default="")
    event_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
