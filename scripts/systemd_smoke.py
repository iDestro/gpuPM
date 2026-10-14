"""Temporary localhost QA units; stop and remove units after verification."""

import json
import os
from pathlib import Path
import subprocess
import secrets

assert os.geteuid() == 0
base = Path("/var/lib/gpupm-qa")
assert base.is_dir() and base.stat().st_uid == 0
api = base / "api"
api.mkdir(exist_ok=True, mode=0o700)
os.chown(api, 1000, 1000)
config = base / ("service-" + secrets.token_hex(3) + ".json")
python = "/opt/gpupm-qa/venv/bin/python"
env = dict(os.environ, PYTHONPATH="/opt/gpupm-qa/backend/src")
subprocess.run(
    [
        python,
        "-m",
        "gpupm.cli",
        "init-config",
        "--path",
        str(config),
        "--api-uid",
        "1000",
        "--home-base",
        str(base / "home"),
        "--data-base",
        str(base / "data"),
        "--maintenance-user",
        "wuzhaoxiang",
    ],
    check=True,
    env=env,
)
values = json.loads(config.read_text())
values.update(
    store_path=str(base / "readonly.sqlite"), socket_path=str(base / "readonly.sock")
)
config.write_text(json.dumps(values))
assert config.stat().st_mode & 0o777 == 0o600
units = {
    "gpupm-qa-agent": f"""[Unit]
Description=gpuPM QA root agent
[Service]
User=root
Environment=PYTHONPATH=/opt/gpupm-qa/backend/src
ExecStart={python} -m gpupm.agent.main --config {config}
UMask=0077
NoNewPrivileges=yes
RestrictAddressFamilies=AF_UNIX
""",
    "gpupm-qa-api": f"""[Unit]
Description=gpuPM QA unprivileged API
After=gpupm-qa-agent.service
[Service]
User=wuzhaoxiang
Group=wuzhaoxiang
Environment=PYTHONPATH=/opt/gpupm-qa/backend/src
Environment=GPUPM_DATABASE={api}/app.sqlite
Environment=GPUPM_AGENT_SOCKET={base}/readonly.sock
Environment=GPUPM_FRONTEND_DIST=/opt/gpupm-qa/frontend/dist
Environment=GPUPM_HOME_BASE={base}/home
Environment=GPUPM_DATA_BASE={base}/data
ExecStart={python} -m gpupm.cli serve --host 127.0.0.1 --port 18000
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths={api}
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
""",
}
paths = []
try:
    for name, content in units.items():
        path = Path("/run/systemd/system") / (name + ".service")
        with path.open("x") as output:
            output.write(content)
        paths.append(path)
    subprocess.run(["systemd-analyze", "verify", *[str(p) for p in paths]], check=True)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "start", "gpupm-qa-agent", "gpupm-qa-api"], check=True)
    subprocess.run(
        [
            "runuser",
            "-u",
            "wuzhaoxiang",
            "--",
            "env",
            "PYTHONPATH=/opt/gpupm-qa/backend/src",
            python,
            "/opt/gpupm-qa/service_http_smoke.py",
        ],
        check=True,
    )
    subprocess.run(
        ["systemctl", "restart", "gpupm-qa-agent", "gpupm-qa-api"], check=True
    )
    subprocess.run(
        [
            "runuser",
            "-u",
            "wuzhaoxiang",
            "--",
            "env",
            "PYTHONPATH=/opt/gpupm-qa/backend/src",
            python,
            "/opt/gpupm-qa/service_http_smoke.py",
        ],
        check=True,
    )
    print("systemd initial startup and service restart passed")
finally:
    subprocess.run(["systemctl", "stop", "gpupm-qa-api", "gpupm-qa-agent"], check=False)
    for path in paths:
        path.unlink()
    subprocess.run(["systemctl", "daemon-reload"], check=False)
