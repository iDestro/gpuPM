import base64
import json
import socket
import struct

from gpupm.errors import DomainError
from gpupm.agent.protocol import MAX_SNAPSHOT

MAX_MESSAGE = 1024 * 1024


def read_exact(sock, size):
    result = bytearray()
    while len(result) < size:
        block = sock.recv(size - len(result))
        if not block:
            raise DomainError("agent_protocol", "agent 连接提前关闭", 503)
        result.extend(block)
    return bytes(result)


class AgentClient:
    def __init__(self, path, timeout=15):
        self.path, self.timeout = path, timeout

    def call(self, method, params=None):
        request = {"version": 1, "method": method, "params": params or {}}
        if method == "snapshot":
            request["snapshot_stream"] = True
        data = json.dumps(request).encode()
        if len(data) > MAX_MESSAGE:
            raise DomainError("message_too_large", "请求过大", 413)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.path)
                sock.sendall(struct.pack("!I", len(data)) + data)
                assembled = bytearray()
                sequence = 0
                expected_size = None
                while True:
                    length = struct.unpack("!I", read_exact(sock, 4))[0]
                    if not 0 < length <= MAX_MESSAGE:
                        raise DomainError("agent_protocol", "agent 响应长度无效", 503)
                    response = json.loads(read_exact(sock, length))
                    if not isinstance(response, dict) or response.get("version") != 1:
                        raise DomainError("agent_protocol", "agent 协议版本不兼容", 503)
                    if "chunk" not in response:
                        if assembled:
                            raise DomainError("agent_protocol", "agent snapshot interrupted", 503)
                        break
                    size = response.get("snapshot_size")
                    if (
                        method != "snapshot"
                        or type(size) is not int
                        or not 0 < size <= MAX_SNAPSHOT
                        or response.get("sequence") != sequence
                        or (expected_size is not None and expected_size != size)
                    ):
                        raise DomainError("agent_protocol", "agent snapshot sequence invalid", 503)
                    expected_size = size
                    chunk = base64.b64decode(response["chunk"], validate=True)
                    if not chunk or len(assembled) + len(chunk) > size:
                        raise DomainError("agent_protocol", "agent snapshot size invalid", 503)
                    assembled.extend(chunk)
                    sequence += 1
                    if len(assembled) == size:
                        response = json.loads(assembled)
                        if not isinstance(response, dict) or response.get("version") != 1:
                            raise DomainError("agent_protocol", "agent snapshot invalid", 503)
                        break
                if "error" in response:
                    error = response["error"]
                    raise DomainError(error["code"], error["message"], error.get("status", 409))
                return response["result"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DomainError("agent_unavailable", "无法连接宿主机 agent，请检查服务状态", 503) from exc
