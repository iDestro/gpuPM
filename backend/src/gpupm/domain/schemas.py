from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from gpupm.domain.rules import validate_name

Priority = Annotated[int, Field(strict=True, ge=0, le=100)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(max_length=1024)


class GroupInput(Input):
    name: str = Field(min_length=1, max_length=64)
    priority: Priority = 50
    notes: str = Field(default="", max_length=4096)


class GroupPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    priority: Priority | None = None
    notes: str | None = Field(default=None, max_length=4096)


class UserPatch(Input):
    group_id: int | None = Field(default=None, gt=0)
    priority: Priority | None = None
    notes: str | None = Field(default=None, max_length=4096)


class TaskPatch(Input):
    revision: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=4096)
    priority: Priority | None = None
    protected: bool | None = None
    expires_at: datetime | None = None
    max_runtime_seconds: int | None = Field(default=None, gt=0, le=315360000)
    deadline_action: Literal["notify", "terminate"] | None = None
    cleanup_orphans: bool | None = None
    orphan_reminder: bool | None = Field(default=None, strict=True)
    orphan_wait_seconds: int | None = Field(default=None, strict=True, ge=1, le=86400)

    @field_validator("expires_at")
    @classmethod
    def aware_time(cls, value):
        if value and value.tzinfo is None:
            raise ValueError("到期时间必须带时区")
        return value


class ProcessIdentity(Input):
    boot_id: str = Field(min_length=1, max_length=64)
    pid: int = Field(gt=1)
    start_ticks: int = Field(ge=0)


class TerminationPreview(Input):
    residual_only: bool = Field(default=False, strict=True)
    identity: ProcessIdentity | None = None


class Terminate(Input):
    token: str = Field(min_length=16, max_length=128)
    reason: str = Field(min_length=1, max_length=1024)
    idempotency_key: str = Field(min_length=8, max_length=128)


class SettingsPatch(Input):
    scan_interval_seconds: int | None = Field(default=None, ge=1, le=300)
    term_grace_seconds: int | None = Field(default=None, ge=1, le=120)
    default_max_runtime_seconds: int | None = Field(default=None, strict=True, gt=0, le=315360000)
    default_task_protected: bool | None = Field(default=None, strict=True)
    default_task_priority: Priority | None = None
    default_cleanup_orphans: bool | None = Field(default=None, strict=True)
    default_orphan_reminder: bool | None = Field(default=None, strict=True)
    default_orphan_wait_seconds: int | None = Field(default=None, strict=True, ge=1, le=86400)
    default_deadline_action: Literal["notify", "terminate"] | None = None
    storage_scan_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    warning_percent: int | None = Field(default=None, ge=1, le=99)
    critical_percent: int | None = Field(default=None, ge=2, le=100)


class AccountCreate(Input):
    username: str
    password: SecretStr | None = None
    public_keys: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=4096)
    groups: list[str] = Field(default_factory=list, max_length=32)
    group_id: int = Field(default=1, gt=0)
    priority: Priority = 50
    require_password_change: bool = True
    expires_on: date | None = None
    shell: Literal["/bin/bash", "/usr/sbin/nologin"] = "/bin/bash"

    @field_validator("username")
    @classmethod
    def safe_name(cls, value):
        return validate_name(value)

    @field_validator("password")
    @classmethod
    def password_length(cls, value):
        if value is not None and not 12 <= len(value.get_secret_value()) <= 1024:
            raise ValueError("密码长度必须为 12～1024 位")
        return value

    @model_validator(mode="after")
    def credentials(self):
        if not self.password and not self.public_keys:
            raise ValueError("至少配置密码或 SSH 公钥")
        return self


class AccountPatch(Input):
    primary_group: str | None = Field(default=None, min_length=1, max_length=32)
    reason: str = Field(default="管理员修改", max_length=1024)
    managed: bool | None = None
    revision: int = Field(gt=0)
    token: str | None = Field(default=None, min_length=16, max_length=128)
    username: str | None = None
    notes: str | None = Field(default=None, max_length=4096)
    shell: Literal["/bin/bash", "/usr/sbin/nologin"] | None = None
    groups: list[str] | None = Field(default=None, max_length=32)
    public_keys: list[str] | None = Field(default=None, max_length=20)
    expires_on: date | None = None
    require_password_change: bool | None = None
    group_id: int | None = Field(default=None, gt=0)
    priority: Priority | None = None

    @field_validator("username")
    @classmethod
    def safe_name(cls, value):
        return validate_name(value) if value else value


class AccountPreview(Input):
    action: Literal["disable", "enable", "delete", "restore", "update"]
    revision: int = Field(gt=0)
    changes: dict = Field(default_factory=dict)


class Confirm(Input):
    token: str = Field(min_length=16, max_length=128)
    revision: int = Field(gt=0)
    reason: str = Field(default="管理员操作", min_length=1, max_length=1024)


class PasswordReset(Input):
    revision: int = Field(gt=0)
    token: str = Field(min_length=16, max_length=128)
    reason: str = Field(default="管理员密码重置", max_length=1024)
    password: SecretStr
    require_password_change: bool = True

    @field_validator("password")
    @classmethod
    def password_length(cls, value):
        return AccountCreate.password_length(value)


class QuotaInput(Input):
    filesystem_id: str = Field(min_length=1, max_length=128)
    soft_bytes: int = Field(default=0, ge=0)
    hard_bytes: int = Field(default=0, ge=0)
    soft_inodes: int = Field(default=0, ge=0)
    hard_inodes: int = Field(default=0, ge=0)
    grace_seconds: int | None = Field(default=None, ge=0, le=31536000)

    @model_validator(mode="after")
    def limits(self):
        if self.hard_bytes and self.soft_bytes > self.hard_bytes:
            raise ValueError("空间软限额不能大于硬限额")
        if self.hard_inodes and self.soft_inodes > self.hard_inodes:
            raise ValueError("inode 软限额不能大于硬限额")
        return self


class SystemGroupInput(Input):
    name: str
    members: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("name")
    @classmethod
    def safe_name(cls, value):
        return validate_name(value)


class ShareInput(Input):
    token: str | None = None
    reason: str = Field(default="共享授权", max_length=1024)
    name: str
    reader_group: str
    writer_group: str
    notes: str = Field(default="", max_length=4096)

    @field_validator("name", "reader_group", "writer_group")
    @classmethod
    def safe_name(cls, value):
        return validate_name(value)


class QuotaPatch(QuotaInput):
    token: str | None = None
    reason: str = Field(default="配额配置", max_length=1024)
