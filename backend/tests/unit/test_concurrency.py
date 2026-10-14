from concurrent.futures import ThreadPoolExecutor
import threading

from gpupm.api.auth import Auth
from gpupm.api.context import Context
from gpupm.config import Config
from gpupm.db.session import database
from gpupm.db.models import AuditLog, TaskConfig
from gpupm.errors import DomainError
from sqlalchemy import select, func


def test_parallel_login_attempts_reserve_rate_limit(tmp_path):
    _, sessions = database(tmp_path / "app.db")
    auth = Auth(sessions)
    gate = threading.Barrier(10)

    def attempt(_):
        gate.wait()
        try:
            auth.login("missing", "wrong", "127.0.0.1")
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=10) as workers:
        results = list(workers.map(attempt, range(10)))
    assert results.count("invalid_credentials") == 5
    assert results.count("rate_limited") == 5


def test_parallel_audit_import_is_duplicate_safe(tmp_path):
    _, sessions = database(tmp_path / "app.db")

    class Agent:
        def call(self, method, params):
            return [{"id": "event1", "action": "test", "target": "test"}]

    ctx = Context(sessions, Agent(), Config())
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(lambda _: ctx.synchronize_events(), range(8)))
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 1


def test_heartbeat_registers_new_and_reconfirms_membership_revision(tmp_path):
    _, sessions = database(tmp_path / "app.db")

    class Agent:
        revision = 1
        confirmed = None

        def call(self, method, params):
            if method == "snapshot":
                return {
                    "tasks": [{"id": "task1", "revision": self.revision, "status": "running"}],
                    "collected_at": __import__("datetime")
                    .datetime.now(__import__("datetime").timezone.utc)
                    .isoformat(),
                }
            if method == "apply_task_policy":
                assert params["revision"] == self.revision
                assert params["policy"] == {}
                self.revision += 1
                return {"revision": self.revision}
            if method == "heartbeat":
                self.confirmed = params["policy_versions"]
            if method == "audit_since":
                return []

    agent = Agent()
    ctx = Context(sessions, agent, Config())
    ctx.heartbeat()
    assert agent.confirmed == {"task1": 2}
    agent.revision = 3
    ctx.heartbeat()
    assert agent.confirmed == {"task1": 4}
    with sessions() as db:
        policy = db.get(TaskConfig, "task1")
        policy.status = "failed"
        db.commit()
    ctx.heartbeat()
    assert agent.confirmed == {}


def test_business_identity_resets_when_native_uid_is_reused(tmp_path):
    from gpupm.db.models import ManagedUser
    from gpupm.domain.rules import utcnow

    _, sessions = database(tmp_path / "app.sqlite")

    class Agent:
        lifecycle = "first"

        def call(self, method, params):
            return {
                "accounts": [
                    {"uid": 1001, "username": "alice", "id": "1001", "lifecycle_id": self.lifecycle}
                ],
                "tasks": [],
                "collected_at": utcnow().isoformat(),
            }

    agent = Agent()
    ctx = Context(sessions, agent, Config())
    ctx.users()
    with sessions.begin() as db:
        db.get(ManagedUser, 1001).priority = 99
    agent.lifecycle = "replacement"
    ctx.invalidate()
    assert ctx.users()[0]["priority"] == 50
    with sessions() as db:
        assert db.get(ManagedUser, 1001).account_id == "replacement"


def test_native_protection_is_visible_even_if_requested_policy_clears_it(tmp_path):
    from gpupm.domain.rules import utcnow

    _, sessions = database(tmp_path / "app.sqlite")

    class Agent:
        def call(self, method, params):
            return {
                "accounts": [],
                "gpus": [],
                "source": "host",
                "collected_at": utcnow().isoformat(),
                "tasks": [
                    {
                        "id": "task",
                        "uid": 1000,
                        "username": "operator",
                        "started_at": utcnow().isoformat(),
                        "status": "running",
                        "members": [],
                        "protected": True,
                        "policy_status": "applied",
                        "revision": 1,
                    }
                ],
            }

    ctx = Context(sessions, Agent(), Config())
    with sessions.begin() as db:
        db.add(TaskConfig(task_id="task", policy={"protected": False}, revision=1, status="applied"))
    assert ctx.tasks()[0][0]["protected"] is True
