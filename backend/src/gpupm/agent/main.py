"""Run as root on Linux with a root-controlled JSON configuration."""

import argparse
import fcntl
import json
import os
import signal
import pwd
import socket
import stat
import threading
from pathlib import Path

from gpupm.agent.accounts import secure_directory
from gpupm.agent.host import AgentService
from gpupm.agent.protocol import handle_connection
from gpupm.errors import DomainError


def load_config(path):
    path = Path(path)
    secure_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise DomainError("unsafe_config", "config must be a root-owned 0600 regular file", 403)
        with os.fdopen(fd, "r", closefd=False) as stream:
            config = json.load(stream)
    finally:
        os.close(fd)
    if not isinstance(config, dict) or type(config.get("api_uid")) is not int or config["api_uid"] <= 0:
        raise DomainError("invalid_config", "non-root API UID required", 422)
    if type(config.get("allow_mutations", False)) is not bool:
        raise DomainError("invalid_config", "allow_mutations must be explicit JSON boolean", 422)
    if not isinstance(config.get("maintenance_users", []), list) or not all(
        isinstance(v, str) for v in config.get("maintenance_users", [])
    ):
        raise DomainError("invalid_config", "maintenance_users must be a username list", 422)
    for key, default in [
        ("store_path", "/var/lib/gpupm/agent.sqlite"),
        ("socket_path", "/run/gpupm/agent.sock"),
    ]:
        value = Path(config.get(key, default))
        secure_directory(value.parent)
        if os.path.lexists(value):
            info = value.lstat()
            if (
                info.st_uid != 0
                or stat.S_ISLNK(info.st_mode)
                or (
                    key == "store_path"
                    and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077)
                )
            ):
                raise DomainError("unsafe_config", f"{key} root-owned path required", 403)
    for key, default in [("home_base", "/home"), ("data_base", "/data"), ("share_base", "/data/shared")]:
        secure_directory(config.get(key, default))
    return config


def serve(config):
    if os.geteuid() != 0 or not hasattr(socket, "SO_PEERCRED"):
        raise DomainError("platform_unsupported", "agent requires Linux root", 503)
    path = Path(config.get("socket_path", "/run/gpupm/agent.sock"))
    lockfd = os.open(str(path) + ".lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    lockinfo = os.fstat(lockfd)
    if (
        not stat.S_ISREG(lockinfo.st_mode)
        or lockinfo.st_uid != 0
        or lockinfo.st_nlink != 1
        or lockinfo.st_mode & 0o077
    ):
        os.close(lockfd)
        raise DomainError("unsafe_socket", "lock file must be a root-owned private regular file", 403)
    try:
        fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Startup recovery writes state, so it must also hold the singleton lock.
        service = AgentService(config)
    except BaseException:
        os.close(lockfd)
        raise
    if os.path.lexists(path):
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0:
            raise DomainError("unsafe_socket", "socket path conflict", 403)
        path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    os.chown(path, 0, pwd.getpwuid(config["api_uid"]).pw_gid)
    os.chmod(path, 0o660)
    server.listen(32)
    server.settimeout(1)

    def shutdown(*_):
        service.stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    def poll():
        while not service.stop.is_set():
            try:
                service.tick()
            except Exception as exc:
                with service.lock, service.database() as db:
                    state = service.load(db)
                    service.event(state, {}, "agent.collection", "host", None, None, type(exc).__name__)
                    service.save(db, state)
            service.wait_interval("scan_interval_seconds", 5)

    threading.Thread(target=poll, daemon=True).start()

    def storage_poll():
        while not service.stop.is_set():
            try:
                service.collect_storage()
            except Exception as exc:
                with service.lock, service.database() as db:
                    state = service.load(db)
                    service.event(state, {}, "storage.collection", "host", None, None, type(exc).__name__)
                    service.save(db, state)
            service.wait_interval("storage_scan_interval_seconds", 900)

    threading.Thread(target=storage_poll, daemon=True).start()

    def login_poll():
        while not service.stop.is_set():
            try:
                service.call("login_events_since", {"filters": {"page_size": 1}})
            except DomainError:
                pass
            service.stop.wait(30)

    threading.Thread(target=login_poll, daemon=True).start()
    try:
        while not service.stop.is_set():
            try:
                client, _ = server.accept()
            except TimeoutError:
                continue
            # One request per connection; length/peer/timeout bound resource use.
            with client:
                try:
                    handle_connection(client, service, config["api_uid"])
                except (DomainError, OSError):
                    pass
    finally:
        service.stop.set()
        server.close()
        path.unlink(missing_ok=True)
        os.close(lockfd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    serve(load_config(args.config))


if __name__ == "__main__":
    main()
