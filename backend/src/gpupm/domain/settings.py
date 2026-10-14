"""Settings shared by the API database and standalone agents."""

DEFAULT_SETTINGS = {
    "scan_interval_seconds": 5,
    "term_grace_seconds": 10,
    "default_max_runtime_seconds": 1800,
    "default_task_protected": False,
    "default_task_priority": 50,
    "default_deadline_action": "notify",
    "default_cleanup_orphans": False,
    "storage_scan_interval_seconds": 900,
    "warning_percent": 80,
    "critical_percent": 90,
}


def task_defaults(settings):
    fields = {
        "max_runtime_seconds": "default_max_runtime_seconds",
        "protected": "default_task_protected",
        "priority": "default_task_priority",
        "deadline_action": "default_deadline_action",
        "cleanup_orphans": "default_cleanup_orphans",
    }
    return {field: settings.get(key, DEFAULT_SETTINGS[key]) for field, key in fields.items()}
