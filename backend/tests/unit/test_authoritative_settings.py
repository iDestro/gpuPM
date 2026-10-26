from types import SimpleNamespace

import pytest

from gpupm.api.context import Context
from gpupm.db.models import Setting
from gpupm.db.session import database
from gpupm.errors import DomainError


class HealthAgent:
    def __init__(self, response):
        self.response = response

    def call(self, method, params=None):
        assert method == 'health'
        return self.response


def context(tmp_path, response):
    _, sessions = database(tmp_path / 'api.db')
    with sessions.begin() as db:
        db.get(Setting, 1).values = {'term_grace_seconds': 10}
    return Context(sessions, HealthAgent(response), SimpleNamespace(
        mode='host', home_base='/wrong-home', data_base='/wrong-data',
    ))


def test_settings_use_agent_roots_not_api_environment(tmp_path):
    roots = {'home_base': '/home', 'data_base': '/data', 'share_base': '/data/shared'}
    result = context(tmp_path, {'roots': roots, 'root_readiness': {'ready': True}}).settings()
    assert {key: result[key] for key in roots} == roots
    assert result['term_grace_seconds'] == 10


def test_settings_refuse_to_invent_roots_when_agent_cannot_confirm(tmp_path):
    with pytest.raises(DomainError, match='initialization'):
        context(tmp_path, {'status': 'ok'}).settings()


def test_snapshot_stays_readable_and_stale_when_agent_health_is_unavailable(tmp_path):
    ctx = context(tmp_path, {})
    with ctx.sessions.begin() as db:
        db.get(Setting, 1).values = {'scan_interval_seconds': 5}

    def unavailable(*args):
        raise DomainError('agent_unavailable', 'agent offline', 503)

    ctx.agent.call = unavailable
    ctx.cached = {'tasks': [], 'collected_at': '2026-10-15T00:00:00+00:00', 'stale': False}
    assert ctx.snapshot()['stale'] is True
    ctx.cached = None
    result = ctx.snapshot(force=True)
    assert result['stale'] is True
    assert result['tasks'] == []
    assert result['errors'] == ['agent offline']
