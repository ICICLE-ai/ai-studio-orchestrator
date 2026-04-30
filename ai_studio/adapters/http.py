"""Shared HTTP request helpers for external service adapters."""

import logging
import time

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_studio.exceptions import (
    InvalidResponseError,
    ServiceError,
    ServiceUnavailableError,
    UpstreamServiceError,
)

logger = logging.getLogger("ai_studio.adapters.http")


def _validation_details(error: ValidationError) -> list[str]:
    """Return compact validation messages suitable for API error details."""
    return [f"{err['loc'][-1]}: {err['msg']}" for err in error.errors()]


async def _send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    json_data: dict | None,
    unavailable_message: str,
) -> httpx.Response:
    """Send an HTTP request, logging timing and translating connection errors."""
    start = time.perf_counter()
    logger.debug("http.request method=%s url=%s", method, url)
    try:
        response = await client.request(
            method=method,
            url=url,
            json=json_data,
            headers=headers,
        )
    except httpx.RequestError as error:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.warning(
            "http.unavailable method=%s url=%s duration_ms=%.2f error=%s",
            method,
            url,
            duration_ms,
            type(error).__name__,
        )
        raise ServiceUnavailableError(
            status_code=503,
            detail={
                "message": unavailable_message,
                "details": f"{type(error).__name__}: {str(error)}",
            },
        ) from error

    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "http.response method=%s url=%s status=%d duration_ms=%.2f",
        method,
        url,
        response.status_code,
        duration_ms,
    )
    return response


async def make_request[T: BaseModel](
    *,
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    response_model: type[T],
    upstream_error_message: str,
    invalid_response_message: str,
    unavailable_message: str,
    json_data: dict | None = None,
    success_statuses: tuple[int, ...] = (200, 201),
    upstream_error_class: type[ServiceError] = UpstreamServiceError,
) -> T:
    """Send a request and validate a Pydantic object response."""
    response = await _send(
        client, method, url, headers, json_data, unavailable_message
    )
    if response.status_code not in success_statuses:
        logger.warning(
            "http.upstream_error method=%s url=%s status=%d",
            method,
            url,
            response.status_code,
        )
        raise upstream_error_class(
            status_code=response.status_code,
            detail={
                "message": upstream_error_message,
                "details": response.text,
            },
        )
    try:
        return response_model.model_validate(response.json())
    except ValidationError as error:
        logger.warning(
            "http.invalid_response method=%s url=%s model=%s",
            method,
            url,
            response_model.__name__,
        )
        raise InvalidResponseError(
            status_code=502,
            detail={
                "message": invalid_response_message,
                "details": _validation_details(error),
            },
        ) from error


async def make_list_request[L](
    *,
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    item_type: type[L],
    upstream_error_message: str,
    invalid_response_message: str,
    unavailable_message: str,
    json_data: dict | None = None,
    success_statuses: tuple[int, ...] = (200, 201),
    upstream_error_class: type[ServiceError] = UpstreamServiceError,
) -> list[L]:
    """Send a request and validate a JSON-array response."""
    response = await _send(
        client, method, url, headers, json_data, unavailable_message
    )
    if response.status_code not in success_statuses:
        logger.warning(
            "http.upstream_error method=%s url=%s status=%d",
            method,
            url,
            response.status_code,
        )
        raise upstream_error_class(
            status_code=response.status_code,
            detail={
                "message": upstream_error_message,
                "details": response.text,
            },
        )
    try:
        adapter = TypeAdapter(list[item_type])
        return adapter.validate_python(response.json())
    except ValidationError as error:
        logger.warning(
            "http.invalid_response method=%s url=%s item_type=%s",
            method,
            url,
            getattr(item_type, "__name__", repr(item_type)),
        )
        raise InvalidResponseError(
            status_code=502,
            detail={
                "message": invalid_response_message,
                "details": _validation_details(error),
            },
        ) from error


async def make_empty_request(
    *,
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    upstream_error_message: str,
    unavailable_message: str,
    json_data: dict | None = None,
    success_statuses: tuple[int, ...] = (200, 204),
    upstream_error_class: type[ServiceError] = UpstreamServiceError,
) -> None:
    """Send a request that does not require response-body validation."""
    response = await _send(
        client, method, url, headers, json_data, unavailable_message
    )
    if response.status_code not in success_statuses:
        logger.warning(
            "http.upstream_error method=%s url=%s status=%d",
            method,
            url,
            response.status_code,
        )
        raise upstream_error_class(
            status_code=response.status_code,
            detail={
                "message": upstream_error_message,
                "details": response.text,
            },
        )
