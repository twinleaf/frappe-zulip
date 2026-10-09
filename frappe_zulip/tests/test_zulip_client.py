import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from frappe_zulip.zulip import ZulipClient, ZulipError


def response(status=200, body=None, headers=None, text=None):
	resp = MagicMock(spec=requests.Response)
	resp.status_code = status
	resp.ok = status < 400
	resp.headers = headers or {}
	if text is not None:
		resp.json.side_effect = ValueError(text)
	else:
		resp.json.return_value = body
	return resp


class TestZulipClient(unittest.TestCase):
	def setUp(self):
		self.client = ZulipClient("https://zulip.example.com/", "bot@zulip.example.com", "key")
		self.request = patch.object(self.client.session, "request").start()
		self.addCleanup(patch.stopall)

	def test_session_setup(self):
		self.assertEqual(self.client.base_url, "https://zulip.example.com/api/v1")
		self.assertEqual(self.client.session.auth, ("bot@zulip.example.com", "key"))

	def test_send_channel_message(self):
		self.request.return_value = response(body={"result": "success", "id": 42})
		self.assertEqual(self.client.send_channel_message("erp", "TASK-1", "hi"), 42)
		self.request.assert_called_once_with(
			"POST",
			"https://zulip.example.com/api/v1/messages",
			timeout=10,
			data={"type": "channel", "to": "erp", "topic": "TASK-1", "content": "hi"},
		)

	def test_send_direct_message(self):
		self.request.return_value = response(body={"result": "success", "id": 43})
		self.assertEqual(self.client.send_direct_message([7], "hi"), 43)
		data = self.request.call_args.kwargs["data"]
		self.assertEqual(data["type"], "direct")
		self.assertEqual(json.loads(data["to"]), [7])

	def test_get_users(self):
		members = [{"user_id": 7, "email": "ada@example.com"}]
		self.request.return_value = response(body={"result": "success", "members": members})
		self.assertEqual(self.client.get_users(), members)

	def test_client_error_is_permanent(self):
		self.request.return_value = response(
			400, {"result": "error", "msg": "Channel 'nope' does not exist", "code": "STREAM_DOES_NOT_EXIST"}
		)
		with self.assertRaises(ZulipError) as ctx:
			self.client.send_channel_message("nope", "t", "hi")
		self.assertEqual(str(ctx.exception), "Channel 'nope' does not exist")
		self.assertEqual(ctx.exception.code, "STREAM_DOES_NOT_EXIST")
		self.assertFalse(ctx.exception.retryable)

	def test_rate_limit_is_retryable(self):
		self.request.return_value = response(
			429, {"result": "error", "msg": "API usage exceeded rate limit"}, {"Retry-After": "7"}
		)
		with self.assertRaises(ZulipError) as ctx:
			self.client.send_channel_message("erp", "t", "hi")
		self.assertTrue(ctx.exception.retryable)
		self.assertEqual(ctx.exception.retry_after, 7.0)

	def test_rate_limit_from_body(self):
		self.request.return_value = response(429, {"result": "error", "msg": "slow down", "retry-after": 2.5})
		with self.assertRaises(ZulipError) as ctx:
			self.client.send_channel_message("erp", "t", "hi")
		self.assertEqual(ctx.exception.retry_after, 2.5)

	def test_server_error_without_json(self):
		self.request.return_value = response(502, text="<html>Bad Gateway</html>")
		with self.assertRaises(ZulipError) as ctx:
			self.client.send_channel_message("erp", "t", "hi")
		self.assertIn("HTTP 502", str(ctx.exception))
		self.assertTrue(ctx.exception.retryable)

	def test_success_status_without_success_result(self):
		self.request.return_value = response(200, ["unexpected"])
		with self.assertRaises(ZulipError):
			self.client.send_channel_message("erp", "t", "hi")

	def test_connection_error_is_retryable(self):
		self.request.side_effect = requests.ConnectionError("connection refused")
		with self.assertRaises(ZulipError) as ctx:
			self.client.send_channel_message("erp", "t", "hi")
		self.assertIsNone(ctx.exception.status)
		self.assertTrue(ctx.exception.retryable)
