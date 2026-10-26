from pathlib import Path
from unittest.mock import Mock

import pytest

from gpupm.agent.host import AgentService
from gpupm.agent.storage import Storage
from gpupm.errors import DomainError


def test_share_creation_checks_configured_devices_before_native_write(tmp_path, monkeypatch):
    home, data, shared = (tmp_path / name for name in ("home", "data", "shared"))
    for directory in (home, data, shared):
        directory.mkdir()
    service = AgentService(
        dict(
            store_path=str(tmp_path / "agent.db"),
            home_base=str(home),
            data_base=str(data),
            share_base=str(shared),
            data_dev_id=data.stat().st_dev + 1,
        ),
        collector=lambda: ([], [], []),
    )
    service.accounts.validate_permission_groups = lambda *args: None
    service.accounts.run = Mock()
    monkeypatch.setattr("gpupm.agent.storage.secure_directory", Path)
    storage = Storage(service)
    state = {"shares": [], "previews": {}, "events": []}
    changes = dict(name="research", reader_group="readers", writer_group="writers")
    preview = storage.dispatch(state, "preview_share_change", {"changes": changes})
    with pytest.raises(DomainError) as error:
        storage.dispatch(state, "execute_share_change", dict(changes=changes, token=preview["token"]))
    assert error.value.code == "device_mismatch"
    assert not (shared / "research").exists()
    service.accounts.run.assert_not_called()




def test_filesystem_discovery_preserves_kernel_mount_id(monkeypatch, tmp_path):
    from gpupm.agent.storage import filesystems

    import os

    stats = os.statvfs(tmp_path)
    monkeypatch.setattr(Path, "read_text", lambda self: "123 1 8:16 / /data rw - ext4 /dev/sdb rw,usrquota\n")
    monkeypatch.setattr("gpupm.agent.storage.os.statvfs", lambda path: stats)
    discovered = filesystems()
    assert discovered[0]["mount_id"] == "123"
    assert discovered[0]["device"] == "/dev/sdb"
    assert discovered[0]["fstype"] == "ext4"
