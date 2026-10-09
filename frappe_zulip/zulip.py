"""Minimal Zulip REST client. Kept free of Frappe imports so it can be tested standalone."""

import json

import requests

from frappe_zulip import __version__

TIMEOUT = 10


class ZulipError(Exception):
	def __init__(
		self,
		message: str,
		*,
		status: int | None = None,
		code: str | None = None,
		retry_after: float | None = None,
	):
		super().__init__(message)
		self.status = status
		self.code = code
		self.retry_after = retry_after

	@property
	def retryable(self) -> bool:
		# No status means no response at all: timeout, DNS failure, connection reset.
		return self.status is None or self.status == 429 or self.status >= 500


class ZulipClient:
	def __init__(self, server_url: str, email: str, api_key: str, timeout: float = TIMEOUT):
		self.base_url = server_url.rstrip("/") + "/api/v1"
		self.timeout = timeout
		self.session = requests.Session()
		self.session.auth = (email, api_key)
		self.session.headers["User-Agent"] = f"frappe_zulip/{__version__}"

	def send_channel_message(self, channel: str, topic: str, content: str) -> int:
		data = {"type": "channel", "to": channel, "topic": topic, "content": content}
		return self._request("POST", "messages", data=data)["id"]

	def send_direct_message(self, to: list[int | str], content: str) -> int:
		data = {"type": "direct", "to": json.dumps(to), "content": content}
		return self._request("POST", "messages", data=data)["id"]

	def get_users(self) -> list[dict]:
		return self._request("GET", "users")["members"]

	def _request(self, method: str, path: str, **kwargs) -> dict:
		try:
			response = self.session.request(method, f"{self.base_url}/{path}", timeout=self.timeout, **kwargs)
		except requests.RequestException as e:
			raise ZulipError(f"Could not reach Zulip: {e}")

		try:
			body = response.json()
		except ValueError:
			body = {}
		if not isinstance(body, dict):
			body = {}

		if response.ok and body.get("result") == "success":
			return body

		raise ZulipError(
			body.get("msg") or f"Unexpected response from Zulip (HTTP {response.status_code})",
			status=response.status_code,
			code=body.get("code"),
			retry_after=_retry_after(response, body),
		)


def _retry_after(response: requests.Response, body: dict) -> float | None:
	value = response.headers.get("Retry-After") or body.get("retry-after")
	try:
		return float(value) if value is not None else None
	except TypeError, ValueError:
		return None
