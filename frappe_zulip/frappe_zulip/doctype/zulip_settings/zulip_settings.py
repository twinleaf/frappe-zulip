import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_fullname, get_url

from frappe_zulip import formatting
from frappe_zulip.zulip import ZulipClient, ZulipError


class ZulipSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.desk.doctype.notification_type_preference.notification_type_preference import (
			NotificationTypePreference,
		)
		from frappe.types import DF

		api_key: DF.Password | None
		bot_email: DF.Data | None
		default_channel: DF.Data | None
		default_topic: DF.Data | None
		dm_notification_types: DF.TableMultiSelect[NotificationTypePreference]
		dry_run: DF.Check
		enabled: DF.Check
		server_url: DF.Data | None
	# end: auto-generated types

	def validate(self):
		self.server_url = (self.server_url or "").strip().rstrip("/")
		self.default_channel = (self.default_channel or "").strip().lstrip("#")

	def get_client(self, email: str | None = None, api_key: str | None = None) -> ZulipClient:
		email = email or self.bot_email
		api_key = api_key or self.get_password("api_key", raise_exception=False)
		if not (self.server_url and email and api_key):
			frappe.throw(_("Set the Zulip server URL, bot email and API key in Zulip Settings"))
		return ZulipClient(self.server_url, email, api_key)

	def get_dm_types(self) -> set[str]:
		return {row.notification_type for row in self.dm_notification_types}

	@frappe.whitelist()
	def send_test_message(self, channel: str, topic: str) -> int:
		content = _("Test message from ERPNext ({0}), sent by {1}.").format(get_url(), get_fullname())
		try:
			return self.get_client().send_channel_message(
				channel.strip().lstrip("#"), formatting.topic(topic), content
			)
		except ZulipError as e:
			frappe.throw(str(e), title=_("Zulip rejected the test message"))

	@frappe.whitelist()
	def sync_users(self, admin_email: str | None = None, admin_api_key: str | None = None) -> dict:
		from frappe_zulip.users import sync_users

		# Incoming webhook bots may not list users, so an admin's key can be supplied for this call only.
		if bool(admin_email) != bool(admin_api_key):
			frappe.throw(_("Enter both the admin email and API key, or neither"))
		try:
			return sync_users(self.get_client(admin_email, admin_api_key))
		except ZulipError as e:
			frappe.throw(str(e), title=_("Could not fetch Zulip users"))


def get_settings() -> ZulipSettings:
	return frappe.get_cached_doc("Zulip Settings")
