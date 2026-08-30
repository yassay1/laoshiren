from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from laoshiren.domain.personal_state.exceptions import (
    EntityNotFound,
    InvalidStateTransition,
    VersionConflict,
)


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: object | None = None,
) -> JSONResponse:
    error: dict[str, object] = {
        "code": code,
        "message": message,
        "request_id": request.state.request_id,
    }
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status_code, content=jsonable_encoder({"error": error}))


async def entity_not_found_handler(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, EntityNotFound):
        raise exception
    return error_response(
        request,
        status_code=status.HTTP_404_NOT_FOUND,
        code="NOT_FOUND",
        message=str(exception),
    )


async def version_conflict_handler(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, VersionConflict):
        raise exception
    return error_response(
        request,
        status_code=status.HTTP_409_CONFLICT,
        code="VERSION_CONFLICT",
        message=str(exception),
    )


async def invalid_state_transition_handler(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, InvalidStateTransition):
        raise exception
    return error_response(
        request,
        status_code=status.HTTP_409_CONFLICT,
        code="INVALID_STATE_TRANSITION",
        message=str(exception),
    )


async def http_exception_handler(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, HTTPException):
        raise exception
    return error_response(
        request,
        status_code=exception.status_code,
        code="HTTP_ERROR",
        message=str(exception.detail),
    )


async def request_validation_handler(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, RequestValidationError):
        raise exception
    return error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        details=exception.errors(),
    )


async def value_error_handler(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, ValueError):
        raise exception
    return error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="VALIDATION_ERROR",
        message=str(exception),
    )
