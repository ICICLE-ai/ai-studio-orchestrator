"""Tests for shared adapter HTTP helpers."""

import unittest

import httpx
from pydantic import BaseModel

from ai_studio_orchestrator.adapters.http import make_list_request, make_request
from ai_studio_orchestrator.exceptions import (
    AuthenticationError,
    InvalidResponseError,
    ServiceUnavailableError,
    UpstreamServiceError,
)


class ExampleResponse(BaseModel):
    value: str


class HttpAdapterHelperTest(unittest.IsolatedAsyncioTestCase):
    async def test_make_request_validates_model_response(self):
        client = self._client(status_code=200, json={"value": "ok"})

        result = await make_request(
            client=client,
            method="GET",
            url="/example",
            headers={"X-Test": "yes"},
            response_model=ExampleResponse,
            upstream_error_message="upstream failed",
            invalid_response_message="bad response",
            unavailable_message="unavailable",
        )

        self.assertEqual(result.value, "ok")

    async def test_make_request_uses_supplied_upstream_error_class(self):
        client = self._client(status_code=401, text="nope")

        with self.assertRaises(AuthenticationError) as ctx:
            await make_request(
                client=client,
                method="GET",
                url="/example",
                headers={},
                response_model=ExampleResponse,
                upstream_error_message="auth failed",
                invalid_response_message="bad response",
                unavailable_message="unavailable",
                upstream_error_class=AuthenticationError,
            )

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail["message"], "auth failed")

    async def test_make_request_maps_request_error_to_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.test",
        )

        with self.assertRaises(ServiceUnavailableError):
            await make_request(
                client=client,
                method="GET",
                url="/example",
                headers={},
                response_model=ExampleResponse,
                upstream_error_message="upstream failed",
                invalid_response_message="bad response",
                unavailable_message="unavailable",
            )

    async def test_make_request_maps_invalid_payload(self):
        client = self._client(status_code=200, json={"missing": "value"})

        with self.assertRaises(InvalidResponseError) as ctx:
            await make_request(
                client=client,
                method="GET",
                url="/example",
                headers={},
                response_model=ExampleResponse,
                upstream_error_message="upstream failed",
                invalid_response_message="bad response",
                unavailable_message="unavailable",
            )

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(ctx.exception.detail["message"], "bad response")

    async def test_make_list_request_validates_items(self):
        client = self._client(status_code=200, json=[{"value": "one"}, {"value": "two"}])

        result = await make_list_request(
            client=client,
            method="GET",
            url="/example",
            headers={},
            item_type=ExampleResponse,
            upstream_error_message="upstream failed",
            invalid_response_message="bad response",
            unavailable_message="unavailable",
        )

        self.assertEqual([item.value for item in result], ["one", "two"])

    async def test_make_list_request_maps_non_success_status(self):
        client = self._client(status_code=500, text="failed")

        with self.assertRaises(UpstreamServiceError):
            await make_list_request(
                client=client,
                method="GET",
                url="/example",
                headers={},
                item_type=ExampleResponse,
                upstream_error_message="upstream failed",
                invalid_response_message="bad response",
                unavailable_message="unavailable",
            )

    @staticmethod
    def _client(
        *,
        status_code: int,
        json=None,
        text: str | None = None,
    ) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            if json is not None:
                return httpx.Response(status_code=status_code, json=json)
            return httpx.Response(status_code=status_code, text=text or "")

        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.test",
        )
