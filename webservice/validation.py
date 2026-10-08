"""Return validation details without echoing non-finite JSON input values."""

from fastapi import Request
from fastapi.responses import JSONResponse


def validation_error_handler(_request: Request, error) -> JSONResponse:
    # An overflowing JSON number can become infinity, which JSONResponse cannot
    # serialize in FastAPI's default validation error payload.
    details = [
        {key: item[key] for key in ("loc", "msg", "type")} for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": details})
