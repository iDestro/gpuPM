"""Local SSH/PAM matrix via the running agent; no existing credentials are read."""

import argparse
import errno
import os
import pty
import re
import secrets
import select
import signal
import tempfile
import time
from pathlib import Path

from native_acceptance_common import CheckFailed, as_user, execute, require, run

# Match complete prompts only; ordering distinguishes current/new/retype from login.
PROMPTS = re.compile(
    rb"(?i)(retype[^\r\n:]*password:|(?:enter )?new[^\r\n:]*password:|(?:\(current\)|current|old)[^\r\n:]*password:|[^\r\n:]*password:)[ \t]*$"
)


def prompt_stage(buffer):
    match = PROMPTS.search(buffer)
    if not match:
        # Retain the byte buffer across reads; a split UTF-8 character is matched only when complete.
        text = buffer.decode("utf-8", errors="ignore")
        for stage, pattern in (
            ("retype", r"(?:重新|再次)输入[^\r\n:：]*密码[:：][ \t]*$"),
            ("new", r"(?:输入)?新(?:的)?\s*(?:UNIX\s*)?密码[:：][ \t]*$"),
            ("current", r"当前(?:的)?\s*(?:UNIX\s*)?密码[:：][ \t]*$"),
        ):
            if re.search(pattern, text, re.IGNORECASE):
                return stage
        return None
    prompt = match[1].lower().lstrip()
    if prompt.startswith(b"retype "):
        return "retype"
    if prompt.startswith((b"new ", b"enter new ")):
        return "new"
    if prompt.startswith((b"(current)", b"current ", b"old ")):
        return "current"
    return "login"


def prompt_reply(buffer, old, new):
    stage = prompt_stage(buffer)
    return None if stage is None else new if stage in {"new", "retype"} else old


