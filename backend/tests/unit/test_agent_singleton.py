import fcntl
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gpupm.agent import main


def test_second_agent_cannot_initialize_store_before_acquiring_lock(tmp_path, monkeypatch):
    path = tmp_path / 'agent.sock'
    lock = os.open(str(path) + '.lock', os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    original_fstat = os.fstat

    def owned_stat(fd):
        info = original_fstat(fd)
        return SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_nlink=info.st_nlink)

    monkeypatch.setattr(main.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(main.os, 'fstat', owned_stat)
    monkeypatch.setattr(main.socket, 'SO_PEERCRED', 17, raising=False)
    initialize = Mock()
    monkeypatch.setattr(main, 'AgentService', initialize)
    try:
        with pytest.raises(BlockingIOError):
            main.serve({'socket_path': str(path)})
        initialize.assert_not_called()
        assert not path.exists()
    finally:
        os.close(lock)
