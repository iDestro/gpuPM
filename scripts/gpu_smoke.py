"""Terminates only fresh tasks of a disposable QA UID, preserves other GPU PIDs."""

import json
import os
from pathlib import Path
import subprocess
import time
from gpupm.agent.host import AgentService
from gpupm.agent.processes import collect, proc_identity
from gpupm.domain.rules import utcnow

assert os.geteuid() == 0
base = Path("/var/lib/gpupm-qa")
service = AgentService(
    dict(
        store_path=str(base / "state.sqlite"),
        allow_mutations=True,
        home_base=str(base / "home"),
        data_base=str(base / "data"),
        share_base=str(base / "data/shared"),
        maintenance_users=["wuzhaoxiang"],
        term_grace_seconds=10,
    )
)
service.call("configure", {"settings": {"term_grace_seconds": 1}})
account = next(
    a
    for a in service.call("list_accounts")
    if a["username"].startswith("gpupmqa_") and a["managed"]
)
uid = account["uid"]
assert uid != 1000 and uid != 0
before = [p["identity"] for p in collect()[1] if p["gpu_memory"] and p["uid"] != uid]
launchers = [
    subprocess.Popen(
        [
            "runuser",
            "-u",
            account["username"],
            "--",
            "python3",
            "/opt/gpupm-qa/gpu_supervisor_fixture.py",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
]
try:
    tasks = []
    for _ in range(30):
        tasks = [
            t
            for t in service.call("snapshot")["tasks"]
            if t["uid"] == uid and any(m["gpu_memory"] for m in t["members"])
        ]
        if len(tasks) == 2 and all(len(t["members"]) == 2 for t in tasks):
            break
        time.sleep(0.2)
    assert len(tasks) == 2 and all(len(t["members"]) == 2 for t in tasks), tasks
    supervisor = next(
        p
        for p in collect()[1]
        if p["uid"] == uid and "gpu_supervisor_fixture.py" in p["command"]
    )
    assert all(
        supervisor["pid"] not in {m["pid"] for m in task["members"]} for task in tasks
    )
    task = tasks[0]
    service.call(
        "apply_task_policy",
        {"task_id": task["id"], "revision": task["revision"], "policy": {}},
    )
    preview = service.call("preview_termination", {"task_id": task["id"]})
    assert len(preview["targets"]) == 2 and all(
        m["uid"] == uid for m in preview["targets"]
    )
    job = service.call(
        "execute_termination",
        {
            "task_id": task["id"],
            "token": preview["token"],
            "reason": "isolated QA",
            "idempotency_key": "gpu-" + task["id"],
        },
    )
    for worker in list(service.workers.values()):
        worker.join(timeout=8)
    job = service.call("job_status", {"id": job["id"]})
    assert all(
        r.get("final") in ("exited", "zombie", "reused") for r in job["results"]
    ), job
    assert any(r.get("kill") == "signaled" for r in job["results"]), job
    sibling = next(
        t for t in service.call("snapshot")["tasks"] if t["id"] == tasks[1]["id"]
    )
    assert sibling["status"] == "running"
    assert proc_identity(supervisor["pid"]) == supervisor["identity"]
    applied = service.call(
        "apply_task_policy",
        {
            "task_id": sibling["id"],
            "revision": sibling["revision"],
            "policy": {
                "expires_at": utcnow().isoformat(),
                "deadline_action": "terminate",
            },
        },
    )
    service.call("heartbeat", {"policy_versions": {sibling["id"]: applied["revision"]}})
    service.tick()
    for worker in list(service.workers.values()):
        worker.join(timeout=8)
    assert not any(p["uid"] == uid and p["gpu_memory"] for p in collect()[1])
    for identity in before:
        assert proc_identity(identity["pid"]) == identity
    print(
        json.dumps(
            {
                "checks": [
                    "real_CUDA_collection",
                    "helper_grouping",
                    "TERM_KILL",
                    "sibling_preserved",
                    "unknown_same_UID_supervisor_context_only",
                    "automatic_deadline_without_browser",
                    "existing_GPU_identity_preserved",
                ],
                "manual_job": job["status"],
                "untouched_GPU_PIDs": [i["pid"] for i in before],
            }
        )
    )
finally:
    for launcher in launchers:
        try:
            launcher.wait(timeout=5)
        except subprocess.TimeoutExpired:
            launcher.terminate()
