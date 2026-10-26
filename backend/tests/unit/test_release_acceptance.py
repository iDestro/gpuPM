import importlib.util
import json
import shutil
from pathlib import Path

from gpupm.db.session import database
from gpupm.db.models import ManagementGroup, ManagedUser, Setting, TaskConfig
from gpupm.agent.host import AgentService

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/release_acceptance.py"


def harness():
    spec = importlib.util.spec_from_file_location("release_acceptance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stores(tmp_path):
    api, agent = tmp_path / "app.db", tmp_path / "agent.db"
    engine, factory = database(api)
    with factory.begin() as session:
        session.add(ManagementGroup(id=3, name="private-project", priority=73, notes="secret-note"))
        session.flush()
        session.add(ManagedUser(uid=1001, username="private-user", group_id=3, priority=61))
        session.add(TaskConfig(task_id="persist-task", policy={"max_runtime_seconds": 1234}, revision=7))
        session.get(Setting, 1).values = {"scan_interval_seconds": 17}
    engine.dispose()
    service = AgentService({"store_path": str(agent), "allow_mutations": False})
    with service.database() as db:
        state = service.load(db)
        state["accounts"] = {
            "1001": {
                "disabled": True,
                "disable_reason": "private-reason",
                "creation": {"status": "incomplete"},
            }
        }
        state["groups"] = {"team": {"managed": True}}
        state["tasks"] = [
            {"id": "task", "status": "running", "revision": 5, "priority": 62, "policy_status": "applied"}
        ]
        state["settings"]["scan_interval_seconds"] = 17
        service.save(db, state)
    return api, agent


def test_isolated_upgrade_rollback_preserves_state_and_originals(tmp_path):
    module = harness()
    api, agent = stores(tmp_path)
    source = SCRIPT.parents[1] / "backend/src"
    previous = tmp_path / "previous"
    shutil.copytree(source, previous)
    before = [module.fingerprint(path) for path in (api, agent)]
    result = module.rehearse(source, previous, api, agent)
    assert result["ok"] is True
    assert result["originals_unchanged"] is True
    assert result["restore_exact"] is True
    assert [phase["phase"] for phase in result["phases"]] == [
        "previous_baseline",
        "current_upgrade",
        "previous_rollback",
        "previous_restored",
    ]
    assert all(phase["durable_data_preserved"] for phase in result["phases"])
    assert result["baseline"]["agent"]["accounts"]["count"] == 1
    assert result["baseline"]["api"]["task_policies"]["count"] == 1
    assert [module.fingerprint(path) for path in (api, agent)] == before
    assert "private-reason" not in json.dumps(result)
    assert "secret-note" not in json.dumps(result)


def test_rehearsal_detects_release_dropping_persisted_policy(tmp_path):
    module = harness()
    api, agent = stores(tmp_path)
    source = SCRIPT.parents[1] / "backend/src"
    damaged = tmp_path / "damaged"
    shutil.copytree(source, damaged)
    session = damaged / "gpupm/db/session.py"
    session.write_text(
        session.read_text().replace(
            "return engine, factory",
            "with engine.begin() as connection:\n        connection.exec_driver_sql('DELETE FROM task_policies')\n    return engine, factory",
        )
    )
    result = module.rehearse(damaged, source, api, agent)
    assert result["ok"] is False
    phase = next(item for item in result["phases"] if item["phase"] == "current_upgrade")
    assert phase["durable_data_preserved"] is False
    assert result["originals_unchanged"] is True
    assert result["restore_exact"] is True
