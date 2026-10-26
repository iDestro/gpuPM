import os
import pwd
import shlex
import re
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

import psutil

from gpupm.domain.rules import utcnow, parse_time
from gpupm.domain.settings import ignored_process


def identity_key(identity):
    return f"{identity['boot_id']}:{identity['pid']}:{identity['start_ticks']}"


def proc_identity(pid, proc_root=Path("/proc")):
    text = (proc_root / str(pid) / "stat").read_text()
    fields = text[text.rindex(")") + 2 :].split()
    return dict(
        boot_id=(proc_root / "sys/kernel/random/boot_id").read_text().strip(),
        pid=pid,
        start_ticks=int(fields[19]),
    )


def shell_process(process):
    name = process["command"].split(" ", 1)[0].split("/")[-1].lstrip("-")
    return name in {
        "bash",
        "sh",
        "zsh",
        "fish",
        "dash",
        "sshd",
        "systemd",
        "init",
        "gpupm",
        "sudo",
        "su",
        "login",
        "tmux",
        "screen",
    }


def launcher_process(process):
    try:
        argv = process.get("argv") or shlex.split(process["command"])
    except ValueError:
        return False
    if not argv:
        return False
    executable = Path(argv[0]).name
    if executable == "torchrun":
        return True
    if not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", executable):
        return False
    args = argv[1:]
    while args and args[0] in {"-u", "-B", "-E", "-I", "-s", "-S", "-O", "-OO"}:
        args = args[1:]
    return bool(
        args
        and (
            Path(args[0]).name == "torchrun"
            or len(args) >= 2
            and args[0] == "-m"
            and args[1] in {"torch.distributed.run", "torch.distributed.launch"}
        )
    )


def collect():
    gpus = []
    usage = {}
    errors = []
    try:
        import pynvml as nv

        nv.nvmlInit()
        for index in range(nv.nvmlDeviceGetCount()):
            handle = nv.nvmlDeviceGetHandleByIndex(index)
            uuid = nv.nvmlDeviceGetUUID(handle)
            item = dict(
                uuid=uuid,
                index=index,
                name=nv.nvmlDeviceGetName(handle),
                memory_total=None,
                memory_used=None,
                utilization=None,
                error=None,
            )
            try:
                memory = nv.nvmlDeviceGetMemoryInfo(handle)
                item.update(memory_total=memory.total, memory_used=memory.used)
                item["utilization"] = nv.nvmlDeviceGetUtilizationRates(handle).gpu
            except nv.NVMLError as exc:
                item["error"] = str(exc)
            for getter in (nv.nvmlDeviceGetComputeRunningProcesses, nv.nvmlDeviceGetGraphicsRunningProcesses):
                try:
                    for process in getter(handle):
                        amount = process.usedGpuMemory
                        usage.setdefault(process.pid, {})[uuid] = (
                            None if amount is None or amount >= 2**64 - 1 else amount
                        )
                except nv.NVMLError as exc:
                    errors.append(dict(code="nvml_processes_unavailable", message=str(exc)))
            gpus.append(item)
        nv.nvmlShutdown()
    except Exception as exc:
        errors.append(dict(code="nvml_unavailable", message=str(exc)))
    processes = []
    try:
        Path("/proc/sys/kernel/random/boot_id").read_text()
    except OSError as exc:
        errors.append(dict(code="procfs_unavailable", message=str(exc)))
        return gpus, processes, errors
    for process in psutil.process_iter(
        ["pid", "ppid", "uids", "cmdline", "name", "create_time", "status", "exe"]
    ):
        try:
            info = process.info
            identity = proc_identity(process.pid)
            uid = info["uids"].real
            try:
                username = pwd.getpwuid(uid).pw_name
            except KeyError:
                username = str(uid)
            command = " ".join(info["cmdline"] or [info["name"]])
            item = dict(
                identity=identity,
                pid=process.pid,
                ppid=info["ppid"],
                uid=uid,
                username=username,
                command=command,
                argv=info["cmdline"] or [info["name"]],
                exe=info["exe"],
                create_time=datetime.fromtimestamp(info["create_time"], timezone.utc).isoformat(),
                status=info["status"],
                gpu_memory=usage.get(process.pid, {}),
                evidence="NVML + procfs" if process.pid in usage else "confirmed descendant",
            )
            if proc_identity(process.pid) != identity or process.ppid() != info["ppid"]:
                errors.append(
                    dict(
                        code="process_collection_incomplete",
                        pid=process.pid,
                        message="identity or parent changed during collection",
                    )
                )
                continue
            processes.append(item)
        except (psutil.NoSuchProcess, ProcessLookupError, FileNotFoundError):
            continue
        except (psutil.Error, OSError, ValueError) as exc:
            errors.append(dict(code="process_collection_incomplete", pid=process.pid, message=str(exc)))
            continue
    return gpus, processes, errors


