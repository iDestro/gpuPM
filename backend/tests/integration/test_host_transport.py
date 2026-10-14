import os
import socket
import subprocess
import sys
import threading

import pytest

from gpupm.agent.host import AgentService
from gpupm.agent.protocol import handle_connection, read_frame, write_frame

pytestmark = pytest.mark.linux


@pytest.mark.skipif(sys.platform != "linux", reason="Linux kernel SO_PEERCRED required")
def test_real_peer_socket_and_read_only_dispatch(tmp_path):
    service = AgentService({"store_path": str(tmp_path / "agent.sqlite")}, collector=lambda: ([], [], []))
    client, server = socket.socketpair()
    worker = threading.Thread(target=lambda: handle_connection(server, service, os.getuid()))
    try:
        worker.start()
        write_frame(client, dict(version=1, method="health", params={}))
        assert read_frame(client)["result"] == dict(status="ok", source="host", mutations=False)
        worker.join(timeout=3)
        assert not worker.is_alive()
    finally:
        client.close()
        server.close()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux procfs required")
def test_real_process_identity_is_stable_and_root_is_protected():
    from gpupm.agent.processes import proc_identity, signal_identity

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(15)"])
    try:
        identity = proc_identity(child.pid)
        assert proc_identity(child.pid) == identity
        if os.getuid() == 0:
            assert signal_identity(identity, 15) == "protected"
            assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=3)
