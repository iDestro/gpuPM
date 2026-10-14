from datetime import datetime, timedelta, timezone

import pytest

from gpupm.domain.rules import account_status, deadline, priority_key, validate_name


def test_priority_is_lexicographic_and_integer_only():
    assert priority_key(80, 0, 0) > priority_key(79, 100, 100)
    assert priority_key(80, 60, 0) > priority_key(80, 59, 100)
    for bad in [-1, 101, 1.5, True]:
        with pytest.raises(ValueError):
            priority_key(bad, 50, 50)


def test_deadline_uses_start_and_earlier_limit():
    start = datetime(2026, 10, 14, tzinfo=timezone.utc)
    assert deadline(start, 3600, start + timedelta(hours=2)) == start + timedelta(hours=1)
    assert deadline(start, None, None) is None
    with pytest.raises(ValueError):
        deadline(start.replace(tzinfo=None), 1, None)


def test_independent_login_restrictions():
    assert account_status(deleted=True, disabled=True, expired=True) == "deleted"
    assert account_status(deleted=False, disabled=True, expired=True) == "disabled"
    assert account_status(deleted=False, disabled=False, expired=True) == "expired"
    assert account_status(deleted=False, disabled=False, expired=False) == "active"


@pytest.mark.parametrize("name", ["root", "shared", "-evil", "../bob", "a;id", "UPPER", "a b"])
def test_unsafe_names_rejected(name):
    with pytest.raises(ValueError):
        validate_name(name)


def test_normal_name_accepted():
    assert validate_name("alice_2") == "alice_2"
