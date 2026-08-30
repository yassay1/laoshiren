from typing import Any


def build_tool_receipt(
    *,
    tool_name: str,
    status: str,
    code: str,
    message: str,
    data: dict[str, Any],
    mutation_refs: list[str] | tuple[str, ...] = (),
    source_refs: list[str] | tuple[str, ...] = (),
    retryable: bool = False,
    warnings: list[str] | None = None,
    current_state: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refs = list(mutation_refs)
    sources = list(source_refs)
    return {
        "status": status,
        "code": code,
        "message": message,
        "data": data,
        "retryable": retryable,
        "mutation_refs": refs,
        "source_refs": sources,
        "receipt": {
            "code": code,
            "data": data,
            "mutation_refs": refs,
            "source_refs": sources,
        },
        "error": error,
        "warnings": warnings or [],
        "current_state": current_state,
        "tool_name": tool_name,
    }
