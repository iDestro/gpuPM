import json
import sqlite3

import pytest
from pydantic import ValidationError

from gpupm.agent.demo import DemoAgent
from gpupm.agent.host import AgentService
from gpupm.db.models import Setting
from gpupm.db.session import database
from gpupm.domain.schemas import SettingsPatch
from gpupm.errors import DomainError


POLICY = {
    "max_runtime_seconds": 1800,
    "protected": False,
    "priority": 50,
    "deadline_action": "notify",
    "cleanup_orphans": False,
    "orphan_reminder": True,
    "orphan_wait_seconds": 300,
}
TEMPLATE = {
    "default_max_runtime_seconds": 1800,
    "default_task_protected": False,
    "default_task_priority": 50,
    "default_deadline_action": "notify",
    "default_cleanup_orphans": False,
    "default_orphan_reminder": True,
    "default_orphan_wait_seconds": 300,
}


def policy(task):
    return {key: task[key] for key in POLICY}


def process(pid, uid=1000, username="alice"):
    return dict(
        identity=dict(boot_id="boot", pid=pid, start_ticks=pid * 10),
        pid=pid,
        ppid=1,
        uid=uid,
        username=username,
        command="python train.py",
        status="S",
        create_time="2026-10-14T00:00:00+00:00",
        gpu_memory={"gpu": 10},
        evidence="proc",
    )


def test_fresh_settings_and_old_json_preserve_explicit_values(tmp_path):
    path = tmp_path / "api.db"
    engine, sessions = database(path)
    with sessions.begin() as db:
        assert TEMPLATE.items() <= db.get(Setting, 1).values.items()
        db.get(Setting, 1).values = {
            "default_max_runtime_seconds": None,
            "default_deadline_action": "terminate",
            "term_grace_seconds": 77,
            "custom_key": "preserved",
        }
    engine.dispose()
    engine, sessions = database(path)
    with sessions() as db:
        values = db.get(Setting, 1).values
        assert values["default_max_runtime_seconds"] is None
        assert values["default_deadline_action"] == "terminate"
        assert values["term_grace_seconds"] == 77
        assert values["custom_key"] == "preserved"
        assert values["default_task_protected"] is False
        assert values["default_task_priority"] == 50
        assert values["default_cleanup_orphans"] is False
    engine.dispose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("default_task_protected", "false"),
        ("default_task_protected", 0),
        ("default_cleanup_orphans", "true"),
        ("default_cleanup_orphans", 1),
        ("default_task_priority", -1),
        ("default_task_priority", 101),
        ("default_task_priority", True),
        ("default_task_priority", "50"),
        ("default_max_runtime_seconds", True),
        ("default_max_runtime_seconds", "1800"),
    ],
)
def test_template_patch_rejects_coerced_or_invalid_values(field, value):
    with pytest.raises(ValidationError):
        SettingsPatch(**{field: value})


def test_template_patch_accepts_all_fields_and_unlimited():
    assert SettingsPatch(**TEMPLATE).model_dump(exclude_unset=True) == TEMPLATE
    assert SettingsPatch(default_max_runtime_seconds=None).model_dump(exclude_unset=True) == {
        "default_max_runtime_seconds": None
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("default_task_protected", "false"),
        ("default_task_protected", 0),
        ("default_task_protected", None),
        ("default_cleanup_orphans", "true"),
        ("default_cleanup_orphans", 1),
        ("default_cleanup_orphans", None),
        ("default_task_priority", -1),
        ("default_task_priority", 101),
        ("default_task_priority", True),
        ("default_task_priority", "50"),
        ("default_task_priority", None),
        ("default_max_runtime_seconds", True),
        ("default_max_runtime_seconds", "1800"),
        ("default_max_runtime_seconds", 315360001),
    ],
)
def test_root_configure_validates_template_at_boundary(tmp_path, field, value):
    service = AgentService(dict(store_path=str(tmp_path / "agent.db")), collector=lambda: ([], [], []))
    with pytest.raises(DomainError) as error:
        service.call("configure", {"settings": {field: value}})
    assert error.value.code == "invalid_settings"
    with service.database() as db:
        assert service.load(db)["settings"] == {
            "ignored_task_executables": ["/usr/lib/xorg/Xorg", "/usr/bin/Xorg"]
        }


