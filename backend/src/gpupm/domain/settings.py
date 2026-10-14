"""Settings shared by the API database and standalone agents."""

import posixpath
import shlex

DEFAULT_SETTINGS = {
    "ignored_task_executables": ["/usr/lib/xorg/Xorg", "/usr/bin/Xorg"],
    "scan_interval_seconds": 5,
    "term_grace_seconds": 10,
    "default_max_runtime_seconds": 1800,
    "default_task_protected": False,
    "default_task_priority": 50,
    "default_deadline_action": "notify",
    "default_cleanup_orphans": False,
    "default_orphan_reminder": True,
    "default_orphan_wait_seconds": 300,
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
        "orphan_reminder": "default_orphan_reminder",
        "orphan_wait_seconds": "default_orphan_wait_seconds",
    }
    return {field: settings.get(key, DEFAULT_SETTINGS[key]) for field, key in fields.items()}


def validate_ignored_executables(value):
    if type(value) is not list or len(value) > 50:
        raise ValueError("ignored executables must be a list of at most 50 exact absolute paths")
    for path in value:
        if (
            type(path) is not str
            or not path.startswith("/")
            or path.startswith("//")
            or len(path) > 4096
            or posixpath.normpath(path) != path
            or any(char in path for char in "\0\n\r*?[]{}|^$()+\\")
        ):
            raise ValueError("ignored executable must be a normalized absolute path without patterns")
    return value


def ignored_process(process, executables):
    # Native exe is authoritative; argv fallback is only for old/demo records without it.
    if "exe" in process:
        executable = process["exe"]
    else:
        try:
            argv = process.get("argv") or shlex.split(process.get("command", ""))
        except ValueError:
            return False
        executable = argv[0] if argv else None
    return bool(executable and executable.startswith("/") and executable in executables)
