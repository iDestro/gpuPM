"""Linux account administration. Never removes accounts or their files."""

import base64
import copy
from uuid import uuid4
import ctypes
import ctypes.util
import grp
import os
import pwd
import re
import stat
from datetime import datetime, timezone
import subprocess
from pathlib import Path

import psutil

from gpupm.domain.rules import account_status, utcnow, validate_name
from gpupm.errors import DomainError

SENSITIVE_GROUPS = {
    "root",
    "sudo",
    "wheel",
    "docker",
    "adm",
    "gpupm",
    "shadow",
    "disk",
    "lxd",
    "libvirt",
    "kvm",
    "systemd-journal",
}


def run(argv, input=None):
    try:
        result = subprocess.run(
            argv,
            input=input,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DomainError("host_tool_unavailable", f"{argv[0]} unavailable: {exc}", 503) from exc
    if result.returncode:
        # Never echo command input (passwords) or tool output that may contain it.
        raise DomainError("host_command_failed", f"{argv[0]} failed (exit {result.returncode})", 503)
    return result.stdout


def secure_directory(path, owner=0):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise DomainError("unsafe_path", "absolute controlled path required", 422)
    for ancestor in [path, *path.parents]:
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
            raise DomainError("unsafe_path", f"root-owned non-writable directory required: {ancestor}", 403)
    return path


def open_directory(path):
    """Resolve every component with nofollow: no symlink swaps between validation/use."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise DomainError("unsafe_path", "absolute controlled path required", 422)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except OSError as exc:
        os.close(fd)
        raise DomainError("unsafe_path", "directory path is missing or contains symlink", 422) from exc


def validate_groups(groups):
    if not isinstance(groups, list):
        raise DomainError("invalid_groups", "groups must be a list", 422)
    for name in groups:
        if name in SENSITIVE_GROUPS:
            raise DomainError("protected_group", "sensitive group grant forbidden", 403)
        try:
            validate_name(name)
        except (ValueError, TypeError) as exc:
            raise DomainError("invalid_group", str(exc), 422) from exc
        try:
            group = grp.getgrnam(name)
        except KeyError as exc:
            raise DomainError("group_missing", "system group does not exist", 422) from exc
        if group.gr_gid < 1000:
            raise DomainError("protected_group", "system group grant forbidden", 403)


def validate_keys(keys):
    if not isinstance(keys, list) or len(keys) > 50:
        raise DomainError("invalid_keys", "invalid public keys", 422)
    for key in keys:
        if not isinstance(key, str) or "\n" in key or "\r" in key or len(key) > 16384:
            raise DomainError("invalid_keys", "one public key per line required", 422)
        parts = key.split()
        if len(parts) < 2 or parts[0] not in {
            "ssh-ed25519",
            "ssh-rsa",
            "ecdsa-sha2-nistp256",
            "ecdsa-sha2-nistp384",
            "ecdsa-sha2-nistp521",
        }:
            raise DomainError("invalid_keys", "plain supported public key required; options forbidden", 422)
        try:
            blob = base64.b64decode(parts[1], validate=True)
            fields = []
            offset = 0
            while offset < len(blob):
                if offset + 4 > len(blob):
                    raise ValueError()
                size = int.from_bytes(blob[offset : offset + 4], "big")
                offset += 4
                if offset + size > len(blob):
                    raise ValueError()
                fields.append(blob[offset : offset + size])
                offset += size
            if not fields or fields[0].decode() != parts[0]:
                raise ValueError()
            if parts[0] == "ssh-ed25519":
                if len(fields) != 2 or len(fields[1]) != 32:
                    raise ValueError()
            elif parts[0] == "ssh-rsa":
                if (
                    len(fields) != 3
                    or int.from_bytes(fields[1], "big") < 3
                    or int.from_bytes(fields[1], "big") % 2 != 1
                    or int.from_bytes(fields[2], "big").bit_length() < 2048
                ):
                    raise ValueError()
            else:
                curve = parts[0].removeprefix("ecdsa-sha2-")
                lengths = {"nistp256": 65, "nistp384": 97, "nistp521": 133}
                if (
                    len(fields) != 3
                    or fields[1].decode() != curve
                    or len(fields[2]) != lengths[curve]
                    or fields[2][0] != 4
                ):
                    raise ValueError()
        except (ValueError, UnicodeError) as exc:
            raise DomainError("invalid_keys", "malformed SSH key", 422) from exc


def quality_password(password, username):
    if (
        not isinstance(password, str)
        or len(password) < 12
        or "\n" in password
        or "\r" in password
        or "\x00" in password
    ):
        raise DomainError(
            "weak_password", "password requires at least 12 characters and no control delimiters", 422
        )
    library = ctypes.util.find_library("pwquality")
    if not library:
        raise DomainError(
            "password_quality_unavailable", "install libpwquality; password operation refused", 503
        )
    lib = ctypes.CDLL(library)
    lib.pwquality_default_settings.restype = ctypes.c_void_p
    lib.pwquality_check.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.pwquality_free_settings.argtypes = [ctypes.c_void_p]
    settings = lib.pwquality_default_settings()
    try:
        lib.pwquality_read_config.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        aux = ctypes.c_void_p()
        if lib.pwquality_read_config(settings, None, ctypes.byref(aux)) < 0:
            raise DomainError(
                "password_quality_unavailable", "host password quality configuration cannot be read", 503
            )
        result = lib.pwquality_check(settings, password.encode(), None, username.encode(), ctypes.byref(aux))
        if result < 0:
            raise DomainError("weak_password", "password fails host password quality policy", 422)
    finally:
        lib.pwquality_free_settings(settings)


def restriction_active(account, baseline=False):
    return bool(
        baseline
        or account.get("disabled")
        or account.get("deleted_at")
        or (account.get("expires_on") and account["expires_on"] <= utcnow().date().isoformat())
    )


def user_service_configuration(account, global_paths=None):
    scheduled = []
    own = Path(account["home"]) / ".config/systemd/user"
    if own.exists():
        fd = open_directory(own)
        try:
            for name in os.listdir(fd):
                if not name.endswith((".wants", ".requires")):
                    continue
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    if os.listdir(child):
                        scheduled.append(dict(kind="user_service_config", line=str(own / name)))
                finally:
                    os.close(child)
        finally:
            os.close(fd)
    # Generic %u/%h/%t global units follow the renamed login and must not block every account.
    for path in global_paths or [Path("/etc/systemd/user"), Path("/usr/lib/systemd/user")]:
        if not path.exists():
            continue
        fd = open_directory(path)
        try:
            for name in os.listdir(fd):
                if not name.endswith((".service", ".timer", ".socket", ".path")):
                    continue
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    continue
                unit = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                with os.fdopen(unit, errors="replace") as stream:
                    content = stream.read(1024 * 1024)
                for line in content.splitlines():
                    if not line.strip() or line.lstrip().startswith(("#", ";")):
                        continue
                    references = [account["home"], account.get("data_dir")]
                    explicit_user = line.strip() in {
                        "User=" + account["username"],
                        "User=" + str(account["uid"]),
                    }
                    if explicit_user or any(
                        value and re.search(re.escape(value) + r"(?=$|[/\s\"';])", line)
                        for value in references
                    ):
                        scheduled.append(dict(kind="global_user_service_reference", line=str(path / name)))
                        break
        finally:
            os.close(fd)
    return scheduled


class Accounts:
    def __init__(self, config, executor=run, event=None):
        self.config = config
        self.run = executor
        self.event = event

    def protected(self, entry):
        return (
            entry.pw_uid < 1000
            or entry.pw_uid == self.config.get("api_uid")
            or entry.pw_name in self.config.get("maintenance_users", [])
            or entry.pw_name in {"gpupm", "nobody"}
        )

    def local_entries(self):
        # pwd may use NSS/LDAP; only local passwd entries are eligible for writes.
        names = {line.split(":")[0] for line in Path("/etc/passwd").read_text().splitlines() if ":" in line}
        return [entry for entry in pwd.getpwall() if entry.pw_name in names]

    def observe_identities(self, state, entries):
        observations = state.setdefault("account_observations", {})
        present = {str(entry.pw_uid): entry for entry in entries}
        for uid, meta in list(state["accounts"].items()):
            if uid not in observations and uid not in present and meta.get("managed"):
                name = meta.get("identity_username") or Path(meta.get("data_dir") or "").name
                observations[uid] = dict(
                    lifecycle_id=str(uuid4()),
                    username=name,
                    home=meta.get("identity_home") or str(Path(self.config.get("home_base", "/home")) / name),
                    absent=False,
                )

        def invalidate(uid, observed, reason):
            old = copy.deepcopy(state["accounts"].get(uid, {}))
            if old:
                state.setdefault("account_history", []).append(
                    dict(
                        uid=uid,
                        lifecycle_id=observed.get("lifecycle_id"),
                        metadata=old,
                        invalidated_at=utcnow().isoformat(),
                        reason=reason,
                    )
                )
            state["accounts"][uid] = dict(
                managed=False,
                identity_conflict=True,
                revision=old.get("revision", 1) + 1,
                login_policy_status="identity_conflict",
            )
            after = dict(reason=reason, uid=uid)
            if self.event:
                self.event(state, {}, "account.identity_conflict", uid, observed, after, "identity_conflict")
            else:
                state.setdefault("events", []).append(
                    dict(
                        id=str(uuid4()),
                        time=utcnow().isoformat(),
                        actor="system",
                        action="account.identity_conflict",
                        target=uid,
                        before=copy.deepcopy(observed),
                        after=after,
                        result="identity_conflict",
                        reason=reason,
                    )
                )

        for uid, observed in observations.items():
            if uid not in present and not observed.get("absent"):
                invalidate(uid, observed, "native account absence observed")
                observed["absent"] = True
        for uid, entry in present.items():
            observed = observations.get(uid)
            if not observed:
                meta = state["accounts"].get(uid, {})
                if meta.get("managed"):
                    expected_name = meta.get("identity_username") or Path(meta.get("data_dir") or "").name
                    expected_home = meta.get("identity_home") or str(
                        Path(self.config.get("home_base", "/home")) / expected_name
                    )
                    if expected_name != entry.pw_name or expected_home != entry.pw_dir:
                        invalidate(
                            uid,
                            dict(username=expected_name, home=expected_home),
                            "legacy managed identity does not match native account",
                        )
                observed = dict(
                    lifecycle_id=str(uuid4()), username=entry.pw_name, home=entry.pw_dir, absent=False
                )
                observations[uid] = observed
            elif (
                observed.get("absent")
                or observed["username"] != entry.pw_name
                or observed["home"] != entry.pw_dir
            ):
                if not observed.get("absent"):
                    invalidate(uid, observed, "native username/home drift observed")
                observations[uid] = dict(
                    lifecycle_id=str(uuid4()), username=entry.pw_name, home=entry.pw_dir, absent=False
                )
            meta = state["accounts"].get(uid, {})
            if meta.get("managed"):
                meta.update(identity_username=entry.pw_name, identity_home=entry.pw_dir)

    def list(self, state):
        result = []
        entries = self.local_entries()
        self.observe_identities(state, entries)
        for entry in entries:
            meta = state["accounts"].get(str(entry.pw_uid), {})
            groups = sorted(
                {g.gr_name for g in grp.getgrall() if entry.pw_name in g.gr_mem or g.gr_gid == entry.pw_gid}
            )
            try:
                primary_group = grp.getgrgid(entry.pw_gid).gr_name
            except KeyError:
                primary_group = None
            candidates = []
            if meta.get("expires_on"):
                candidates.append(datetime.fromisoformat(meta["expires_on"]).replace(tzinfo=timezone.utc))
            if meta.get("agent_restricted"):
                native_expiry = meta.get("baseline", {}).get("expire", "")
            else:
                try:
                    native_expiry = self.shadow_baseline(entry.pw_name)["expire"]
                except DomainError:
                    native_expiry = ""
            if isinstance(native_expiry, str) and native_expiry.isdigit():
                candidates.append(datetime.fromtimestamp(int(native_expiry) * 86400, timezone.utc))
            expiry = min(candidates) if candidates else None
            effective = expiry.isoformat() if expiry else None
            expired = bool(expiry and expiry <= utcnow())
            successes = [
                event
                for event in state.get("login_events", [])
                if event["username"] == entry.pw_name and event["result"] == "success"
            ]
            last_success = max(successes, key=lambda event: event["time"]) if successes else None
            result.append(
                dict(
                    id=str(entry.pw_uid),
                    lifecycle_id=state["account_observations"][str(entry.pw_uid)]["lifecycle_id"],
                    identity_conflict=bool(meta.get("identity_conflict")),
                    recovery_required=bool(meta.get("rename_recovery_required")),
                    uid=entry.pw_uid,
                    gid=entry.pw_gid,
                    primary_group=primary_group,
                    last_success_login={key: last_success.get(key) for key in ("time", "ip", "method")}
                    if last_success
                    else None,
                    login_coverage="Only ingested OpenSSH records; inspect login history for sources and coverage",
                    username=entry.pw_name,
                    groups=groups,
                    shell=entry.pw_shell,
                    home=entry.pw_dir,
                    data_dir=meta.get("data_dir"),
                    managed=bool(meta.get("managed")),
                    protected=self.protected(entry),
                    disabled=bool(meta.get("disabled")),
                    deleted_at=meta.get("deleted_at"),
                    expires_on=meta.get("expires_on"),
                    expires_effective_at=effective,
                    require_password_change=meta.get("require_password_change", False),
                    notes=meta.get("notes", ""),
                    revision=meta.get("revision", 1),
                    public_keys=meta.get("public_keys", []),
                    status=account_status(
                        deleted=meta.get("deleted_at"), disabled=meta.get("disabled"), expired=expired
                    ),
                    login_policy_status=meta.get("login_policy_status", "unmanaged"),
                )
            )
        return result

    def groups(self, state):
        local = {line.split(":")[0] for line in Path("/etc/group").read_text().splitlines() if ":" in line}
        return [
            dict(
                id=g.gr_name,
                name=g.gr_name,
                gid=g.gr_gid,
                members=sorted(g.gr_mem),
                protected=g.gr_gid < 1000 or g.gr_name in SENSITIVE_GROUPS,
                managed=g.gr_name in state["groups"],
                revision=state["groups"].get(g.gr_name, {}).get("revision", 1),
            )
            for g in grp.getgrall()
            if g.gr_name in local
        ]

    def find(self, state, ident):
        for account in self.list(state):
            if account["id"] == str(ident):
                return account
        raise DomainError("not_found", "local account not found", 404)

    def writable(self, state, ident, adopt=False):
        account = self.find(state, ident)
        try:
            validate_name(account["username"])
        except ValueError as exc:
            raise DomainError(
                "protected_account", "only normal validated local account names are editable", 403
            ) from exc
        if state["accounts"].get(str(ident), {}).get("rename_recovery_required"):
            raise DomainError(
                "rename_recovery_required",
                "rename was interrupted; root reconciliation required before any further mutation",
                403,
            )
        if state["accounts"].get(str(ident), {}).get("identity_conflict"):
            raise DomainError(
                "identity_conflict",
                "native account lifecycle changed; root reconciliation required before management",
                403,
            )
        if account["protected"]:
            raise DomainError("protected_account", "account is protected", 403)
        if not account["managed"] and not adopt:
            raise DomainError("unmanaged_account", "explicit guarded adoption required", 403)
        return account

    def activity(self, state, ident):
        account = self.find(state, ident)
        uid = account["uid"]
        processes = []
        for process in psutil.process_iter(["pid", "uids", "cmdline"]):
            try:
                if process.info["uids"].real == uid:
                    processes.append(dict(pid=process.pid, command=" ".join(process.info["cmdline"] or [])))
            except psutil.Error:
                continue
        sessions = [
            dict(name=s.name, terminal=s.terminal, host=s.host, started=s.started, pid=s.pid)
            for s in psutil.users()
            if s.name == account["username"]
        ]
        scheduled = []
        coverage = {}
        try:
            spool = Path("/var/spool/cron/crontabs")
            if not spool.exists():
                raise OSError("cron spool unavailable")
            fd = open_directory(spool)
            try:
                try:
                    cron = os.open(account["username"], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    text = ""
                else:
                    with os.fdopen(cron) as stream:
                        text = stream.read(1024 * 1024)
            finally:
                os.close(fd)
            scheduled.extend(
                dict(kind="crontab", line=line)
                for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            )
            coverage["crontab"] = "available"
        except (OSError, DomainError):
            coverage["crontab"] = "unavailable"
        try:
            paths = [Path("/etc/crontab"), *Path("/etc/cron.d").iterdir()]
            for path in paths:
                if not path.is_file() or path.is_symlink():
                    continue
                with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as stream:
                    for line in stream:
                        fields = line.split()
                        if line.lstrip().startswith("#") or not fields:
                            continue
                        user_index = 1 if fields[0].startswith("@") else 5
                        if len(fields) > user_index and fields[user_index] == account["username"]:
                            scheduled.append(dict(kind="system_cron", line=line.strip()))
            coverage["system_cron"] = "available"
        except OSError:
            coverage["system_cron"] = "unavailable"
        try:
            services = self.run(["systemctl", "list-units", "--all", "--no-legend", f"user@{uid}.service"])
            coverage["user_services"] = "available"
            scheduled.extend(
                dict(kind="user_service", line=line)
                for line in services.splitlines()
                if " active " in " " + line + " "
            )
            scheduled.extend(user_service_configuration(account))
        except (OSError, DomainError):
            coverage["user_services"] = "unavailable"
        coverage.update(processes="procfs via psutil", sessions="utmp; session visibility may be incomplete")
        return dict(processes=processes, sessions=sessions, scheduled=scheduled, coverage=coverage)

    def assert_idle(self, state, account):
        activity = self.activity(state, account["id"])
        if activity["processes"] or activity["sessions"]:
            raise DomainError("account_active", "offline change requires no processes or sessions")
        if any(v.startswith("unavailable") for v in activity["coverage"].values()):
            raise DomainError(
                "activity_unknown", "offline change requires complete scheduled activity coverage", 503
            )
        if activity["scheduled"]:
            raise DomainError("account_scheduled", "offline rename requires scheduled jobs/services removed")

    def write_files(self, account, keys=None, initialize=False):
        home = Path(account["home"])
        fd = open_directory(home)
        try:
            info = os.fstat(fd)
            if info.st_uid != account["uid"]:
                raise DomainError("unsafe_home", "home is not owned by account", 403)
            if initialize:
                for name, text in {
                    ".profile": 'umask 077\nexport DATA_DIR="$HOME/data"\n',
                    ".bashrc": 'umask 077\nexport DATA_DIR="$HOME/data"\n',
                }.items():
                    out = os.open(
                        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
                    )
                    try:
                        os.write(out, text.encode())
                        os.fchown(out, account["uid"], account["gid"])
                    finally:
                        os.close(out)
                os.symlink(account["data_dir"], "data", dir_fd=fd)
            if keys is not None:
                validate_keys(keys)
                try:
                    os.mkdir(".ssh", 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                ssh = os.open(".ssh", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    if os.fstat(ssh).st_uid not in {0, account["uid"]}:
                        raise DomainError("unsafe_home", "SSH directory owner conflict", 403)
                    os.fchmod(ssh, 0o700)
                    os.fchown(ssh, account["uid"], account["gid"])
                    # New inode replaces an untrusted account-owned key file without following links.
                    name = ".gpupm-keys-" + os.urandom(8).hex()
                    out = os.open(
                        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=ssh
                    )
                    try:
                        os.write(out, ("\n".join(keys) + "\n").encode())
                        os.fchown(out, account["uid"], account["gid"])
                        os.fsync(out)
                    finally:
                        os.close(out)
                    os.rename(name, "authorized_keys", src_dir_fd=ssh, dst_dir_fd=ssh)
                finally:
                    os.close(ssh)
        except OSError as exc:
            raise DomainError("unsafe_home", "home file conflict or symlink", 403) from exc
        finally:
            os.close(fd)

    def shadow_baseline(self, name):
        try:
            line = next(
                line for line in Path("/etc/shadow").read_text().splitlines() if line.startswith(name + ":")
            )
        except (OSError, StopIteration) as exc:
            raise DomainError("shadow_unavailable", "root shadow access required", 503) from exc
        parts = line.split(":")
        return dict(
            password=parts[1],
            last_change=parts[2],
            expire=parts[7],
            shell=pwd.getpwnam(name).pw_shell,
            restricted=parts[1].startswith(("!", "*"))
            or bool(parts[7])
            or pwd.getpwnam(name).pw_shell.endswith(("nologin", "false")),
        )

    def capture_external_policy(self, account, meta):
        current = self.shadow_baseline(account["username"])
        baseline = meta["baseline"]
        if meta.get("agent_restricted"):
            expected = (
                baseline["password"] if baseline["password"].startswith("!") else "!" + baseline["password"]
            )
            if (
                current["password"] != expected
                or current["shell"] != "/usr/sbin/nologin"
                or current["expire"] != "1"
            ):
                raise DomainError(
                    "external_policy_changed",
                    "external restrictions changed while agent restriction active; refusing to overwrite",
                )
            return
        baseline["password"] = current["password"]
        baseline["shell"] = current["shell"]
        if current["expire"] != meta.get("agent_expire_value", baseline["expire"]):
            baseline["expire"] = current["expire"]
        if not (meta.get("agent_password_change") and current.get("last_change") == "0"):
            baseline["last_change"] = current.get("last_change", baseline.get("last_change", ""))
        baseline["restricted"] = (
            baseline["password"].startswith("!")
            or bool(baseline["expire"])
            or baseline["shell"].endswith(("nologin", "false"))
        )
        meta["baseline_restricted"] = baseline["restricted"]

    def apply_login(self, account, meta):
        if not meta.get("agent_restricted") and restriction_active(meta):
            self.capture_external_policy(account, meta)
        baseline = meta["baseline"]
        restricted = restriction_active(meta)
        current = self.shadow_baseline(account["username"])
        if restricted:
            if meta.get("agent_restricted"):
                expected_hash = (
                    baseline["password"]
                    if baseline["password"].startswith("!")
                    else "!" + baseline["password"]
                )
                if (
                    current["shell"] != "/usr/sbin/nologin"
                    or current["expire"] != "1"
                    or current["password"] != expected_hash
                ):
                    raise DomainError(
                        "external_policy_changed", "external login policy changed; refusing to overwrite"
                    )
            # Expiry also blocks SSH key/PAM logins. Existing sessions are deliberately retained.
            self.run(
                [
                    "usermod",
                    "--lock",
                    "--expiredate",
                    "1",
                    "--shell",
                    "/usr/sbin/nologin",
                    account["username"],
                ]
            )
        else:
            if meta.get("agent_restricted"):
                if (
                    current["shell"] != "/usr/sbin/nologin"
                    or current["expire"] != "1"
                    or current["password"]
                    != (
                        baseline["password"]
                        if baseline["password"].startswith("!")
                        else "!" + baseline["password"]
                    )
                ):
                    raise DomainError(
                        "external_policy_changed", "external login restrictions changed; refusing to clear"
                    )
                self.run(
                    [
                        "usermod",
                        "--shell",
                        baseline["shell"],
                        "--expiredate",
                        baseline["expire"] or "-1",
                        account["username"],
                    ]
                )
                if not baseline["password"].startswith("!"):
                    self.run(["usermod", "--unlock", account["username"]])
        if not restricted:
            candidates = [
                value
                for value in (
                    baseline["expire"],
                    str(
                        (
                            datetime.fromisoformat(meta["expires_on"]).replace(tzinfo=timezone.utc)
                            - datetime(1970, 1, 1, tzinfo=timezone.utc)
                        ).days
                    )
                    if meta.get("expires_on")
                    else "",
                )
                if value and value.isdigit()
            ]
            target = min(candidates, key=int) if candidates else ""
            latest = self.shadow_baseline(account["username"])
            expected = meta.get("agent_expire_value", baseline["expire"])
            if latest["expire"] not in {expected, baseline["expire"]}:
                raise DomainError(
                    "external_policy_changed", "external account expiry changed; refusing to clear"
                )
            if latest["expire"] != target:
                self.run(["usermod", "--expiredate", target or "-1", account["username"]])
            meta["agent_expire_value"] = target
        meta["login_policy_status"] = "applied"
        meta["agent_restricted"] = restricted
        meta["baseline_restricted"] = baseline["restricted"]

    def assert_devices(self, home_base, data_base):
        for key, path in [("home_dev_id", home_base), ("data_dev_id", data_base)]:
            expected = self.config.get(key)
            if expected is None:
                continue
            if type(expected) is not int or expected <= 0:
                raise DomainError("invalid_device", "expected device ID must be a positive integer", 422)
            fd = open_directory(path)
            try:
                if os.fstat(fd).st_dev != expected:
                    raise DomainError(
                        "device_mismatch",
                        f"{path} no longer matches configured {key}; refusing provisioning",
                        503,
                    )
            finally:
                os.close(fd)
        for key, path in [("home_device", home_base), ("data_device", data_base)]:
            expected = self.config.get(key)
            if expected is None:
                continue
            if not isinstance(expected, str) or not expected.startswith("/dev/"):
                raise DomainError("invalid_device", "expected device must be an absolute /dev/ path", 422)
            try:
                device = os.stat(expected)
                fd = open_directory(path)
                try:
                    actual = os.fstat(fd).st_dev
                finally:
                    os.close(fd)
            except OSError as exc:
                raise DomainError("device_unavailable", f"configured {key} is unavailable", 503) from exc
            if not stat.S_ISBLK(device.st_mode) or device.st_rdev != actual:
                raise DomainError(
                    "device_mismatch", f"{path} is not on configured {key}; refusing provisioning", 503
                )

    def rename(self, state, account, meta, new_name):
        try:
            validate_name(new_name)
        except ValueError as exc:
            raise DomainError("invalid_username", str(exc), 422) from exc
        try:
            pwd.getpwnam(new_name)
        except KeyError:
            pass
        else:
            raise DomainError("account_exists", "rename target exists")
        self.assert_idle(state, account)
        old_name = account["username"]
        home_base = secure_directory(self.config.get("home_base", "/home"))
        data_base = secure_directory(self.config.get("data_base", "/data"))
        self.assert_devices(home_base, data_base)
        if account["home"] != str(home_base / old_name) or meta["data_dir"] != str(data_base / old_name):
            raise DomainError("rename_path_conflict", "rename only controlled managed home/data paths")
        home_fd = open_directory(home_base)
        data_fd = open_directory(data_base)
        home = None
        try:
            for parent in (home_fd, data_fd):
                try:
                    os.stat(new_name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise DomainError("path_conflict", "rename target path exists")
                info = os.stat(old_name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != account["uid"]:
                    raise DomainError("unsafe_path", "managed directory identity/owner changed")
            home = os.open(old_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=home_fd)
            if os.readlink("data", dir_fd=home) != meta["data_dir"]:
                raise DomainError("rename_path_conflict", "managed data link changed")
            # Block new PAM logins before the final activity recheck and keep failures restricted.
            meta["rename_recovery_required"] = True
            self.run(["usermod", "--lock", "--expiredate", "1", "--shell", "/usr/sbin/nologin", old_name])
            meta["agent_restricted"] = True
            self.assert_idle(state, account)
            rename_noreplace(home_fd, old_name, home_fd, new_name)
            try:
                rename_noreplace(data_fd, old_name, data_fd, new_name)
            except DomainError:
                rename_noreplace(home_fd, new_name, home_fd, old_name)
                raise
            try:
                self.run(["usermod", "--login", new_name, "--home", str(home_base / new_name), old_name])
            except DomainError:
                rename_noreplace(data_fd, new_name, data_fd, old_name)
                rename_noreplace(home_fd, new_name, home_fd, old_name)
                raise
            meta["data_dir"] = str(data_base / new_name)
            account.update(username=new_name, home=str(home_base / new_name), data_dir=meta["data_dir"])
            meta.update(identity_username=new_name, identity_home=account["home"])
            observation = state.get("account_observations", {}).get(account["id"])
            if observation:
                observation.update(username=new_name, home=account["home"])
            temp = ".gpupm-data-" + os.urandom(8).hex()
            os.symlink(meta["data_dir"], temp, dir_fd=home)
            os.rename(temp, "data", src_dir_fd=home, dst_dir_fd=home)
            meta["rename_recovery_required"] = False
        finally:
            if home is not None:
                os.close(home)
            os.close(home_fd)
            os.close(data_fd)

    def execute(self, state, action, ident, changes):
        unknown = set(changes) - {
            "username",
            "password",
            "public_keys",
            "notes",
            "groups",
            "primary_group",
            "shell",
            "expires_on",
            "require_password_change",
            "managed",
        }
        if unknown:
            raise DomainError(
                "invalid_fields", "unsupported account fields: " + ",".join(sorted(unknown)), 422
            )
        if "shell" in changes and changes["shell"] not in {"/bin/bash", "/bin/sh", "/usr/sbin/nologin"}:
            raise DomainError("invalid_shell", "shell must be an allowed login shell", 422)
        if "managed" in changes and changes["managed"] is not True:
            raise DomainError("invalid_adoption", "managed account cannot be released", 422)
        if "primary_group" in changes:
            if action == "create":
                raise DomainError(
                    "private_primary_group",
                    "new accounts always receive a same-name private primary group",
                    422,
                )
            validate_groups([changes["primary_group"]])
        if "groups" in changes:
            validate_groups(changes["groups"])
        if "public_keys" in changes:
            validate_keys(changes["public_keys"])
        if "expires_on" in changes and changes["expires_on"] is not None:
            from datetime import date

            try:
                date.fromisoformat(changes["expires_on"])
            except (ValueError, TypeError) as exc:
                raise DomainError("invalid_expiry", "ISO expiry date required", 422) from exc
        if action == "create":
            try:
                name = validate_name(changes["username"])
            except (KeyError, ValueError) as exc:
                raise DomainError("invalid_username", str(exc), 422) from exc
            try:
                pwd.getpwnam(name)
            except KeyError:
                pass
            else:
                raise DomainError("account_exists", "account already exists, including soft-deleted account")
            if not changes.get("password") and not changes.get("public_keys"):
                raise DomainError("credentials_required", "password or SSH public key required", 422)
            if changes.get("password"):
                quality_password(changes["password"], name)
            home_base = secure_directory(self.config.get("home_base", "/home"))
            data_base = secure_directory(self.config.get("data_base", "/data"))
            self.assert_devices(home_base, data_base)
            home = home_base / name
            data = data_base / name
            if os.path.lexists(home) or os.path.lexists(data):
                raise DomainError("path_conflict", "home or data path already exists")
            argv = [
                "useradd",
                "--user-group",
                "--no-create-home",
                "--shell",
                "/usr/sbin/nologin",
                "--expiredate",
                "1",
                "--home-dir",
                str(home),
                name,
            ]
            self.observe_identities(state, self.local_entries())
            self.run(argv)
            entry = pwd.getpwnam(name)
            if (
                str(entry.pw_uid) in state.get("account_observations", {})
                or str(entry.pw_uid) in state["accounts"]
            ):
                self.observe_identities(state, self.local_entries())
                raise DomainError(
                    "uid_lifecycle_conflict",
                    "native allocator reused a previously observed UID; new account remains locked for root reconciliation",
                    403,
                )
            account = dict(
                id=str(entry.pw_uid),
                uid=entry.pw_uid,
                gid=entry.pw_gid,
                username=name,
                home=str(home),
                data_dir=str(data),
            )
            # Account remains locked on partial provisioning; never deletes data/account to roll back.
            for base in (home_base, data_base):
                fd = open_directory(base)
                try:
                    expected_id = self.config.get("home_dev_id" if base == home_base else "data_dev_id")
                    if expected_id is not None and os.fstat(fd).st_dev != expected_id:
                        raise DomainError(
                            "device_mismatch",
                            "controlled parent device changed; account remains restricted",
                            503,
                        )
                    expected = self.config.get("home_device" if base == home_base else "data_device")
                    if expected and os.fstat(fd).st_dev != os.stat(expected).st_rdev:
                        raise DomainError(
                            "device_mismatch",
                            "controlled parent device changed; account remains restricted",
                            503,
                        )
                    os.mkdir(name, 0o700, dir_fd=fd)
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        os.fchown(child, entry.pw_uid, entry.pw_gid)
                        os.fchmod(child, 0o700)
                    finally:
                        os.close(child)
                finally:
                    os.close(fd)
            meta = dict(
                managed=True,
                identity_username=name,
                identity_home=str(home),
                data_dir=str(data),
                revision=1,
                disabled=False,
                deleted_at=None,
                baseline=self.shadow_baseline(name),
                login_policy_status="pending",
            )
            state["accounts"][account["id"]] = meta
            state["groups"][name] = {"revision": 1}
            self.write_files(account, changes.get("public_keys", []), initialize=True)
            if changes.get("password"):
                self.run(["chpasswd"], input=f"{name}:{changes['password']}\n")
            else:
                self.run(["usermod", "--password", "*", name])
            meta["baseline"] = self.shadow_baseline(name)
            meta["baseline"].update(shell="/bin/bash", expire="", restricted=False)
            meta["agent_restricted"] = True
            self.run(["usermod", "--lock", name])
        else:
            account = self.writable(state, ident, adopt=changes.get("managed") is True)
            meta = state["accounts"].setdefault(
                account["id"], dict(revision=account["revision"], disabled=False, deleted_at=None)
            )
            if not meta.get("managed"):
                # Adoption never imports arbitrary user-chosen paths into managed filesystem operations.
                expected_home = str(Path(self.config.get("home_base", "/home")) / account["username"])
                expected_data = str(Path(self.config.get("data_base", "/data")) / account["username"])
                if account["home"] != expected_home:
                    raise DomainError(
                        "adoption_path_conflict", "account home is outside controlled managed path"
                    )
                for path in (expected_home, expected_data):
                    path_fd = open_directory(path)
                    try:
                        info = os.fstat(path_fd)
                        if info.st_uid != account["uid"] or info.st_mode & 0o077:
                            raise DomainError(
                                "adoption_path_conflict",
                                "adoption requires account-owned private home/data directories",
                            )
                    finally:
                        os.close(path_fd)
                meta.update(
                    managed=True, data_dir=expected_data, baseline=self.shadow_baseline(account["username"])
                )
            self.capture_external_policy(account, meta)
            if (
                changes.get("shell")
                and meta["baseline"]["shell"].endswith(("nologin", "false"))
                and changes["shell"] != meta["baseline"]["shell"]
            ):
                raise DomainError(
                    "external_policy_changed", "platform cannot clear external shell restriction", 403
                )
            if meta.get("deleted_at") and action not in {"delete", "restore"}:
                raise DomainError("account_deleted", "restore soft-deleted account first")
            meta["login_policy_status"] = "pending"
            if action == "disable":
                meta["disabled"] = True
            elif action == "enable":
                meta["disabled"] = False
            elif action == "delete":
                meta["deleted_at"] = utcnow().isoformat()
            elif action == "restore":
                meta["deleted_at"] = None
            elif action != "update":
                raise DomainError("unsupported_action", "unsupported account action", 422)
            if meta.get("deleted_at") and action not in {"delete", "restore"}:
                raise DomainError("account_deleted", "restore soft-deleted account first")
            if changes.get("username", account["username"]) != account["username"]:
                self.rename(state, account, meta, changes["username"])
            if changes.get("password"):
                quality_password(changes["password"], account["username"])
                self.run(["chpasswd"], input=f"{account['username']}:{changes['password']}\n")
                # Changing a password must not clear the platform restriction.
                new_hash = self.shadow_baseline(account["username"])["password"]
                external_lock = meta["baseline"]["password"].startswith("!")
                if external_lock or restriction_active(meta) or meta.get("agent_restricted"):
                    self.run(["usermod", "--lock", account["username"]])
                if external_lock:
                    new_hash = "!" + new_hash
                meta["baseline"]["password"] = new_hash
                meta["baseline"]["last_change"] = self.shadow_baseline(account["username"]).get(
                    "last_change", str(int(utcnow().timestamp()) // 86400)
                )
            if "public_keys" in changes:
                self.write_files(account, changes["public_keys"])
        if "primary_group" in changes:
            self.run(["usermod", "--gid", changes["primary_group"], account["username"]])
        if "groups" in changes:
            self.run(["usermod", "--groups", ",".join(changes["groups"]), account["username"]])
        if "shell" in changes:
            if changes["shell"] not in {"/bin/bash", "/bin/sh", "/usr/sbin/nologin"}:
                raise DomainError("invalid_shell", "shell must be an allowed login shell", 422)
            meta["baseline"]["shell"] = changes["shell"]
            if not restriction_active(meta):
                self.run(["usermod", "--shell", changes["shell"], account["username"]])
        for field in ("notes", "public_keys", "expires_on", "require_password_change"):
            if field in changes:
                meta[field] = changes[field]
        if changes.get("require_password_change", action == "create" and bool(changes.get("password"))):
            self.run(["chage", "--lastday", "0", account["username"]])
            meta["require_password_change"] = True
            meta["agent_password_change"] = True
        elif changes.get("require_password_change") is False and meta.get("agent_password_change"):
            if meta["baseline"].get("last_change") == "0":
                raise DomainError(
                    "external_password_policy", "cannot clear external password-change requirement", 403
                )
            self.run(
                [
                    "chage",
                    "--lastday",
                    meta["baseline"].get("last_change") or str(int(utcnow().timestamp()) // 86400),
                    account["username"],
                ]
            )
            meta["agent_password_change"] = False
        self.apply_login(account, meta)
        meta["revision"] += 1
        return self.find(state, account["id"])


def rename_noreplace(source_fd, source, dest_fd, dest):
    lib = ctypes.CDLL(None, use_errno=True)
    if not hasattr(lib, "renameat2"):
        raise DomainError("rename_unavailable", "Linux renameat2 NOREPLACE required", 503)
    lib.renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if lib.renameat2(source_fd, source.encode(), dest_fd, dest.encode(), 1):
        raise DomainError(
            "rename_conflict",
            f"atomic directory rename failed errno {ctypes.get_errno()}; paths retained",
            409,
        )
