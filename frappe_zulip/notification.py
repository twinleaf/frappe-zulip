import frappe
from frappe import _
from frappe.email.doctype.notification.notification import get_reference_doctype, get_reference_name
from frappe.utils import get_url_to_form
from frappe.utils.jinja import validate_template

from frappe_zulip import formatting
from frappe_zulip.frappe_zulip.doctype.zulip_settings.zulip_settings import get_settings
from frappe_zulip.outbox import queue_channel_message, queue_direct_message
from frappe_zulip.users import get_mention, get_topic


class ZulipNotificationMixin:
	"""Adds the Zulip channel to Notification."""

	def validate(self):
		super().validate()
		if self.channel != "Zulip":
			return
		if not (self.zulip_post_to_channel or self.zulip_dm_recipients):
			frappe.throw(_("Turn on Post to Zulip Channel, Direct Message Each Recipient, or both"))
		if self.zulip_post_to_channel and not (self.zulip_stream or get_settings().default_channel):
			frappe.throw(_("Set a Zulip channel, or a default channel in Zulip Settings"))
		if (self.mentions_recipients() or self.zulip_dm_recipients) and not (
			self.recipients or self.send_to_all_assignees
		):
			frappe.throw(_("Add recipients or turn on Send To All Assignees"))
		if self.zulip_topic:
			validate_template(self.zulip_topic)

	def send_notification_by_channel(self, doc, context):
		if self.channel == "Zulip":
			try:
				self.send_zulip_message(doc, context)
			except Exception:
				self.log_error("Failed to send Zulip notification")
		super().send_notification_by_channel(doc, context)

	def send_zulip_message(self, doc, context):
		context = {**context, "zulip": frappe._dict(mention=get_mention, topic=get_topic)}
		reference_doctype, reference_name = get_reference_doctype(doc), get_reference_name(doc)
		reference = {
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"source": f"Notification: {self.name}",
		}

		content = frappe.render_template(self.message, context).strip()
		url = get_url_to_form(reference_doctype, reference_name)
		if url not in content:
			content += "\n\n" + formatting.link(f"{_(reference_doctype)} {reference_name}", url)

		users = []
		if self.zulip_dm_recipients or self.mentions_recipients():
			users = self.get_zulip_users(doc, context)

		if self.zulip_post_to_channel:
			self.post_to_channel(context, content, users, reference)

		if self.zulip_dm_recipients:
			for user in users:
				queue_direct_message(user, content, **reference)

	def post_to_channel(self, context, content, users, reference):
		settings = get_settings()
		channel = self.zulip_stream or settings.default_channel
		if not channel:
			self.log_error("No Zulip channel set, and Zulip Settings has no default channel")
			return
		if self.zulip_topic:
			topic = frappe.render_template(self.zulip_topic, context)
		else:
			topic = settings.default_topic or get_topic(
				reference["reference_doctype"], reference["reference_name"]
			)
		if self.mentions_recipients() and users:
			content = " ".join(get_mention(user) for user in users) + "\n\n" + content
		queue_channel_message(channel, topic, content, **reference)

	def mentions_recipients(self) -> bool:
		return bool(self.zulip_post_to_channel and self.zulip_mention_recipients)

	def get_zulip_users(self, doc, context) -> list[str]:
		"""Enabled system users among the recipients, which core resolves to email addresses."""
		recipients, cc, bcc = self.get_list_of_recipients(doc, context)
		addresses = {address.strip() for address in (*recipients, *cc, *bcc) if address and address.strip()}
		if not addresses:
			return []
		users = frappe.get_all(
			"User",
			filters={"enabled": 1, "user_type": "System User"},
			or_filters={"name": ("in", addresses), "email": ("in", addresses)},
			pluck="name",
		)
		return sorted(set(users))
