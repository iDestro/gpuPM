from gpupm.agent.host import AgentService
from gpupm.agent.storage import Storage


def test_share_preview_shows_before_after_without_creating_directories(tmp_path, monkeypatch):
    monkeypatch.setattr("gpupm.agent.storage.share_directory_identity", lambda path: dict(path=str(path),device=1,inode=2))
    service = AgentService(
        dict(store_path=str(tmp_path / "agent.db"), share_base=str(tmp_path / "shared")),
        collector=lambda: ([], [], []),
    )
    service.accounts.validate_permission_groups = lambda *args: None
    storage = Storage(service)
    state = {"shares": [], "previews": {}, "events": []}
    changes = dict(name="research", reader_group="readers", writer_group="writers", notes="Team data")
    preview = storage.dispatch(state, "preview_share_change", {"changes": changes})
    assert preview["current"] is None
    assert preview["proposed"] == dict(changes, path=str(tmp_path / "shared/research"))
    assert not (tmp_path / "shared").exists()
    share = dict(changes, path=str(tmp_path / "shared/research"), id="share", revision=1)
    state["shares"].append(share)
    preview = storage.dispatch(state, "preview_share_change", {
        "id": "share", "revision": 1, "changes": {"reader_group": "visitors"},
    })
    assert preview["current"]["reader_group"] == "readers"
    assert preview["proposed"]["reader_group"] == "visitors"
    assert preview["proposed"]["writer_group"] == "writers"
    assert share["reader_group"] == "readers"


def test_legacy_quota_snapshot_is_not_returned(tmp_path):
    from unittest.mock import Mock
    from gpupm.domain.rules import utcnow

    service = AgentService(dict(store_path=str(tmp_path / "agent.db")), collector=lambda: ([], [], []))
    service.storage_worker = Mock()
    service.storage_worker.is_alive.return_value = True
    state = {"settings": {}, "shares": [], "storage": {
        "quotas": [{"hard_bytes": 100}], "collected_at": utcnow().isoformat(),
        "filesystems": [{"quota_enabled": False, "error": "enable quotas"}],
    }}
    result = Storage(service).dispatch(state, "storage_snapshot", {})
    assert result["directory_collected_at"] is None
    assert "quotas" not in result


def test_host_rejects_removed_quota_methods(tmp_path):
    import pytest
    from gpupm.errors import DomainError

    service = AgentService(dict(store_path=str(tmp_path / "agent.db")), collector=lambda: ([], [], []))
    for method in ("get_quotas", "preview_quota", "apply_quota"):
        with pytest.raises(DomainError) as error:
            service.call(method, {"id": "1001"})
        assert error.value.code == "unsupported"


def test_share_list_never_starts_directory_sampling(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from gpupm.domain.rules import utcnow
    service = AgentService(dict(store_path=str(tmp_path/'agent.db')), collector=lambda: ([], [], []))
    service.storage_worker = None
    service.accounts.groups = lambda state: []
    worker = Mock()
    monkeypatch.setattr('threading.Thread', Mock(return_value=worker))
    state = {'settings': {}, 'shares': [{'id':'s','name':'project','usage_bytes':12}]}
    result = Storage(service).dispatch(state, 'list_shares', {})
    worker.start.assert_not_called()
    assert result[0]['usage_stale'] is True
    assert 'usage_stale' not in state['shares'][0]
    state['shares'][0]['collected_at'] = utcnow().isoformat()
    state['storage'] = {'collected_at':utcnow().isoformat(),'users':[],'shares':state['shares']}
    assert Storage(service).dispatch(state, 'list_shares', {})[0]['usage_stale'] is False


def test_storage_read_and_periodic_collection_do_not_walk_directories(tmp_path, monkeypatch):
    from unittest.mock import Mock
    service = AgentService(dict(store_path=str(tmp_path/'agent.db')), collector=lambda: ([], [], []))
    walk = Mock(side_effect=AssertionError("unexpected directory traversal"))
    monkeypatch.setattr('gpupm.agent.storage.directory_usage', walk)
    service.accounts.list = lambda state: [dict(id='1', username='alice', managed=True, home='/home/alice', data_dir='/data/alice')]
    service.collect_storage()
    result = service.call('storage_snapshot')
    assert result['directory_collected_at'] is None
    walk.assert_not_called()


def test_manual_refresh_deduplicates_running_worker(tmp_path, monkeypatch):
    from unittest.mock import Mock
    service = AgentService(dict(store_path=str(tmp_path/'agent.db')), collector=lambda: ([], [], []))
    worker = Mock()
    worker.is_alive.return_value = True
    factory = Mock(return_value=worker)
    monkeypatch.setattr('threading.Thread', factory)
    assert service.call('refresh_storage')['scanning'] is True
    assert service.call('refresh_storage')['scanning'] is True
    worker.start.assert_called_once()


def test_manual_refresh_completes_and_automatic_collection_keeps_measurement_time(tmp_path, monkeypatch):
    from unittest.mock import Mock
    service = AgentService(dict(store_path=str(tmp_path/'agent.db')), collector=lambda: ([], [], []))
    service.accounts.list = lambda state: [dict(id='1', username='alice', managed=True, home='/home/alice', data_dir='/data/alice')]
    walk = Mock(return_value=dict(bytes=123, status='available'))
    monkeypatch.setattr('gpupm.agent.storage.directory_usage', walk)
    service.call('refresh_storage')
    service.storage_worker.join(timeout=3)
    result = service.call('storage_snapshot')
    assert result['scanning'] is False
    assert result['scan_error'] is None
    assert result['users'][0]['data_bytes'] == 123
    assert result['directory_collected_at']
    assert 'files' not in result['users'][0]
    walk.assert_called()
    walk.reset_mock()
    service.collect_storage()
    assert service.call('storage_snapshot')['directory_collected_at'] == result['directory_collected_at']
    walk.assert_not_called()


def test_manual_scan_failure_is_visible_and_retryable(tmp_path, monkeypatch):
    service = AgentService(dict(store_path=str(tmp_path/'agent.db')), collector=lambda: ([], [], []))
    def fail(**kwargs):
        raise OSError('failed')
    monkeypatch.setattr(service, 'collect_storage', fail)
    service.call('refresh_storage')
    service.storage_worker.join(timeout=3)
    result = service.call('storage_snapshot')
    assert result['scanning'] is False
    assert result['scan_error']
    monkeypatch.setattr(service, 'collect_storage', lambda **kwargs: None)
    service.call('refresh_storage')
    service.storage_worker.join(timeout=3)
    assert service.call('storage_snapshot')['scan_error'] is None
