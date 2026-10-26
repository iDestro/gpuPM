from gpupm.domain.settings import task_defaults

POLICY_FIELDS = (
    "priority",
    "max_runtime_seconds",
    "protected",
    "deadline_action",
    "orphan_reminder",
    "orphan_wait_seconds",
)


def resolve_policy(settings, group, user=None):
    values = {k: v for k, v in task_defaults(settings).items() if k in POLICY_FIELDS}
    overrides = (user.personal_policy if user else {}) if group.is_custom else group.policy_overrides
    if group.is_default:
        overrides = {}
    sources = {k: "global" for k in values}
    for key, value in overrides.items():
        if key in values:
            values[key] = value
            sources[key] = "personal" if group.is_custom else "group"
    return values, sources


def policy_editable(account):
    return bool(
        account
        and account.get("is_human")
        and account.get("managed")
        and not account.get("protected")
        and account.get("status") == "active"
        and not account.get("resume_required")
        and not account.get("recovery_required")
        and not account.get("readonly_reasons")
    )
