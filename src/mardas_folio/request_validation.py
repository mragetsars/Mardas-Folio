"""Validate the JSON request boundary without invoking application work."""

from __future__ import annotations

from typing import Any, Mapping

from .engine_errors import EngineError


def validate_params(params: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise EngineError(
            "Unsupported request parameters were supplied.",
            code="MARDAS-INVALID-PARAMS",
            details={"unknown_parameters": unknown},
        )


def optional_bool(params: Mapping[str, Any], key: str, *, default: bool) -> bool:
    value = params.get(key, default)
    if not isinstance(value, bool):
        raise EngineError(
            f"{key} must be true or false.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    return value


def optional_int(
    params: Mapping[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise EngineError(
            f"{key} must be an integer.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    if value < minimum or value > maximum:
        raise EngineError(
            f"{key} must be between {minimum} and {maximum}.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key, "minimum": minimum, "maximum": maximum},
        )
    return value


def string_list(value: Any, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise EngineError(
            f"{key} must be an array of strings.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise EngineError(
                f"{key} must contain only non-empty strings.",
                code="MARDAS-INVALID-PARAMS",
                details={"parameter": key},
            )
        result.append(request_string_value(item, key))
    return tuple(result)


def request_string_value(value: str, key: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EngineError(
            f"{key} must contain valid UTF-8 text.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        ) from exc
    if "\x00" in value:
        raise EngineError(
            f"{key} cannot contain NUL characters.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    return value.strip()


def required_string(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EngineError(
            f"{key} must be a non-empty string.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    return request_string_value(value, key)


def required_content(params: Mapping[str, Any]) -> str:
    value = params.get("content")
    if not isinstance(value, str):
        raise EngineError(
            "content must be a string.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": "content"},
        )
    return value


def optional_string(params: Mapping[str, Any], key: str) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EngineError(
            f"{key} must be a non-empty string when supplied.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    return request_string_value(value, key)


def mapping(value: Any, key: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EngineError(
            f"{key} must be an object.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    return value
