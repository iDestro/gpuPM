import json
import socket
import threading
import tempfile

import pytest

from gpupm.agent import protocol
from gpupm.api.agent_client import AgentClient
from gpupm.errors import DomainError


def test_snapshot_larger_than_frame_is_coherent_and_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(protocol, "peer_uid", lambda sock: 1000)
    directory = tempfile.TemporaryDirectory(dir="/tmp")
    path = directory.name + "/rpc.sock"
    expected = {
        "tasks": [{"id": str(i), "name": "训练" * 400, "revision": 7} for i in range(1200)],
        "collected_at": "one-snapshot",
    }
    assert len(json.dumps(expected).encode()) > protocol.MAX_FRAME

    class Service:
        calls = 0

        def call(self, method, params):
            assert method == "snapshot"
            self.calls += 1
            return expected

    service = Service()
    errors = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(path)
        listener.listen()

        def serve():
            try:
                with listener.accept()[0] as connection:
                    protocol.handle_connection(connection, service, 1000)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=serve)
        worker.start()
        try:
            assert AgentClient(path).call("snapshot") == expected
        finally:
            worker.join(5)
        assert not worker.is_alive()
    assert not errors
    assert service.calls == 1
    directory.cleanup()


def test_nonstream_frame_limit_remains():
    sock, peer = socket.socketpair()
    with sock, peer:
        with pytest.raises(DomainError, match="frame exceeds limit"):
            protocol.write_frame(sock, {"version": 1, "result": "x" * protocol.MAX_FRAME})


@pytest.mark.parametrize(
    "fault", ["truncated", "sequence", "size_changed", "over_limit", "bad_base64", "interrupted"]
)
def test_invalid_stream_never_returns_partial_snapshot(monkeypatch, fault):
    import base64
    import struct

    data = json.dumps({"version": 1, "result": {"tasks": [{"id": "task"}]}}).encode()
    first = dict(version=1, sequence=0, snapshot_size=len(data), chunk=base64.b64encode(data[:8]).decode())
    second = dict(version=1, sequence=1, snapshot_size=len(data), chunk=base64.b64encode(data[8:]).decode())
    frames = [first, second]
    if fault == "truncated":
        frames.pop()
    elif fault == "sequence":
        second["sequence"] = 0
    elif fault == "size_changed":
        second["snapshot_size"] += 1
    elif fault == "over_limit":
        first["snapshot_size"] = protocol.MAX_SNAPSHOT + 1
    elif fault == "bad_base64":
        first["chunk"] = "$$$"
    elif fault == "interrupted":
        frames[1] = {"version": 1, "result": {"tasks": []}}
    encoded = [json.dumps(f).encode() for f in frames]

    class Socket:
        wire = b"".join(struct.pack("!I", len(f)) + f for f in encoded)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, timeout):
            pass

        def connect(self, path):
            pass

        def sendall(self, data):
            pass

        def recv(self, count):
            result, self.wire = self.wire[:count], self.wire[count:]
            return result

    monkeypatch.setattr(socket, "socket", lambda *args: Socket())
    with pytest.raises(DomainError):
        AgentClient("unused").call("snapshot")


def test_old_snapshot_client_gets_normal_frame(monkeypatch):
    monkeypatch.setattr(protocol, "peer_uid", lambda sock: 1000)

    class Service:
        def call(self, method, params):
            return {"tasks": []}

    client, server = socket.socketpair()
    with client, server:
        worker = threading.Thread(target=protocol.handle_connection, args=(server, Service(), 1000))
        worker.start()
        protocol.write_frame(client, {"version": 1, "method": "snapshot", "params": {}})
        assert protocol.read_frame(client) == {"version": 1, "result": {"tasks": []}}
        worker.join(3)
        assert not worker.is_alive()
