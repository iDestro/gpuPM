"""Rehearse release database compatibility on private copies; never run services or tick.

Run with the backend Python environment, for example:
  python scripts/release_acceptance.py --current-source backend/src \
      --previous-source /srv/previous/backend/src --api-db /path/app.db --agent-db /path/agent.db

This proves SQLite backup/restore and release startup/migration/read compatibility on
clones, not native account rollback, service restart, reboot or package compatibility.
Live source writes make the originals check inconclusive; use quiesced inputs for proof.
"""

import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


def encode(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def connect_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def snapshot(path):
    with connect_readonly(path) as db:
        db.execute("BEGIN")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("integrity_check_failed")
        schema = db.execute(
            "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
        ).fetchall()
        tables = {}
        for kind, name, _ in schema:
            if kind != "table":
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            cursor = db.execute(f"SELECT * FROM {quoted}")
            columns = [column[0] for column in cursor.description]
            rows = []
            for row in cursor:
                values = {}
                for key, value in zip(columns, row):
                    if isinstance(value, bytes):
                        value = {"blob_hex": value.hex()}
                    elif isinstance(value, str) and value[:1] in ("{", "["):
                        try:
                            value = json.loads(value)
                        except ValueError:
                            pass
                    values[key] = value
                rows.append(values)
            tables[name] = sorted(rows, key=encode)
        return {"schema": schema, "tables": tables}


def fingerprint(path):
    return digest(snapshot(path))


def backup(source, destination):
    fd = os.open(
        destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    os.close(fd)
    with connect_readonly(source) as source_db, sqlite3.connect(destination) as target:
        source_db.backup(target)


def durable(api, agent):
    tables = snapshot(api)["tables"]
    rows = snapshot(agent)["tables"]["state"]
    state = next(row["data"] for row in rows if row["id"] == 1)
    # Startup invalidates runtime confirmations and recovers jobs, not task policy.
    runtime = {
        "status",
        "policy_status",
        "deadline_handled_revision",
        "cleanup_handled_revision",
        "recovery_attempt",
    }
    return {
        "api": tables,
        "agent": {
            **{
                key: state.get(key, {}) if key == "quotas" else state[key]
                for key in ("accounts", "groups", "shares", "quotas", "settings")
            },
            "account_lifecycle": {
                key: {
                    k: v
                    for k, v in account.items()
                    if k
                    in {
                        "disabled",
                        "deleted_at",
                        "expires_on",
                        "lifecycle",
                        "creation",
                        "disable_reason",
                        "disabled_reason",
                        "disabled_at",
                        "expiry_reason",
                    }
                }
                for key, account in state["accounts"].items()
            },
            "task_configuration": [
                {k: v for k, v in task.items() if k not in runtime}
                for task in state["tasks"]
            ],
        },
    }


def preserved(before, after):
    if isinstance(before, dict):
        return isinstance(after, dict) and all(
            key in after and preserved(value, after[key])
            for key, value in before.items()
        )
    if isinstance(before, list):
        if not isinstance(after, list):
            return False
        remaining = list(after)
        for item in before:
            match = next(
                (
                    index
                    for index, candidate in enumerate(remaining)
                    if preserved(item, candidate)
                ),
                None,
            )
            if match is None:
                return False
            remaining.pop(match)
        return True
    return before == after


def policy_migration_preserved(before, after):
    """Allow only the documented, audited group-assignment migration on clones."""
    adjusted = copy.deepcopy(after)
    old_tables, new_tables = before["api"], adjusted["api"]
    audits = new_tables.get("audit_logs", [])
    for table, action, key in (("management_groups", "group.policy_migration", "id"), ("managed_users", "user.policy_migration", "uid")):
        for old in old_tables.get(table, []):
            new = next((r for r in new_tables.get(table, []) if r[key] == old[key]), None)
            event = next((e for e in audits if e.get("actor") == "system" and e.get("action") == action and e.get("target") == str(old[key]) and preserved(old, e.get("before")) and preserved(e.get("after"), new)), None)
            if new is None or event is None:
                continue
            if table == "management_groups" and old.get("is_default") and new.get("name") == "默认组":
                new["name"] = old["name"]
            if table == "managed_users" and old.get("priority") != 50 and new.get("personal_policy") == {"priority": old["priority"]}:
                custom = next((g for g in new_tables.get("management_groups", []) if g.get("id") == new.get("group_id") and g.get("is_custom")), None)
                if custom:
                    new["group_id"] = old["group_id"]
    old_default = next((g for g in old_tables.get("management_groups", []) if g.get("is_default")), None)
    if old_default and old_default["priority"] != 50:
        for old in old_tables.get("settings", []):
            new = next((r for r in new_tables.get("settings", []) if r["id"] == old["id"]), None)
            if new and new.get("policy_epoch") and not old.get("policy_epoch") and new["values"].get("default_task_priority") == old_default["priority"]:
                if "default_task_priority" in old["values"]:
                    new["values"]["default_task_priority"] = old["values"]["default_task_priority"]
    return preserved(before, adjusted)


def evidence(data):
    return {
        kind: {
            key: {"count": len(value), "sha256": digest(value)}
            for key, value in section.items()
        }
        for kind, section in data.items()
    }


def source_root(path):
    path = Path(path).resolve()
    if (path / "backend/src/gpupm").is_dir():
        path /= "backend/src"
    if (
        not (path / "gpupm/db/session.py").is_file()
        or not (path / "gpupm/agent/host.py").is_file()
    ):
        raise ValueError("release_source_missing")
    return path


def probe(source, api, agent):
    """Worker process: release imports and initialization target clones only."""
    release = source_root(source)
    sys.path.insert(0, str(release))
    from gpupm.agent.host import AgentService
    from gpupm.db.models import Base
    from gpupm.db.session import database
    from sqlalchemy import select

    for symbol in (AgentService, Base, database):
        origin = Path(sys.modules[symbol.__module__].__file__).resolve()
        if not origin.is_relative_to(release):
            raise RuntimeError("release_import_mismatch")

    def forbidden(*args, **kwargs):
        raise RuntimeError("native_action_forbidden")

    # Fail closed if a release starts workers or bypasses injected native hooks.
    threading.Thread.start = forbidden
    subprocess.Popen = forbidden
    os.system = forbidden
    os.kill = forbidden
    engine, factory = database(Path(api))
    try:
        with factory() as session:
            for mapper in Base.registry.mappers:
                session.execute(select(mapper.class_)).all()
    finally:
        engine.dispose()
    root = Path(agent).parent
    service = AgentService(
        {
            "store_path": str(agent),
            "allow_mutations": False,
            "home_base": str(root / "home"),
            "data_base": str(root / "data"),
            "share_base": str(root / "shared"),
        },
        collector=forbidden,
        executor=forbidden,
        signaler=forbidden,
        process_checker=lambda identity: "unconfirmed",
    )
    with service.database() as db:
        service.load(db)
    return {"opened": True}


def run_probe(source, api, agent):
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--probe",
                str(source),
                str(api),
                str(agent),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=Path(api).parent,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        return (
            json.loads(result.stdout)
            if result.returncode == 0
            else {"opened": False, "error": "release_probe_failed"}
        )
    except (subprocess.TimeoutExpired, ValueError):
        return {"opened": False, "error": "release_probe_failed"}


def inspect_phase(source, api, agent, baseline, phase):
    report = run_probe(source, api, agent)
    try:
        after = durable(api, agent)
        report.update(
            durable_data_preserved=policy_migration_preserved(baseline, after), persisted=evidence(after)
        )
    except (KeyError, ValueError, sqlite3.DatabaseError):
        report.update(durable_data_preserved=False, error="clone_state_unreadable")
    return {**report, "phase": phase}


def source_fingerprint(source):
    return digest(
        [
            (
                str(path.relative_to(source)),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in sorted(source.rglob("*.py"))
        ]
    )


def rehearse(current_source, previous_source, api_db, agent_db):
    current, previous = source_root(current_source), source_root(previous_source)
    originals = [Path(api_db).resolve(), Path(agent_db).resolve()]
    if originals[0] == originals[1] or not all(path.is_file() for path in originals):
        raise ValueError("two_existing_databases_required")
    before = [fingerprint(path) for path in originals]
    result = {
        "scope": "isolated_database_startup_compatibility",
        "phases": [],
        "limits": [
            "No services, sockets, tick, native commands, reboot or package upgrade executed; startup migrations run on isolated copies.",
            "Runtime confirmations, heartbeat and interrupted job bookkeeping are excluded from durable policy comparisons.",
            "Separate SQLite snapshots are not a cross-database atomic transaction.",
        ],
    }
    with tempfile.TemporaryDirectory(prefix="gpupm-release-acceptance-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        backups = [root / "api.backup", root / "agent.backup"]
        clones = [root / "api.clone", root / "agent.clone"]
        for original, saved, clone in zip(originals, backups, clones):
            backup(original, saved)
            backup(saved, clone)
        baseline = durable(*backups)
        result["baseline"] = evidence(baseline)
        result["backup_matches_initial_snapshot"] = before == [
            fingerprint(path) for path in backups
        ]
        for phase, source in (
            ("previous_baseline", previous),
            ("current_upgrade", current),
            ("previous_rollback", previous),
        ):
            result["phases"].append(inspect_phase(source, *clones, baseline, phase))
        restored = [root / "api.restored", root / "agent.restored"]
        for saved, restore in zip(backups, restored):
            backup(saved, restore)
        result["restore_exact"] = [fingerprint(path) for path in restored] == [
            fingerprint(path) for path in backups
        ]
        result["phases"].append(
            inspect_phase(previous, *restored, baseline, "previous_restored")
        )
    result["originals_unchanged"] = before == [fingerprint(path) for path in originals]
    result["ok"] = (
        result["originals_unchanged"]
        and result["backup_matches_initial_snapshot"]
        and result["restore_exact"]
        and all(
            item["opened"] and item["durable_data_preserved"]
            for item in result["phases"]
        )
    )
    result["source_tree_distinct"] = current != previous
    result["release_source_sha256"] = {
        "current": source_fingerprint(current),
        "previous": source_fingerprint(previous),
    }
    if (
        not result["originals_unchanged"]
        or not result["backup_matches_initial_snapshot"]
    ):
        result["originals_check"] = "inconclusive_source_changed_during_rehearsal"
    else:
        result["originals_check"] = "logical_contents_unchanged"
    return result


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "--probe":
        try:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = probe(*sys.argv[2:])
        except Exception as exc:  # noqa: BLE001 -- sanitized CLI boundary; never emit database values
            result = {"opened": False, "error": type(exc).__name__}
        print(json.dumps(result))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("current-source", "previous-source", "api-db", "agent-db"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = rehearse(
            args.current_source, args.previous_source, args.api_db, args.agent_db
        )
    except Exception as exc:  # noqa: BLE001 -- sanitized CLI boundary; never emit database values
        result = {
            "ok": False,
            "error": type(exc).__name__,
            "scope": "isolated_database_startup_compatibility",
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
