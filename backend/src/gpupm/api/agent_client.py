import json
import socket
import struct

from gpupm.errors import DomainError

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
        data = json.dumps({"version": 1, "method": method, "params": params or {}}).encode()
        if len(data) > MAX_MESSAGE:
            raise DomainError("message_too_large", "请求过大", 413)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.path)
                sock.sendall(struct.pack("!I", len(data)) + data)
                length = struct.unpack("!I", read_exact(sock, 4))[0]
                if not 0 < length <= MAX_MESSAGE:
                    raise DomainError("agent_protocol", "agent 响应长度无效", 503)
                response = json.loads(read_exact(sock, length))
                if response.get("version") != 1:
                    raise DomainError("agent_protocol", "agent 协议版本不兼容", 503)
                if "error" in response:
                    error = response["error"]
                    raise DomainError(error["code"], error["message"], error.get("status", 409))
                return response["result"]
        except (OSError, ValueError, KeyError) as exc:
            raise DomainError("agent_unavailable", "无法连接宿主机 agent，请检查服务状态", 503) from exc
