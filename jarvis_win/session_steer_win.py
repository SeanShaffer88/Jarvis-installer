"""Patch ``session_steer`` for AF_UNIX paths and Windows named pipes."""

from __future__ import annotations

from typing import Any

from . import transport


def post_to_session(socket_path: str | None, prompt: str,
                    timeout: float = 5.0) -> str:
    """Same wire format and outcome strings as upstream; two Windows transports."""
    return transport.send_payload(socket_path, prompt, timeout=timeout)


def apply(module: Any) -> Any:
    module.post_to_session = post_to_session
    module.classify_socket_path = transport.classify_socket_path
    module.transport_exists = transport.transport_exists
    return module