def group_processes(processes, previous, excluded=(), ignored_executables=()):
    ignored_by_key = {
        identity_key(p["identity"]): p for p in processes if ignored_process(p, ignored_executables)
    }
    processes = [p for p in processes if identity_key(p["identity"]) not in ignored_by_key]
    by_pid = {p["pid"]: p for p in processes}
    by_key = {identity_key(p["identity"]): p for p in processes}
    observed_keys = by_key.keys() | ignored_by_key.keys()
    assigned = set(excluded)
    owners = {
        key: task["id"]
        for task in previous
        for key in (
            set(task.get("historic_identities", []))
            | {identity_key(m["identity"]) for m in task["members"] + task.get("ignored_members", [])}
        )
    }
    tasks = []
    for old in previous:
        task = dict(old)
        old_members = old["members"] + old.get("ignored_members", [])
        task.setdefault(
            "original_name",
            next((p["command"][:120] for p in old_members if p.get("gpu_memory")), None),
        )
        task["gpu_uuids"] = sorted(
            set(task.get("gpu_uuids", []))
            | {gpu for m in old_members for gpu in m.get("gpu_memory", {})}
        )
        old_pids = {p["pid"] for p in old_members}
        task.setdefault(
            "leader_identities", [p["identity"] for p in old_members if p["ppid"] not in old_pids]
        )
        historic = set(old.get("historic_identities", [])) | {
            identity_key(p["identity"]) for p in old_members
        }
        members = [by_key[key] for key in historic if key in by_key and key not in assigned]
        frontier = {member["pid"] for member in members}
        seen = set(frontier)
        while frontier:
            children = [
                p
                for p in processes
                if p["ppid"] in frontier
                and p["pid"] not in seen
                and p["uid"] == old["uid"]
                and identity_key(p["identity"]) not in assigned
                and not shell_process(p)
                and owners.get(identity_key(p["identity"]), old["id"]) == old["id"]
                and by_pid[p["ppid"]]["identity"]["start_ticks"] <= p["identity"]["start_ticks"]
            ]
            members.extend(children)
            frontier = {p["pid"] for p in children}
            seen |= frontier
            historic.update(identity_key(p["identity"]) for p in children)
        known_ignored = {
            identity_key(p["identity"]): p
            for p in old_members
            if identity_key(p["identity"]) not in by_key and ignored_process(p, ignored_executables)
        }
        known_ignored.update({key: ignored_by_key[key] for key in historic if key in ignored_by_key})
        task["ignored_members"] = list(known_ignored.values())
        task["ignored"] = bool(known_ignored and not members)
        task["members"] = members
        task["historic_identities"] = sorted(historic)
        task["status"] = "running" if members else "finished"
        task["anomalies"] = []
        if members and any(p["ppid"] == 1 and p["identity"] not in task["leader_identities"] for p in members):
            task["anomalies"].append("orphan")
        if any(p["status"] in {"zombie", "Z"} for p in members):
            task["anomalies"].append("zombie")
        assigned.update(identity_key(p["identity"]) for p in members)
        tasks.append(task)
    for process in sorted(processes, key=lambda p: p["create_time"]):
        key = identity_key(process["identity"])
        if not process["gpu_memory"] or key in assigned:
            continue
        root = process
        # Unknown supervisors stay context-only; only explicit supported launchers widen membership.
        seen = set()
        while root["ppid"] in by_pid and root["ppid"] not in seen:
            seen.add(root["pid"])
            parent = by_pid[root["ppid"]]
            if (
                parent["uid"] != process["uid"]
                or not launcher_process(parent)
                or shell_process(parent)
                or parent["pid"] <= 1
                or parent["identity"]["start_ticks"] > root["identity"]["start_ticks"]
            ):
                break
            root = parent
        members = []
        frontier = {root["pid"]}
        while frontier:
            candidates = [
                p
                for p in processes
                if p["pid"] in frontier
                and p["uid"] == process["uid"]
                and identity_key(p["identity"]) not in assigned
                and not shell_process(p)
            ]
            if not candidates:
                break
            members.extend(candidates)
            assigned.update(identity_key(p["identity"]) for p in candidates)
            frontier = {
                p["pid"]
                for p in processes
                if p["ppid"] in {m["pid"] for m in candidates}
                and p["uid"] == process["uid"]
                and by_pid[p["ppid"]]["identity"]["start_ticks"] <= p["identity"]["start_ticks"]
            }
        if not members:
            continue
        tasks.append(
            dict(
                id=str(uuid4()),
                name=process["command"][:120],
                original_name=process["command"][:120],
                uid=process["uid"],
                username=process["username"],
                started_at=min(m["create_time"] for m in members),
                members=members,
                context=[],
                historic_identities=[identity_key(m["identity"]) for m in members],
                leader_identities=[root["identity"]],
                notes="",
                priority=50,
                protected=False,
                revision=1,
                status="running",
                expires_at=None,
                max_runtime_seconds=None,
                deadline_action="notify",
                cleanup_orphans=False,
                policy_status="unconfirmed",
                anomalies=[],
            )
        )
    for task in tasks:
        task["gpu_uuids"] = sorted(
            set(task.get("gpu_uuids", []))
            | {gpu for m in task["members"] for gpu in m.get("gpu_memory", {})}
        )
        task.setdefault("ignored", False)
        leaders = task.get("leader_identities", [])
        task["leaders_present"] = any(identity_key(i) in observed_keys for i in leaders)
        task["orphan_cleanup_due"] = bool(
            task["members"]
            and leaders
            and not any(identity_key(i) in observed_keys for i in leaders)
            and not any(m["gpu_memory"] for m in task["members"])
        )
        member_keys = {identity_key(m["identity"]) for m in task["members"]}
        context = {}
        for member in task["members"]:
            current = member
            seen = {current["pid"]}
            for _ in range(32):
                parent = by_pid.get(current["ppid"])
                if (
                    not parent
                    or parent["pid"] in seen
                    or parent["identity"]["start_ticks"] > current["identity"]["start_ticks"]
                ):
                    break
                seen.add(parent["pid"])
                key = identity_key(parent["identity"])
                if key not in member_keys:
                    context[key] = parent
                current = parent
        task["context"] = list(context.values())
        blocked = {}
        now = utcnow()
        for member in task["members"]:
            key = identity_key(member["identity"])
            if member["status"] in {"D", psutil.STATUS_DISK_SLEEP}:
                since = task.get("blocked_since", {}).get(key, now.isoformat())
                blocked[key] = since
                member["uninterruptible_since"] = since
                member["uninterruptible_seconds"] = max(0, int((now - parse_time(since)).total_seconds()))
                if (
                    member["uninterruptible_seconds"] >= 30
                    and "uninterruptible_sustained" not in task["anomalies"]
                ):
                    task["anomalies"].append("uninterruptible_sustained")
            else:
                member.pop("uninterruptible_since", None)
                member.pop("uninterruptible_seconds", None)
        task["blocked_since"] = blocked
        before = {
            identity_key(p["identity"])
            for p in next((t for t in previous if t["id"] == task["id"]), task)["members"]
        }
        after = {identity_key(p["identity"]) for p in task["members"]}
        if before != after:
            task["revision"] += 1
    return tasks


