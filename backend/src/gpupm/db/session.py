from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from gpupm.db.models import Base, ManagementGroup, Setting

DEFAULT_SETTINGS = {
    "scan_interval_seconds": 5,
    "term_grace_seconds": 10,
    "default_max_runtime_seconds": None,
    "default_deadline_action": "notify",
    "storage_scan_interval_seconds": 900,
    "warning_percent": 80,
    "critical_percent": 90,
}


def database(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")

    # Fresh installs only; subsequent schema upgrades are through Alembic.
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        if session.get(ManagementGroup, 1) is None:
            session.add(ManagementGroup(id=1, name="未分组", priority=50, notes="", is_default=True))
        if session.get(Setting, 1) is None:
            session.add(Setting(id=1, values=DEFAULT_SETTINGS.copy()))
    path.chmod(0o600)
    return engine, factory


def columns(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}
