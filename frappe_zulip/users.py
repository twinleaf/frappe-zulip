import frappe
from frappe.utils import strip_html

from frappe_zulip import formatting
from frappe_zulip.zulip import ZulipClient


def get_zulip_recipient(user: str) -> int | str | None:
	"""Zulip user ID if synced, else the email address. None for disabled users."""
	row = frappe.db.get_value("User", user, ["enabled", "email", "zulip_user_id"], as_dict=True)
	if not row or not row.enabled:
		return None
	return row.zulip_user_id or row.email or None


def wants_zulip_dms(user: str) -> bool:
	value = frappe.db.get_value("Notification Settings", user, "enable_zulip_notifications")
	# Users who never opened their notification settings have no record yet.
	return value is None or bool(value)


def get_mention(user: str | None, silent: bool = False) -> str:
	"""A Zulip @-mention for a synced user, otherwise their full name."""
	if not user:
		return ""
	row = frappe.db.get_value("User", user, ["full_name", "zulip_user_id"], as_dict=True)
	if not row:
		return user
	name = row.full_name or user
	return formatting.mention(name, row.zulip_user_id, silent) if row.zulip_user_id else name


def get_topic(doctype: str, name: str) -> str:
	"""A stable topic per document, e.g. "TASK-2026-00042: Calibrate magnetometer"."""
	title_field = frappe.get_meta(doctype).get_title_field()
	title = name if title_field == "name" else frappe.db.get_value(doctype, name, title_field)
	# Title fields can be Text Editor fields.
	title = strip_html(str(title or "")).strip()
	if not title or title == str(name):
		return formatting.topic(str(name))
	return formatting.topic(f"{name}: {title}")


def sync_users(client: ZulipClient) -> dict:
	"""Store each ERPNext user's Zulip user ID, matched by email."""
	ids_by_email = {}
	zulip_users = 0
	for member in client.get_users():
		if member.get("is_bot") or not member.get("is_active", True):
			continue
		zulip_users += 1
		# delivery_email is the real address; email may be a placeholder, depending on visibility.
		for key in ("delivery_email", "email"):
			if email := member.get(key):
				ids_by_email.setdefault(email.lower(), member["user_id"])

	users = frappe.get_all(
		"User",
		filters={
			"enabled": 1,
			"user_type": "System User",
			"name": ("not in", ("Administrator", "Guest")),
		},
		fields=["name", "email", "zulip_user_id"],
		order_by="name",
	)
	matched, unmatched = 0, []
	for user in users:
		user_id = ids_by_email.get((user.email or "").lower())
		if not user_id:
			# Leave IDs that were set by hand alone.
			if not user.zulip_user_id:
				unmatched.append(user.name)
			continue
		matched += 1
		if user.zulip_user_id != user_id:
			frappe.db.set_value("User", user.name, "zulip_user_id", user_id, update_modified=False)

	return {"zulip_users": zulip_users, "matched": matched, "unmatched": unmatched}
