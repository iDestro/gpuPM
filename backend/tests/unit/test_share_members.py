from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from gpupm.agent.share_members import member_rows, validate_members, MemberGroups
from gpupm.errors import DomainError


def accounts():
    return [
        dict(
            id="1001",
            uid=1001,
            username="alice",
            gid=1001,
            revision=1,
            managed=True,
            is_human=True,
            protected=False,
            status="active",
        )
    ]


def test_member_rows_include_primary_members_and_write_wins():
    groups = [
        dict(name="r", members=["alice", "bob"], primary_users=["carol"]),
        dict(name="w", members=["bob"], primary_users=[]),
    ]
    assert member_rows(dict(reader_group="r", writer_group="w"), groups) == [
        dict(username="alice", permission="read"),
        dict(username="bob", permission="write"),
        dict(username="carol", permission="read"),
    ]


@pytest.mark.parametrize(
    "members",
    [
        [{"username": "root", "permission": "write"}],
        [{"username": "alice", "permission": "admin"}],
        [{"username": "alice", "permission": "read"}] * 2,
    ],
)
def test_members_reject_unknown_invalid_and_duplicate(members):
    with pytest.raises(DomainError):
        validate_members(members, accounts())


def test_protected_unmanaged_deleted_and_recovery_accounts_cannot_be_granted():
    for patch in [
        dict(protected=True),
        dict(managed=False),
        dict(status="deleted"),
        dict(recovery_required=True),
        dict(is_human=False),
    ]:
        with pytest.raises(DomainError):
            validate_members([dict(username="alice", permission="read")], [dict(accounts()[0], **patch)])


def test_native_group_ownership_collision_never_adopts_existing_group(monkeypatch):
    monkeypatch.setattr(
        "gpupm.agent.share_members.grp.getgrnam", lambda name: SimpleNamespace(gr_gid=2001, gr_mem=[])
    )
    service = SimpleNamespace(accounts=SimpleNamespace(run=Mock()))
    with pytest.raises(DomainError):
        MemberGroups(service, {"groups": {}}, "research").scope()
    service.accounts.run.assert_not_called()


def test_internal_share_groups_cannot_be_assigned_or_edited_elsewhere():
    from gpupm.agent.groups import describe_group, require_assignable, validate_group_change
    group = describe_group(dict(id='gps_internal',name='gps_internal',gid=2200,members=[],managed=True,share_owner='project'),accounts(),[])
    assert group['kind'] == 'share_internal'
    assert not group['assignable'] and group['protected']
    with pytest.raises(DomainError):
        require_assignable([group], [group['name']])
    with pytest.raises(DomainError):
        validate_group_change(group, 'update', dict(members=['alice']))


def test_invalid_member_error_identifies_deleted_member_in_mixed_list():
    active = dict(accounts()[0], username='gpu_trial')
    deleted = dict(accounts()[0], username='old_test', status='deleted')
    assert validate_members([dict(username='gpu_trial',permission='read')],[active])
    with pytest.raises(DomainError) as error:
        validate_members([dict(username='gpu_trial',permission='read'),dict(username='old_test',permission='write')],[active,deleted])
    assert str(error.value) == 'Invalid shared member: old_test'