def test_root_configure_rejects_readonly_paths(tmp_path):
    service = AgentService(dict(store_path=str(tmp_path / "agent.db")), collector=lambda: ([], [], []))
    with pytest.raises(DomainError) as error:
        service.call("configure", {"settings": {"home_base": "/tmp"}})
    assert error.value.code == "readonly_settings"


def test_native_defaults_only_apply_to_new_ids_and_survive_restart(tmp_path):
    path = tmp_path / "agent.db"
    processes = [process(21)]
    service = AgentService(dict(store_path=str(path)), collector=lambda: ([], processes, []))
    first = service.call("snapshot")["tasks"][0]
    assert policy(first) == POLICY
    assert first["original_name"] == "python train.py"
    custom = dict(
        POLICY,
        max_runtime_seconds=None,
        protected=True,
        priority=7,
        deadline_action="terminate",
        cleanup_orphans=True,
    )
    with service.database() as db:
        state = service.load(db)
        state["tasks"][0].update(custom, name="manual name", notes="preserve")
        service.save(db, state)
    changed = dict(
        default_max_runtime_seconds=90,
        default_task_protected=False,
        default_task_priority=98,
        default_deadline_action="terminate",
        default_cleanup_orphans=True,
    )
    service.call("configure", {"settings": changed})
    processes.append(process(22))
    tasks = service.call("snapshot")["tasks"]
    existing = next(t for t in tasks if t["id"] == first["id"])
    assert policy(existing) == custom
    assert existing["name"] == "manual name" and existing["notes"] == "preserve"
    assert existing["original_name"] == first["original_name"]
    second = next(t for t in tasks if t["id"] != first["id"])
    assert policy(second) == dict(
        POLICY, max_runtime_seconds=90, priority=98, deadline_action="terminate", cleanup_orphans=True
    )
    reopened = AgentService(dict(store_path=str(path)), collector=lambda: ([], processes, []))
    assert {t["id"]: policy(t) for t in reopened.call("snapshot")["tasks"]} == {
        first["id"]: custom,
        second["id"]: policy(second),
    }


@pytest.mark.parametrize("uid,username", [(0, "root"), (999, "service"), (1005, "api"), (1006, "maint")])
def test_mandatory_protection_wins_over_default(tmp_path, uid, username):
    service = AgentService(
        dict(store_path=str(tmp_path / "agent.db"), api_uid=1005, maintenance_users=["maint"]),
        collector=lambda: ([], [process(21, uid, username)], []),
    )
    service.call("configure", {"settings": TEMPLATE})
    task = service.call("snapshot")["tasks"][0]
    assert task["protected"] is True
    assert task["max_runtime_seconds"] == 1800


def test_heartbeat_configures_template_before_first_task_and_preserves_null(tmp_path):
    service = AgentService(
        dict(store_path=str(tmp_path / "agent.db")), collector=lambda: ([], [process(21)], [])
    )
    service.call(
        "heartbeat",
        {
            "settings": dict(
                TEMPLATE,
                default_max_runtime_seconds=None,
                default_task_protected=True,
                default_task_priority=0,
            )
        },
    )
    assert policy(service.call("snapshot")["tasks"][0]) == dict(
        POLICY, max_runtime_seconds=None, protected=True, priority=0
    )


def test_demo_seed_defaults_and_configure_restart_preserve_task_override(tmp_path):
    path = tmp_path / "demo.db"
    agent = DemoAgent(path)
    tasks = agent.call("snapshot")["tasks"]
    assert all(policy(task) == POLICY for task in tasks)
    custom = dict(
        POLICY,
        max_runtime_seconds=None,
        protected=True,
        priority=10,
        deadline_action="terminate",
        cleanup_orphans=True,
    )
    agent.call(
        "apply_task_policy", {"task_id": tasks[0]["id"], "revision": tasks[0]["revision"], "policy": custom}
    )
    agent.call("configure", {"settings": dict(TEMPLATE, default_task_priority=99)})
    before = agent.call("snapshot")["tasks"]
    assert policy(before[0]) == custom
    reopened = DemoAgent(path)
    assert reopened.call("snapshot")["tasks"] == before
    with sqlite3.connect(path) as db:
        state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
    assert state["settings"]["default_task_priority"] == 99
