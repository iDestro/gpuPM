"""Bounded local RPC; authorization is kernel peer credentials, never JSON actor."""

import json
import socket
import struct

from gpupm.errors import DomainError

MAX_FRAME = 1024 * 1024


def exact(sock, count):
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise DomainError("invalid_frame", "truncated frame", 400)
        data.extend(chunk)
    return bytes(data)


def read_frame(sock):
    size = struct.unpack("!I", exact(sock, 4))[0]
    if not 0 < size <= MAX_FRAME:
        raise DomainError("invalid_frame", "frame exceeds limit", 400)
    try:
        value = json.loads(exact(sock, size))
    except (ValueError, UnicodeError) as exc:
        raise DomainError("invalid_frame", "frame is not UTF-8 JSON", 400) from exc
    if not isinstance(value, dict) or value.get("version") != 1:
        raise DomainError("protocol_version", "Expected protocol version 1", 400)
    return value


def write_frame(sock, value):
    data = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    if len(data) > MAX_FRAME:
        raise DomainError("response_too_large", "frame exceeds limit", 413)
    sock.sendall(struct.pack("!I", len(data)) + data)


def peer_uid(sock):
    if not hasattr(socket, "SO_PEERCRED"):
        raise DomainError("platform_unsupported", "Linux SO_PEERCRED required", 503)
    return struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]


def handle_connection(sock, service, allowed_uid):
    sock.settimeout(10)
    if peer_uid(sock) not in {0, allowed_uid}:
        raise DomainError("peer_forbidden", "Unix peer UID is not authorized", 403)
    try:
        request = read_frame(sock)
        if not isinstance(request.get("method"), str) or not isinstance(request.get("params", {}), dict):
            raise DomainError("invalid_request", "method and params required", 400)
        result = service.call(request["method"], request.get("params", {}))
        write_frame(sock, dict(version=1, result=result))
    except DomainError as exc:
        write_frame(sock, dict(version=1, error=dict(code=exc.code, message=exc.message, status=exc.status)))
