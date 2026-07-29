from __future__ import annotations

from dataclasses import dataclass
from typing import Any

JSONRPC_VERSION = "2.0"
PROTOCOL_NAME = "mardas-sidecar"
PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 8 * 1024 * 1024

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
APPLICATION_ERROR = -32010
JOB_CANCELLED = -32011
SERVER_BUSY = -32012


@dataclass(frozen=True, slots=True)
class RpcRequest:
    request_id: str | int
    method: str
    params: dict[str, Any]


class ProtocolError(ValueError):
    def __init__(
        self,
        code: int,
        message: str,
        *,
        request_id: str | int | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.request_id = request_id
        self.data = data


def parse_request(payload: Any) -> RpcRequest:
    if not isinstance(payload, dict):
        raise ProtocolError(INVALID_REQUEST, "JSON-RPC request must be an object.")
    request_id = payload.get("id")
    if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
        raise ProtocolError(
            INVALID_REQUEST,
            "JSON-RPC request id must be a string or integer.",
            request_id=None,
        )
    if payload.get("jsonrpc") != JSONRPC_VERSION:
        raise ProtocolError(
            INVALID_REQUEST,
            f"jsonrpc must equal {JSONRPC_VERSION!r}.",
            request_id=request_id,
        )
    method = payload.get("method")
    if not isinstance(method, str) or not method.strip():
        raise ProtocolError(
            INVALID_REQUEST,
            "JSON-RPC method must be a non-empty string.",
            request_id=request_id,
        )
    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise ProtocolError(
            INVALID_PARAMS,
            "JSON-RPC params must be an object.",
            request_id=request_id,
        )
    return RpcRequest(request_id=request_id, method=method.strip(), params=params)


def success_response(request_id: str | int, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def error_response(
    request_id: str | int | None,
    code: int,
    message: str,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": int(code), "message": str(message)}
    if data:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}


def notification(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "method": method, "params": params}
