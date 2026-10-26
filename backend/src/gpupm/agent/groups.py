"""Permission-group policy shared by native and simulated inventories."""

from gpupm.agent.accounts import SENSITIVE_GROUPS
from gpupm.errors import DomainError


def describe_group(group, accounts, shares, private_names=()):
    group = dict(group)
    primary = [a["username"] for a in accounts if a["gid"] == group["gid"]]
    private = any(a["gid"] == group["gid"] and a["username"] == group["name"] for a in accounts)
    kind = (
        "share_internal"
        if group.get("share_owner")
        else "platform"
        if group["name"] == "human"
        else "system"
        if group["gid"] < 1000 or group["name"] in SENSITIVE_GROUPS
        else "private"
        if private or group["name"] in private_names
        else "permission"
    )
    members = set(group["members"]) | set(primary)
    human_members = all(
        any(a["username"] == name and a.get("is_human") and not a.get("protected") for a in accounts)
        for name in members
    )
    eligible = (
        kind == "permission"
        and human_members
        and not group.get("protected")
        and not group.get("identity_conflict")
    )
    managed_members = all(
        any(a["username"] == name and a.get("managed") for a in accounts) for name in members
    )
    group.update(
        kind=kind,
        primary_users=sorted(primary),
        share_refs=sorted(
            str(s["id"]) for s in shares if group["name"] in {s["reader_group"], s["writer_group"]}
        ),
        protected=bool(group.get("protected") or kind != "permission"),
        can_adopt=eligible and not group["managed"],
        assignable=eligible and group["managed"] and managed_members,
    )
    return group


def filter_groups(groups, scope="managed"):
    if scope not in {"managed", "other", "all"}:
        raise DomainError("invalid_scope", "group scope must be managed, other or all", 422)
    return [
        g
        for g in groups
        if scope == "all" or (g["assignable"] if scope == "managed" else not g["assignable"])
    ]


def validate_group_change(group, action, changes):
    if action not in {"create", "update", "delete"}:
        raise DomainError("invalid_action", "unsupported group action", 422)
    if action == "delete" and changes:
        raise DomainError("invalid_fields", "delete must not include changes", 422)
    if set(changes) - {"name", "members", "managed"}:
        raise DomainError("invalid_fields", "unsupported group fields", 422)
    if "managed" in changes:
        if action != "update" or changes != {"managed": True} or changes["managed"] is not True:
            raise DomainError("invalid_adoption", "adoption requires only managed=true", 422)
        if not group["can_adopt"]:
            raise DomainError(
                "protected_group", "only ordinary unmanaged permission groups can be adopted", 403
            )
    elif action != "create" and not group["assignable"]:
        raise DomainError("protected_group", "only managed permission groups editable", 403)
    if changes.get("name", group.get("name")) != group.get("name") and group.get("share_refs"):
        raise DomainError("group_in_use", "group grants shared path access")
    if action == "delete" and (group["members"] or group["primary_users"] or group["share_refs"]):
        raise DomainError("group_in_use", "group has membership, primary or share references")


def require_assignable(groups, names):
    for name in names:
        group = next((g for g in groups if g["name"] == name), None)
        if not group or not group["assignable"]:
            raise DomainError("protected_group", "grant requires a managed ordinary permission group", 403)
