"""Tests for logger configuration and request-id handling."""

import json
import logging
import re
import unittest

from ai_studio_orchestrator.context import REQUEST_ID_VAR
from ai_studio_orchestrator.logger import (
    JsonFormatter,
    PassThroughQueueHandler,
    RequestIDFilter,
)
from ai_studio_orchestrator.main import _sanitize_request_id


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class SanitizeRequestIdTest(unittest.TestCase):
    def test_accepts_valid_id(self) -> None:
        self.assertEqual(_sanitize_request_id("req-123_abc"), "req-123_abc")

    def test_rejects_newline_injection(self) -> None:
        result = _sanitize_request_id("abc\nINFO:    forged")
        self.assertTrue(_UUID_RE.fullmatch(result), result)

    def test_rejects_carriage_return(self) -> None:
        result = _sanitize_request_id("abc\r\nfake")
        self.assertTrue(_UUID_RE.fullmatch(result), result)

    def test_rejects_ansi_escape(self) -> None:
        result = _sanitize_request_id("abc\x1b[31mred")
        self.assertTrue(_UUID_RE.fullmatch(result), result)

    def test_rejects_overlong(self) -> None:
        result = _sanitize_request_id("a" * 65)
        self.assertTrue(_UUID_RE.fullmatch(result), result)

    def test_rejects_empty(self) -> None:
        result = _sanitize_request_id("")
        self.assertTrue(_UUID_RE.fullmatch(result), result)

    def test_rejects_none(self) -> None:
        result = _sanitize_request_id(None)
        self.assertTrue(_UUID_RE.fullmatch(result), result)


class RequestIDFilterTest(unittest.TestCase):
    def _make_record(self) -> logging.LogRecord:
        return logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="m",
            args=(),
            exc_info=None,
        )

    def test_attaches_default_when_unset(self) -> None:
        record = self._make_record()
        RequestIDFilter().filter(record)
        self.assertEqual(record.request_id, "-")

    def test_attaches_valid_value_from_contextvar(self) -> None:
        token = REQUEST_ID_VAR.set("rid-abc_123")
        try:
            record = self._make_record()
            RequestIDFilter().filter(record)
            self.assertEqual(record.request_id, "rid-abc_123")
        finally:
            REQUEST_ID_VAR.reset(token)

    def test_rejects_hostile_value_in_contextvar(self) -> None:
        # Defense in depth: even if middleware were bypassed, the filter
        # itself refuses anything outside the allowlist.
        token = REQUEST_ID_VAR.set("abc\nINJECTED")
        try:
            record = self._make_record()
            RequestIDFilter().filter(record)
            self.assertEqual(record.request_id, "-")
        finally:
            REQUEST_ID_VAR.reset(token)


class JsonFormatterTest(unittest.TestCase):
    def _record(self, **kwargs) -> logging.LogRecord:
        defaults = dict(
            name="ai_studio_orchestrator.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=42,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        defaults.update(kwargs)
        return logging.LogRecord(**defaults)

    def test_emits_valid_json_with_core_fields(self) -> None:
        record = self._record()
        record.request_id = "rid-1"

        line = JsonFormatter().format(record)
        payload = json.loads(line)

        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "ai_studio_orchestrator.test")
        self.assertEqual(payload["message"], "hello world")
        self.assertEqual(payload["request_id"], "rid-1")
        self.assertEqual(payload["lineno"], 42)
        self.assertIn("timestamp", payload)

    def test_includes_exception_traceback(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
        record = self._record(exc_info=exc_info)

        payload = json.loads(JsonFormatter().format(record))

        self.assertIn("exception", payload)
        self.assertIn("ValueError: boom", payload["exception"])

    def test_passes_through_extras_as_top_level_fields(self) -> None:
        record = self._record()
        record.user_id = "u-7"
        record.duration_ms = 12.5

        payload = json.loads(JsonFormatter().format(record))

        self.assertEqual(payload["user_id"], "u-7")
        self.assertEqual(payload["duration_ms"], 12.5)


class PassThroughQueueHandlerTest(unittest.TestCase):
    """Regression: stdlib QueueHandler.prepare() drops exc_info and pre-formats
    the message, which corrupts both our JSON formatter (no exception field)
    and our request_id filter (which needs to run before threading)."""

    def _record_with_exc(self) -> logging.LogRecord:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
        return logging.LogRecord(
            name="t",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="hi %s",
            args=("there",),
            exc_info=exc_info,
        )

    def test_prepare_preserves_exc_info(self) -> None:
        import queue

        handler = PassThroughQueueHandler(queue.Queue())
        record = self._record_with_exc()

        prepared = handler.prepare(record)

        self.assertIsNotNone(prepared.exc_info)
        self.assertEqual(prepared.args, ("there",))
        self.assertEqual(prepared.msg, "hi %s")

    def test_prepare_returns_a_copy(self) -> None:
        import queue

        handler = PassThroughQueueHandler(queue.Queue())
        record = self._record_with_exc()

        prepared = handler.prepare(record)

        self.assertIsNot(prepared, record)


if __name__ == "__main__":
    unittest.main()
