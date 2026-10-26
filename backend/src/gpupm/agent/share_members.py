"""Directory-local membership policy and root-owned permission groups."""

import grp
import hashlib
import logging
import pwd

from gpupm.domain.rules import utcnow, validate_name
from gpupm.errors import DomainError


def member_rows(share, groups):
    by_name = {g["name"]: g for g in groups}
    permissions = {}
    for field, permission in [("reader_group", "read"), ("writer_group", "write")]:
        group = by_name.get(share.get(field))
        if group is None:
            raise DomainError(
                "share_members_unavailable", "Shared directory membership could not be verified", 409
            )
        for name in set(group.get("members", [])) | set(group.get("primary_users", [])):
            permissions[name] = permission
    return [dict(username=name, permission=value) for name, value in sorted(permissions.items())]


def validate_members(members, accounts):
    if not isinstance(members, list) or len(members) > 256:
        raise DomainError("invalid_members", "Expected at most 256 members", 422)
    known = {a["username"]: a for a in accounts}
    result = []
    seen = set()
    for member in members:
        if not isinstance(member, dict) or set(member) != {"username", "permission"}:
            raise DomainError("invalid_members", "Expected username and read/write permission", 422)
        try:
            name = validate_name(member["username"])
        except (ValueError, TypeError) as exc:
            raise DomainError("invalid_members", "Invalid member name", 422) from exc
        if member["permission"] not in {"read", "write"} or name in seen:
            raise DomainError("invalid_members", "Invalid or duplicate shared member", 422)
        account = known.get(name)
        if (
            not account
            or not account.get("managed")
            or not account.get("is_human")
            or account.get("protected")
            or account.get("status") != "active"
            or account.get("disabled")
            or bool(account.get("expires_on") and account["expires_on"] <= utcnow().date().isoformat())
            or any(
                account.get(k)
                for k in ("deleted_at", "recovery_required", "identity_conflict", "rename_recovery_required")
            )
        ):
            raise DomainError("invalid_share_member", f"Invalid shared member: {name}", 403)
        seen.add(name)
        result.append(dict(username=name, permission=member["permission"]))
    return sorted(result, key=lambda m: m["username"])


class MemberGroups:
    def __init__(self, service, state, name):
        self.service, self.state, self.owner = service, state, name
        stem = "gps_" + hashlib.sha256(name.encode()).hexdigest()[:16]
        self.names = {"reader_group": stem + "_r", "writer_group": stem + "_w"}

    def scope(self):
        result = {}
        for name in self.names.values():
            meta = self.state.get("groups", {}).get(name)
            try:
                entry = grp.getgrnam(name)
            except KeyError:
                if meta:
                    raise DomainError("identity_conflict", "Directory permission group disappeared", 409)
                result[name] = None
                continue
            if not meta or meta.get("share_owner") != self.owner or meta.get("gid") != entry.gr_gid:
                raise DomainError("identity_conflict", "Directory permission group identity conflict", 409)
            if any(a.pw_gid == entry.gr_gid for a in pwd.getpwall()):
                raise DomainError(
                    "identity_conflict", "Directory permission group is used as a primary group", 409
                )
            result[name] = dict(gid=entry.gr_gid, members=sorted(entry.gr_mem))
        return result

    def apply(self, members):
        current = self.scope()
        for name, entry in current.items():
            if entry is None:
                self.service.accounts.run(["groupadd", name])
                self.state.setdefault("groups", {})[name] = dict(
                    gid=grp.getgrnam(name).gr_gid, revision=1, share_owner=self.owner
                )
                self.service.accounts.checkpoint(self.state)
        # Revoke before granting, including write-to-read transitions.
        targets = {
            name: sorted(m["username"] for m in members if m["permission"] == permission)
            for field, permission in [("reader_group", "read"), ("writer_group", "write")]
            for name in [self.names[field]]
        }
        for name, target in targets.items():
            retained = sorted(set(grp.getgrnam(name).gr_mem) & set(target))
            self.service.accounts.run(["gpasswd", "--members", ",".join(retained), name])
        for name, target in targets.items():
            self.service.accounts.run(["gpasswd", "--members", ",".join(target), name])
            if sorted(grp.getgrnam(name).gr_mem) != target:
                raise DomainError("share_members_unverified", "Directory membership readback failed", 503)
            self.state["groups"][name]["revision"] += 1

    def restrict_after_failure(self):
        for name in self.names.values():
            try:
                entry = grp.getgrnam(name)
                meta = self.state.get("groups", {}).get(name, {})
                if meta.get("share_owner") == self.owner and meta.get("gid") == entry.gr_gid:
                    self.service.accounts.run(["gpasswd", "--members", "", name])
            except Exception:
                logging.getLogger(__name__).exception(
                    "Failed to restrict directory permission group %s", name
                )
