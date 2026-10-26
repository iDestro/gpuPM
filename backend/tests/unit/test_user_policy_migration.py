import sqlite3
from sqlalchemy import select
from gpupm.db.session import database
from gpupm.db.models import ManagementGroup, ManagedUser, Setting, AuditLog


def test_old_database_upgrade_is_idempotent_and_preserves_legacy_values(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE management_groups (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, priority INTEGER NOT NULL, notes TEXT NOT NULL, is_default BOOLEAN NOT NULL);
        CREATE TABLE managed_users (uid INTEGER PRIMARY KEY, username TEXT NOT NULL, group_id INTEGER NOT NULL REFERENCES management_groups(id), priority INTEGER NOT NULL, notes TEXT NOT NULL, account_id TEXT);
        CREATE TABLE settings (id INTEGER PRIMARY KEY, "values" JSON NOT NULL);
        CREATE TABLE task_policies (task_id TEXT PRIMARY KEY, policy JSON NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL);
        INSERT INTO management_groups VALUES (1,'未分组',65,'',1),(2,'自定义组',80,'',0);
        INSERT INTO managed_users VALUES (1001,'alice',2,91,'note','account');
        INSERT INTO settings VALUES (1,'{}');
        INSERT INTO task_policies VALUES ('running','{"max_runtime_seconds":3600}',8,'applied');
        """)
    engine, sessions = database(path)
    with sessions() as db:
        custom = db.scalar(select(ManagementGroup).where(ManagementGroup.is_custom.is_(True)))
        assert custom.id != 2
        user = db.get(ManagedUser, 1001)
        assert user.group_id == custom.id
        assert user.personal_policy == {"priority": 91}
        assert user.priority == 91 and user.notes == "note"
        assert db.get(ManagementGroup, 2).policy_overrides == {"priority": 80}
        assert db.get(Setting, 1).values["default_task_priority"] == 65
        audit_count = len(list(db.scalars(select(AuditLog))))
        epoch = db.get(Setting, 1).policy_epoch
    engine.dispose()
    engine, sessions = database(path)
    with sessions() as db:
        assert len(list(db.scalars(select(AuditLog)))) == audit_count
        assert db.get(Setting, 1).policy_epoch == epoch
    engine.dispose()


def test_release_acceptance_allows_only_audited_migration(tmp_path):
    import copy
    from test_release_acceptance import harness

    module = harness()
    path = tmp_path / "migration.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE management_groups (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, priority INTEGER NOT NULL, notes TEXT NOT NULL, is_default BOOLEAN NOT NULL);
        CREATE TABLE managed_users (uid INTEGER PRIMARY KEY, username TEXT NOT NULL, group_id INTEGER NOT NULL REFERENCES management_groups(id), priority INTEGER NOT NULL, notes TEXT NOT NULL, account_id TEXT);
        CREATE TABLE settings (id INTEGER PRIMARY KEY, "values" JSON NOT NULL);
        INSERT INTO management_groups VALUES (1,'未分组',65,'',1),(2,'research',80,'',0);
        INSERT INTO managed_users VALUES (1001,'alice',2,91,'keep','account');
        INSERT INTO settings VALUES (1,'{"default_task_priority":50}');
        """)
    before = {"api": module.snapshot(path)["tables"], "agent": {"unchanged": True}}
    engine, _ = database(path)
    engine.dispose()
    after = {"api": module.snapshot(path)["tables"], "agent": {"unchanged": True}}
    assert module.policy_migration_preserved(before, after)
    corrupted = copy.deepcopy(after)
    corrupted["api"]["managed_users"][0]["notes"] = "lost"
    assert not module.policy_migration_preserved(before, corrupted)
    corrupted = copy.deepcopy(after)
    corrupted["agent"]["unchanged"] = False
    assert not module.policy_migration_preserved(before, corrupted)


def test_existing_partial_task_policy_preserves_root_settings_and_legacy_rank(tmp_path):
    from gpupm.agent.demo import DemoAgent
    from gpupm.api.main import create_app
    from gpupm.config import Config
    from gpupm.db.models import TaskConfig

    api, agent_path = tmp_path / "api.db", tmp_path / "agent.db"
    agent = DemoAgent(agent_path)
    root_task = agent.call("snapshot")["tasks"][0]
    engine, sessions = database(api)
    with sessions.begin() as db:
        group = ManagementGroup(name="old-group", priority=80)
        db.add(group)
        db.flush()
        db.add(
            ManagedUser(uid=1001, username="alice", group_id=group.id, priority=91, account_id="demo-alice")
        )
        db.add(
            TaskConfig(
                task_id=root_task["id"],
                policy={"notes": "retain"},
                revision=root_task["revision"],
                status="applied",
            )
        )
        # Emulate pre-upgrade records while retaining the current physical schema.
        db.get(Setting, 1).policy_epoch = None
    engine.dispose()
    instance = create_app(Config(mode="demo", database=api, agent_database=agent_path))
    instance.state.ctx.heartbeat()
    with instance.state.sessions() as db:
        policy = db.get(TaskConfig, root_task["id"])
        assert policy.priority_snapshot == [80, 91, root_task["priority"]]
        assert policy.assignment_snapshot == {"group_id": group.id, "group_name": "old-group"}
        assert policy.policy_sources["max_runtime_seconds"] == "legacy"
        assert policy.policy_sources["notes"] == "task"
        assert policy.policy["max_runtime_seconds"] == root_task["max_runtime_seconds"]
        assert policy.policy["notes"] == "retain"
    instance.state.engine.dispose()


def test_finished_task_freezes_legacy_order_without_applying_root_policy(tmp_path):
    from gpupm.api.context import Context
    from gpupm.config import Config
    from gpupm.domain.rules import utcnow
    from gpupm.db.models import TaskConfig

    _, sessions = database(tmp_path / "api.db")
    with sessions.begin() as db:
        group = ManagementGroup(name="legacy", priority=75)
        db.add(group)
        db.flush()
        db.add(ManagedUser(uid=1001, username="alice", group_id=group.id, priority=65))

    class Agent:
        def call(self, method, params):
            if method == "snapshot":
                return dict(
                    collected_at=utcnow().isoformat(),
                    accounts=[],
                    tasks=[
                        dict(
                            id="finished",
                            uid=1001,
                            username="alice",
                            is_human=True,
                            status="finished",
                            revision=4,
                            started_at="2020-01-01T00:00:00+00:00",
                            priority=55,
                            max_runtime_seconds=7200,
                        )
                    ],
                )
            if method == "apply_task_policy":
                raise AssertionError("finished tasks must not receive new root policy")
            if method == "audit_since":
                return []

    ctx = Context(sessions, Agent(), Config())
    ctx.heartbeat()
    with sessions() as db:
        frozen = db.get(TaskConfig, "finished")
        assert frozen.priority_snapshot == [75, 65, 55]
        assert frozen.policy["max_runtime_seconds"] == 7200
        assert frozen.revision == 4
