"""Incremental OpenSSH authentication log ingestion with explicit coverage."""

import hashlib
import json
import ipaddress
import os
import pwd
import re
from datetime import datetime, timezone
from pathlib import Path

from gpupm.agent.accounts import run
from gpupm.errors import DomainError

from gpupm.domain.rules import parse_time, utcnow

PATTERN = re.compile(
    r"sshd(?:\[\d+\])?: (Accepted|Failed) (password|publickey|keyboard-interactive/pam) for (invalid user )?(\S+) from (\S+) port \d+(?: ssh2)?(?:: (.*))?$"
)


def parse_auth_line(line, year=None):
    match = PATTERN.search(line)
    if not match:
        return None
    outcome, method, invalid_user, username, address, details = match.groups()
    try:
        address = str(ipaddress.ip_address(address))
    except ValueError:
        return None
    try:
        if re.match(r"^\d{4}-", line):
            timestamp = datetime.fromisoformat(line.split()[0].replace("Z", "+00:00"))
        else:
            timestamp = datetime.strptime(
                f"{year or utcnow().year} {line[:15]}", "%Y %b %d %H:%M:%S"
            ).replace(tzinfo=datetime.now().astimezone().tzinfo)
    except ValueError:
        return None
    if timestamp.astimezone(timezone.utc) > utcnow() + __import__("datetime").timedelta(
        days=1
    ) and not re.match(r"^\d{4}-", line):
        timestamp = timestamp.replace(year=timestamp.year - 1)
    fingerprint = re.search(r"SHA256:[A-Za-z0-9+/=]+", details or "")
    value = dict(
        username=username,
        time=timestamp.astimezone(timezone.utc).isoformat(),
        ip=address,
        method=method,
        result="success" if outcome == "Accepted" else "failure",
        fingerprint=fingerprint.group() if fingerprint else None,
        account_id=None,
    )
    value["time"] = parse_time(value["time"]).replace(microsecond=0).isoformat()
    if not invalid_user:
        try:
            value["account_id"] = str(pwd.getpwnam(username).pw_uid)
        except KeyError:
            pass
    value["id"] = event_key(value)
    return value


def event_key(event):
    fields = [
        event["username"],
        event["time"],
        event["ip"],
        event["method"],
        event["result"],
        event.get("fingerprint"),
    ]
    return hashlib.sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()


def parse_journal_record(record):
    if record.get("SYSLOG_IDENTIFIER") not in {"sshd", "sshd-session"}:
        return None
    try:
        timestamp = datetime.fromtimestamp(int(record["__REALTIME_TIMESTAMP"]) / 1000000, timezone.utc)
        event = parse_auth_line(timestamp.isoformat() + " host sshd: " + record["MESSAGE"])
    except (ValueError, KeyError, TypeError):
        return None
    return event


def login_events(state, params):
    positions = state.setdefault("auth_positions", {})
    known = {e["id"] for e in state["login_events"]}
    coverage = []
    catching_up = False
    for path in (Path("/var/log/auth.log.1"), Path("/var/log/auth.log")):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "r", errors="replace") as stream:
                info = os.fstat(stream.fileno())
                key = f"{info.st_dev}:{info.st_ino}"
                position = positions.get(key, 0)
                if position > info.st_size:
                    position = 0
                stream.seek(position)
                for _ in range(2000):
                    start = stream.tell()
                    line = stream.readline()
                    if not line:
                        break
                    if not line.endswith("\n"):
                        stream.seek(start)
                        break
                    event = parse_auth_line(line.rstrip("\n"))
                    if event and event["id"] not in known:
                        state["login_events"].append(event)
                        known.add(event["id"])
                positions[key] = stream.tell()
                catching_up = catching_up or positions[key] < info.st_size
                coverage.append(str(path))
        except OSError:
            continue
    try:
        argv = [
            "journalctl",
            "--no-pager",
            "--output=json",
            "--lines=+500",
            "SYSLOG_IDENTIFIER=sshd",
            "+",
            "SYSLOG_IDENTIFIER=sshd-session",
        ]
        if state.get("journal_cursor"):
            argv.extend(["--after-cursor", state["journal_cursor"]])
        else:
            argv.extend(["--since", "24 hours ago"])
        text = run(argv)
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            event = parse_journal_record(record)
            if event and event["id"] not in known:
                state["login_events"].append(event)
                known.add(event["id"])
            if record.get("__CURSOR"):
                state["journal_cursor"] = record["__CURSOR"]
        coverage.append("systemd journal (OpenSSH; initial last24h/500 entries)")
    except DomainError:
        pass
    filters = params.get("filters", params)
    values = state["login_events"]
    for field in ("username", "ip", "result"):
        if filters.get(field):
            values = [v for v in values if v[field] == filters[field]]
    for field, after in [("since", True), ("until", False)]:
        if filters.get(field):
            values = [
                v
                for v in values
                if (
                    parse_time(v["time"]) >= parse_time(filters[field])
                    if after
                    else parse_time(v["time"]) <= parse_time(filters[field])
                )
            ]
    values = sorted(values, key=lambda v: v["time"], reverse=True)
    total = len(values)
    page = max(1, int(filters.get("page", 1)))
    size = min(200, max(1, int(filters.get("page_size", 50))))
    return dict(
        items=values[(page - 1) * size : page * size],
        total=total,
        coverage=dict(
            sources=coverage,
            status="catching_up" if catching_up else ("available" if coverage else "unavailable"),
            limits="OpenSSH Accepted/Failed in auth.log and .1; compressed historical rotations and non-SSH login sources not covered; journal reads bounded to500 entries and auth files2000 lines each per collection; unprocessed backlog is ingested in later scans",
        ),
    )