def signal_identity(
    identity, sig, protected_uids=(), *, expected_uid=None, human_check=None, ignored_executables=()
):
    import signal

    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise RuntimeError("Linux pidfd signaling required")
    try:
        fd = os.pidfd_open(identity["pid"])
    except ProcessLookupError:
        return "exited"
    try:
        if proc_identity(identity["pid"]) != identity:
            return "identity_changed"
        process = psutil.Process(identity["pid"])
        command = " ".join(process.cmdline())
        if (
            process.uids().real in {0, *protected_uids}
            or shell_process(dict(command=command))
            or identity["pid"] <= 1
        ):
            return "protected"
        if proc_identity(identity["pid"]) != identity:
            return "identity_changed"
        current_uid = process.uids().real
        if (expected_uid is not None and current_uid != expected_uid) or (
            human_check is not None and not human_check(current_uid)
        ):
            return "scope_changed"
        paths = ignored_executables() if callable(ignored_executables) else ignored_executables
        if ignored_process({"exe": process.exe()}, paths):
            return "ignored_executable"
        signal.pidfd_send_signal(fd, sig)
        return "signaled"
    except (ProcessLookupError, psutil.NoSuchProcess, FileNotFoundError):
        return "exited"
    finally:
        os.close(fd)


def process_state(identity):
    if not Path("/proc/sys/kernel/random/boot_id").exists():
        return "unavailable"
    try:
        if proc_identity(identity["pid"]) != identity:
            return "identity_changed"
        status = psutil.Process(identity["pid"]).status()
        if proc_identity(identity["pid"]) != identity:
            return "identity_changed"
        return "zombie" if status == psutil.STATUS_ZOMBIE else "alive"
    except (FileNotFoundError, ProcessLookupError, psutil.NoSuchProcess):
        return "exited"
    except (OSError, ValueError, psutil.Error):
        return "unavailable"


