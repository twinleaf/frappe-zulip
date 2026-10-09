import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now
from frappe.utils import add_to_date, now_datetime

from frappe_zulip.frappe_zulip.doctype.zulip_settings.zulip_settings import get_settings
from frappe_zulip.users import get_zulip_recipient
from frappe_zulip.zulip import ZulipError

MAX_ATTEMPTS = 5
# Minutes to wait before attempts 2, 3, 4 and 5.
RETRY_DELAYS = (1, 5, 15, 60)
# Head start for the immediate job before the scheduler sweep picks a queued message up.
SWEEP_GRACE_MINUTES = 2


class ZulipMessage(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		attempts: DF.Int
		channel: DF.Data | None
		content: DF.Code
		error: DF.Code | None
		message_type: DF.Literal["Channel", "Direct"]
		next_attempt: DF.Datetime | None
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		sent_at: DF.Datetime | None
		source: DF.Data | None
		status: DF.Literal["Queued", "Sent", "Failed", "Skipped"]
		topic: DF.Data | None
		user: DF.Link | None
		zulip_message_id: DF.Int
	# end: auto-generated types

	def before_insert(self):
		self.next_attempt = add_to_date(now_datetime(), minutes=SWEEP_GRACE_MINUTES)

	def after_insert(self):
		self.enqueue_delivery()

	def enqueue_delivery(self):
		frappe.enqueue(
			"frappe_zulip.outbox.deliver",
			queue="short",
			name=self.name,
			enqueue_after_commit=True,
		)

	def send(self):
		settings = get_settings()
		if not settings.enabled:
			return self._finish("Skipped", "Zulip integration is disabled")
		if settings.dry_run:
			return self._finish("Skipped", "Dry run")

		try:
			client = settings.get_client()
		except frappe.ValidationError as e:
			return self._finish("Failed", str(e))

		recipient = None
		if self.message_type == "Direct":
			recipient = get_zulip_recipient(self.user)
			if not recipient:
				return self._finish("Failed", f"{self.user} is disabled or has no email address")

		self.attempts += 1
		try:
			if self.message_type == "Direct":
				self.zulip_message_id = client.send_direct_message([recipient], self.content)
			else:
				self.zulip_message_id = client.send_channel_message(self.channel, self.topic, self.content)
		except ZulipError as e:
			if e.retryable and self.attempts < MAX_ATTEMPTS:
				delay = max(e.retry_after or 0, RETRY_DELAYS[self.attempts - 1] * 60)
				self.next_attempt = add_to_date(now_datetime(), seconds=delay)
				self.error = str(e)
				return self._persist()
			return self._finish("Failed", self._describe(e, recipient))
		except Exception:
			return self._finish("Failed", frappe.get_traceback())

		self.sent_at = now_datetime()
		self._finish("Sent", None)

	def _finish(self, status: str, error: str | None):
		self.status = status
		self.error = error
		self.next_attempt = None
		self._persist()

	def _persist(self):
		# The reference document or recipient may have been deleted since the message was queued.
		self.flags.ignore_links = True
		self.save(ignore_permissions=True)

	@staticmethod
	def _describe(error: ZulipError, recipient: int | str | None) -> str:
		if isinstance(recipient, str) and error.status == 400:
			# Addressed by email, which only works if Zulip shows real emails to the bot.
			return _("{0}. Run Sync Users in Zulip Settings to map this user to their Zulip account.").format(
				error
			)
		return str(error)

	@frappe.whitelist()
	def retry(self):
		if self.status not in ("Failed", "Skipped"):
			frappe.throw(_("Only failed or skipped messages can be retried"))
		self.status = "Queued"
		self.attempts = 0
		self.error = None
		self.next_attempt = add_to_date(now_datetime(), minutes=SWEEP_GRACE_MINUTES)
		self.flags.ignore_links = True
		self.save()
		self.enqueue_delivery()

	@staticmethod
	def clear_old_logs(days=30):
		table = frappe.qb.DocType("Zulip Message")
		frappe.db.delete(
			table,
			filters=(table.modified < (Now() - Interval(days=days))) & (table.status != "Queued"),
		)
