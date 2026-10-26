from pathlib import Path

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import sessionmaker

from gpupm.db.models import Base, ManagementGroup, ManagedUser, Setting, AuditLog
from gpupm.domain.settings import DEFAULT_SETTINGS
from gpupm.domain.rules import utcnow


def database(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")

    # Additive startup migration also upgrades existing trial databases.
    Base.metadata.create_all(engine)
    additions = {
        "management_groups": {
            "is_custom": "BOOLEAN NOT NULL DEFAULT 0",
            "policy_overrides": "JSON NOT NULL DEFAULT '{}'",
        },
        "managed_users": {"personal_policy": "JSON NOT NULL DEFAULT '{}'"},
        "task_policies": {
            "assignment_snapshot": "JSON NOT NULL DEFAULT '{}'",
            "policy_sources": "JSON NOT NULL DEFAULT '{}'",
            "priority_snapshot": "JSON",
        },
        "settings": {"policy_epoch": "VARCHAR(40)"},
    }
    with engine.begin() as connection:
        for table, fields in additions.items():
            present = {c["name"] for c in inspect(connection).get_columns(table)}
            for name, kind in fields.items():
                if name not in present:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {kind}"))
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        if session.get(ManagementGroup, 1) is None:
            session.add(ManagementGroup(id=1, name="默认组", priority=50, notes="", is_default=True))
        setting = session.get(Setting, 1)
        if setting is None:
            session.add(Setting(id=1, values=DEFAULT_SETTINGS.copy()))
        else:
            setting.values = dict(DEFAULT_SETTINGS, **setting.values)
        session.flush()
        setting = session.get(Setting, 1)
        if setting.policy_epoch is None:
            setting.policy_epoch = utcnow().isoformat()
            existing_names = set(session.scalars(select(ManagementGroup.name)))
            custom_name = "自定义组"
            while custom_name in existing_names:
                custom_name += "（内置）"
            custom = ManagementGroup(name=custom_name, is_custom=True, priority=50)
            session.add(custom)
            session.flush()
            for group in session.scalars(select(ManagementGroup)):
                if group.is_custom:
                    continue
                before = columns(group)
                if group.is_default:
                    if group.name != "默认组" and "默认组" not in existing_names:
                        group.name = "默认组"
                    if group.priority != 50:
                        old_values = setting.values.copy()
                        setting.values = dict(setting.values, default_task_priority=group.priority)
                        session.add(
                            AuditLog(
                                time=setting.policy_epoch,
                                actor="system",
                                action="settings.policy_migration",
                                target="settings",
                                before=old_values,
                                after=setting.values.copy(),
                                result="succeeded",
                            )
                        )
                else:
                    group.policy_overrides = {"priority": group.priority}
                session.add(
                    AuditLog(
                        time=setting.policy_epoch,
                        actor="system",
                        action="group.policy_migration",
                        target=str(group.id),
                        before=before,
                        after=columns(group),
                        result="succeeded",
                    )
                )
            for user in session.scalars(select(ManagedUser)):
                if user.priority != 50:
                    before = columns(user)
                    user.personal_policy = {"priority": user.priority}
                    user.group_id = custom.id
                    session.add(
                        AuditLog(
                            time=setting.policy_epoch,
                            actor="system",
                            action="user.policy_migration",
                            target=str(user.uid),
                            before=before,
                            after=columns(user),
                            result="succeeded",
                        )
                    )
    path.chmod(0o600)
    return engine, factory


def columns(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}
