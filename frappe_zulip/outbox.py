"""Queue Zulip messages as Zulip Message records and deliver them in the background.

Each message gets an immediate background job. The scheduler sweep retries messages that hit a
transient error and catches any whose job was lost.
"""

import frappe
from frappe.utils import now_datetime

from frappe_zulip import formatting
from frappe_zulip.frappe_zulip.doctype.zulip_settings.zulip_settings import get_settings
from frappe_zulip.users import wants_zulip_dms

SWEEP_BATCH_SIZE = 100


def queue_channel_message(
	channel: str,
	topic: str,
	content: str,
	*,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	source: str | None = None,
) -> str | None:
	return _queue(
		message_type="Channel",
		channel=channel.strip().lstrip("#"),
		topic=formatting.topic(topic),
		content=content,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		source=source,
	)


def queue_direct_message(
	user: str,
	content: str,
	*,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	source: str | None = None,
) -> str | None:
	if not wants_zulip_dms(user):
		return None
	return _queue(
		message_type="Direct",
		user=user,
		content=content,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		source=source,
	)


def _queue(**fields) -> str | None:
	if not _should_queue():
		return None
	fields["content"] = formatting.content(fields["content"])
	doc = frappe.get_doc({"doctype": "Zulip Message", **fields})
	# A deleted reference document shouldn't stop the message.
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _should_queue() -> bool:
	flags = frappe.flags
	if flags.in_install or flags.in_migrate or flags.in_patch:
		return False
	if flags.in_import and flags.mute_emails:
		return False
	return bool(get_settings().enabled)


def deliver(name: str):
	# The row lock stops the immediate job and the sweep from sending the same message twice.
	row = frappe.db.get_value(
		"Zulip Message", name, ["status", "attempts", "next_attempt"], as_dict=True, for_update=True
	)
	if not row or row.status != "Queued":
		return
	# Only the first attempt may run early; retries wait for their backoff.
	if row.attempts and row.next_attempt and row.next_attempt > now_datetime():
		return
	frappe.get_doc("Zulip Message", name).send()


def retry_pending():
	names = frappe.get_all(
		"Zulip Message",
		filters={"status": "Queued", "next_attempt": ("<=", now_datetime())},
		order_by="creation asc",
		limit=SWEEP_BATCH_SIZE,
		pluck="name",
	)
	for name in names:
		try:
			deliver(name)
			frappe.db.commit()  # nosemgrep: each message is independent
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				"Zulip message delivery failed", reference_doctype="Zulip Message", reference_name=name
			)
