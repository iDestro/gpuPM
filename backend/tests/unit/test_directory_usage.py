import os

from gpupm.agent.storage import directory_usage


def allocated(path):
    return path.lstat().st_blocks * 512


def test_usage_counts_allocated_blocks_and_hardlinks_once_per_root(tmp_path):
    root = tmp_path / "usage"
    root.mkdir()
    nested = root / "nested"
    nested.mkdir()
    regular = root / "regular"
    regular.write_bytes(b"a" * 12345)
    sparse = nested / "sparse"
    with sparse.open("wb") as handle:
        handle.truncate(1024**3)
    os.link(regular, nested / "hardlink")
    expected = sum(allocated(path) for path in (root, nested, regular, sparse))
    assert directory_usage(root) == {"bytes": expected, "status": "available"}
    assert directory_usage(nested)["bytes"] == sum(allocated(path) for path in (nested, sparse, regular))


def test_usage_list_error_is_partial(tmp_path, monkeypatch):
    original = os.listdir

    def denied(fd):
        if isinstance(fd, int):
            raise PermissionError("unreadable directory")
        return original(fd)

    monkeypatch.setattr(os, "listdir", denied)
    assert directory_usage(tmp_path) == {"bytes": allocated(tmp_path), "status": "partial"}


def test_usage_skips_foreign_devices_and_link_targets(tmp_path, monkeypatch):
    from types import SimpleNamespace

    root = tmp_path / "root"
    root.mkdir()
    foreign = root / "foreign"
    foreign.mkdir()
    (foreign / "large").write_bytes(b"large" * 1000)
    target = tmp_path / "target"
    target.write_bytes(b"target" * 1000)
    link = root / "link"
    link.symlink_to(target)
    original = os.stat

    def different_device(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == "foreign":
            return SimpleNamespace(st_dev=info.st_dev + 1)
        return info

    monkeypatch.setattr(os, "stat", different_device)
    assert directory_usage(root) == {
        "bytes": allocated(root) + allocated(link),
        "status": "available",
    }