def residual_ready(task, now):
    leaders = task.get("leader_identities", [])
    if not leaders or not all(valid_leader_identity(i) for i in leaders):
        return False
    since = parse_time(task.get("finalizing_since"))
    return bool(
        task.get("members")
        and since
        and task.get("leader_identities")
        and not task.get("leaders_present", False)
        and task.get("orphan_reminder", True)
        and (now - since).total_seconds() >= task.get("orphan_wait_seconds", 300)
        and task.get("is_human")
        and not task.get("protected")
        and not any(m.get("gpu_memory") for m in task["members"])
        and not any(i in [m["identity"] for m in task["members"]] for i in task.get("leader_identities", []))
    )


def residual_status(task, now, cleaning=False):
    leaders = task.get("leader_identities", [])
    if task["members"]:
        task["last_seen_at"] = now.isoformat()
        task["finished_at"] = None
    elif task.get("last_seen_at") and not task.get("finished_at"):
        # This is collection-confirmed exit time; legacy ended tasks remain unknown.
        task["finished_at"] = now.isoformat()
    if not task["members"]:
        task.update(status="finished", finalizing_since=None, orphan_remaining_seconds=None)
    elif (
        not leaders
        or task.get("leaders_present", False)
        or any(i in [m["identity"] for m in task["members"]] for i in leaders)
    ):
        task.update(status="running", finalizing_since=None, orphan_remaining_seconds=None)
    else:
        task["finalizing_since"] = task.get("finalizing_since") or now.isoformat()
        task["orphan_remaining_seconds"] = max(
            0,
            task.get("orphan_wait_seconds", 300)
            - int((now - parse_time(task["finalizing_since"])).total_seconds()),
        )
        task["status"] = (
            "cleaning" if cleaning else ("awaiting_cleanup" if residual_ready(task, now) else "finalizing")
        )


def valid_leader_identity(identity):
    return bool(
        isinstance(identity, dict)
        and isinstance(identity.get("boot_id"), str)
        and identity["boot_id"]
        and type(identity.get("pid")) is int
        and identity["pid"] > 1
        and type(identity.get("start_ticks")) is int
        and identity["start_ticks"] >= 0
    )
