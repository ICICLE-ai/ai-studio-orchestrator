"""Tests for Garage provisioning behavior."""

import unittest
from unittest.mock import AsyncMock

from pydantic import SecretStr

from ai_studio_orchestrator.adapters.garage.client import GarageClient
from ai_studio_orchestrator.adapters.garage.schemas import ListGarageKeysResponseItem
from ai_studio_orchestrator.exceptions import GarageKeyConflictError


class GarageClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_configure_bucket_fails_when_key_exists_without_secret(self):
        client = GarageClient()
        client._ensure_layout = AsyncMock()
        client.list_keys = AsyncMock(
            return_value=[
                ListGarageKeysResponseItem(
                    accessKeyId="existing-access-key",
                    name="aistudio-artifacts-key",
                )
            ]
        )
        client.delete_key = AsyncMock()
        client.create_key = AsyncMock()

        with self.assertRaises(GarageKeyConflictError) as ctx:
            await client._configure_bucket(
                client=AsyncMock(),
                garage_admin_token=SecretStr("admin-token"),
                tapis_token=SecretStr("user-token"),
                key_name="aistudio-artifacts-key",
                bucket_alias="aistudio-artifacts",
                layout_zone="dc1",
                layout_capacity=1024,
            )

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("Manual cleanup", ctx.exception.detail["details"])
        client.delete_key.assert_not_called()
        client.create_key.assert_not_called()