def diagnostic_tail(transcript, old, new, limit=1500):
    text = transcript.decode("utf-8", errors="replace")
    for secret in sorted({old, new} - {""}, key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    text = re.sub(
        r"-----BEGIN [^\n]*PRIVATE KEY-----[\s\S]*", "[private key redacted]", text
    )
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = "".join(
        character
        for character in text
        if character.isprintable() or character in "\n\t"
    )
    for secret in sorted({old, new} - {""}, key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    return text[-limit:]


def expiry_denied(result):
    output = (result.stdout + "\n" + result.stderr).lower()
    evidence = any(
        message in output
        for message in (
            "password has expired",
            "password expired",
            "password change required",
            "must change your password",
            "required to change your password",
        )
    )
    transport_failure = any(
        message in output
        for message in (
            "connection refused",
            "connection timed out",
            "could not resolve hostname",
            "host key verification failed",
            "permission denied (",
        )
    )
    return (
        result.returncode != 0
        and evidence
        and not transport_failure
        and "GPUPM_COMMAND_EXECUTED" not in result.stdout
    )


def sftp_denied_after_expiry(result, mode, ssh_expiry_confirmed):
    method = "publickey" if mode == "key" else "password"
    authenticated = re.search(
        r'Authenticated to 127\.0\.0\.1 [^\r\n]* using "' + method + r'"\.',
        result.stderr,
    )
    return bool(
        ssh_expiry_confirmed
        and authenticated
        and result.returncode != 0
        and "Remote working directory:" not in result.stdout
    )


def change_interactively(command, env, old, new):
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(command[0], command, env)
    deadline = time.monotonic() + 45
    buffer, transcript = b"", b""
    stages = {"login": 0, "current": 0, "new": 0, "retype": 0}
    changed = False
    stop = "timeout"
    try:
        while time.monotonic() < deadline:
            if not select.select([fd], [], [], 0.2)[0]:
                continue
            try:
                data = os.read(fd, 4096)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    stop = "terminal_closed"
                    break
                raise
            if not data:
                stop = "terminal_closed"
                break
            transcript += data
            if len(transcript) > 65536:
                stop = "terminal_output_limit"
                break
            buffer += data
            if any(
                message in buffer.lower()
                for message in (
                    b"password updated successfully",
                    b"all authentication tokens updated successfully",
                    "成功更新密码".encode(),
                    "密码已成功更新".encode(),
                )
            ):
                changed = True
                os.write(fd, b"exit\n")
                break
            stage = prompt_stage(buffer)
            if stage is not None:
                stages[stage] += 1
                if sum(stages.values()) > 5:
                    stop = "password_prompt_loop"
                    break
                reply = new if stage in {"new", "retype"} else old
                os.write(fd, reply.encode() + b"\n")
                buffer = b""
        if not changed:
            raise CheckFailed(
                f"interactive_password_change:{stop}; prompts={stages}; "
                f"terminal_tail={diagnostic_tail(transcript, old, new)!r}"
            )
    finally:
        # Only explicitly redacted failure diagnostics may leave this function.
        os.close(fd)
        finished, _ = os.waitpid(pid, os.WNOHANG)
        if not finished:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)


def matrix(f, args):
    with tempfile.TemporaryDirectory(prefix="gpupm-ssh-qa-") as tmp:
        base = Path(tmp)
        key = base / "identity"
        require(
            run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)]
            ).returncode
            == 0,
            "key generation failed",
        )
        askpass = base / "askpass"
        askpass.write_text(
            '#!/usr/bin/env python3\nimport os\nprint(os.environ["GPUPM_QA_PASSWORD"])\n'
        )
        askpass.chmod(0o700)
        common = [
            "-o",
            "ConnectTimeout=5",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={base / 'known_hosts'}",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "SendEnv=LC_ALL",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "IdentityAgent=none",
            "-o",
            "NumberOfPasswordPrompts=1",
            "-o",
            "KbdInteractiveAuthentication=no",
        ]

        def options(mode):
            return common + (
                [
                    "-i",
                    str(key),
                    "-o",
                    "PreferredAuthentications=publickey",
                    "-o",
                    "PasswordAuthentication=no",
                ]
                if mode == "key"
                else [
                    "-o",
                    "PreferredAuthentications=password",
                    "-o",
                    "PubkeyAuthentication=no",
                ]
            )

        def env(password):
            return dict(
                os.environ,
                LC_ALL="C",
                GPUPM_QA_PASSWORD=password,
                SSH_ASKPASS=str(askpass),
                SSH_ASKPASS_REQUIRE="force",
                DISPLAY=":999",
            )

        def ssh(account, mode, password, command):
            return run(
                [
                    "ssh",
                    "-F",
                    "/dev/null",
                    "-p",
                    str(args.port),
                    *options(mode),
                    "-T",
                    account["username"] + "@127.0.0.1",
                    command,
                ],
                input="",
                env=env(password),
                start_new_session=True,
            )

        def sftp(account, mode, password):
            # -b forces BatchMode, which disables password auth; stdin commands cover both modes.
            return run(
                [
                    "sftp",
                    "-o",
                    "LogLevel=DEBUG1",  # OpenSSH keeps the first value, before common ERROR.
                    "-F",
                    "/dev/null",
                    "-P",
                    str(args.port),
                    *options(mode),
                    account["username"] + "@127.0.0.1",
                ],
                input="pwd\nquit\n",
                env=env(password),
                start_new_session=True,
            )

        for interactive_mode in ("password", "key"):
            old, new = (secrets.token_urlsafe(24) + "9!aB" for _ in range(2))
            account = f.create(
                interactive_mode,
                password=old,
                public_keys=[key.with_suffix(".pub").read_text().strip()],
                require_password_change=True,
            )
            for mode in ("password", "key"):
                result = ssh(account, mode, old, "printf GPUPM_COMMAND_EXECUTED")
                label = f"{interactive_mode}:initial:{mode}:command_expiry_denied"
                ssh_expiry_confirmed = expiry_denied(result)
                require(
                    ssh_expiry_confirmed,
                    label
                    + ": "
                    + diagnostic_tail(
                        (result.stdout + result.stderr).encode(), old, new
                    ),
                )
                f.check(True, label)
                result = sftp(account, mode, old)
                label = f"{interactive_mode}:initial:{mode}:sftp_authenticated_denial_after_ssh_expiry"
                require(
                    sftp_denied_after_expiry(result, mode, ssh_expiry_confirmed),
                    label
                    + ": "
                    + diagnostic_tail(
                        (result.stdout + result.stderr).encode(), old, new
                    ),
                )
                f.check(True, label)
            interactive_env = dict(os.environ, LC_ALL="C", SSH_ASKPASS_REQUIRE="never")
            change_interactively(
                [
                    "ssh",
                    "-F",
                    "/dev/null",
                    "-p",
                    str(args.port),
                    *options(interactive_mode),
                    "-tt",
                    account["username"] + "@127.0.0.1",
                ],
                interactive_env,
                old,
                new,
            )
            f.check(True, f"{interactive_mode}:interactive_password_change")
            for mode in ("password", "key"):
                result = ssh(account, mode, new, "id -un; umask")
                lines = result.stdout.strip().splitlines()
                f.check(
                    result.returncode == 0
                    and len(lines) == 2
                    and lines[0] == account["username"]
                    and lines[1] in ("0077", "077"),
                    f"{interactive_mode}:changed:{mode}:command_and_umask077",
                )
                result = sftp(account, mode, new)
                f.check(
                    result.returncode == 0
                    and "Remote working directory:" in result.stdout,
                    f"{interactive_mode}:changed:{mode}:sftp",
                )
            f.check(
                ssh(account, "password", old, "true").returncode != 0,
                f"{interactive_mode}:old_password_denied",
            )
        first, other = f.accounts
        for field in ("home", "data_dir"):
            target = Path(first[field])
            f.check(target.stat().st_mode & 0o777 == 0o700, f"private:{field}:mode0700")
            result = as_user(other, "import os,sys; os.listdir(sys.argv[1])", target)
            f.check(result.returncode != 0, f"private:{field}:other_account_denied")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--output")
    raise SystemExit(execute(parser.parse_args(), matrix))
